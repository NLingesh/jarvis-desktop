"""Text-to-speech manager.

Provider architecture::

    TTSManager
    ├── KokoroProvider (PRIMARY — local)
    └── ElevenLabsProvider (OPTIONAL fallback)

The primary provider is selected by the ``TTS_PROVIDER`` env var
(``kokoro`` | ``elevenlabs``). Kokoro runs fully offline and is the default.
ElevenLabs is used only when it is the explicitly selected provider, or as a
fallback when Kokoro fails and a valid API key + voice are configured.

Final fallbacks (no key required) are Microsoft Edge TTS and system
espeak/piper/say. A permanent config error (ElevenLabs 404) is never retried;
transient errors fall through to the next provider.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import AsyncGenerator

from managers.tts.base import TTSConfigError
from managers.tts.elevenlabs_provider import ElevenLabsProvider
from managers.tts.kokoro_provider import KokoroProvider

logger = logging.getLogger(__name__)

try:
    import edge_tts

    EDGE_TTS_AVAILABLE = True
except Exception:
    EDGE_TTS_AVAILABLE = False


class TTSManager:
    """Unified text-to-speech with a provider chain.

    Backend priority:
    1. Selected primary (Kokoro by default)
    2. The other provider (ElevenLabs / Kokoro) if available
    3. Edge TTS (cloud, no key required)
    4. System TTS (espeak/piper/say)
    """

    def __init__(
        self,
        kokoro_model_path: str | None = None,
        elevenlabs_api_key: str | None = None,
        elevenlabs_voice_id: str | None = None,
        edge_tts_voice: str | None = None,
        primary: str | None = None,
    ):
        self.kokoro_model_path = kokoro_model_path or os.getenv("KOKORO_MODEL_PATH")
        self.edge_tts_voice = edge_tts_voice or os.getenv("EDGE_TTS_VOICE", "en-US-GuyNeural")

        self.kokoro = KokoroProvider(model_path=self.kokoro_model_path)
        self.elevenlabs = ElevenLabsProvider(
            api_key=elevenlabs_api_key,
            voice_id=elevenlabs_voice_id,
        )

        primary = (primary or os.getenv("TTS_PROVIDER", "kokoro")).lower()
        if primary not in ("kokoro", "elevenlabs"):
            logger.warning("Unknown TTS_PROVIDER %r — defaulting to kokoro", primary)
            primary = "kokoro"
        self.primary = primary

        self._load_lock = asyncio.Lock()

    # ------------------------------------------------------------------ status

    def diagnostics(self) -> dict:
        return {
            "provider": self.primary,
            "kokoro_available": self.kokoro.available(),
            "kokoro_loaded": self.kokoro.diagnostics()["loaded"],
            "kokoro_voice": self.kokoro.voice,
            "elevenlabs_configured": bool(self.elevenlabs.api_key),
            "elevenlabs_available": self.elevenlabs.available(),
            "elevenlabs_voice_id": self.elevenlabs.voice_id,
            "edge_tts_available": EDGE_TTS_AVAILABLE,
            "edge_tts_voice": self.edge_tts_voice,
            "system_engines": [e for e in ("espeak-ng", "espeak", "piper") if shutil.which(e)],
            "ready": self.available,
        }

    @property
    def available(self) -> bool:
        return (
            self.kokoro.available()
            or self.elevenlabs.available()
            or EDGE_TTS_AVAILABLE
            or any(shutil.which(e) for e in ("espeak-ng", "espeak", "piper", "say"))
        )

    def preload(self) -> bool:
        """Warm up the primary provider in a background thread (best effort)."""
        if self.primary == "kokoro":
            with contextlib.suppress(Exception):
                self.kokoro._ensure_pipeline()
                return True
        return self.available

    async def _preload_async_impl(self) -> None:
        await asyncio.to_thread(self.preload)

    # ------------------------------------------------------------- provider chain

    def _ordered_providers(self):
        """Return providers in priority order for the configured primary."""
        providers = [self.kokoro, self.elevenlabs]
        if self.primary == "elevenlabs":
            providers = [self.elevenlabs, self.kokoro]
        return [(p.name, p) for p in providers if p.available()]

    def _log(self, level: int, msg: str, **fields) -> None:
        logger.log(level, msg, extra={"provider": fields.pop("provider", None), **fields})

    # ------------------------------------------------------------------ generate

    async def generate_speech(
        self, text: str, voice_id: str | None = None, retries: int = 2
    ) -> str:
        """Generate speech and return base64 audio, falling back across providers."""
        for name, provider in self._ordered_providers():
            try:
                audio = await provider.generate(text, voice_id)
                if audio:
                    logger.info(
                        "TTS generated (provider=%s, chars=%d)",
                        name,
                        len(text),
                        extra={"provider": name, "status": "completed", "chars": len(text)},
                    )
                    return self._to_base64(audio)
            except TTSConfigError as e:
                logger.warning(
                    "TTS config error, skipping provider %s: %s",
                    name,
                    e,
                    extra={"provider": name, "status": "config_error", "error": str(e)},
                )
            except TimeoutError:
                logger.warning(
                    "TTS timed out on %s", name, extra={"provider": name, "status": "timeout"}
                )
            except Exception as e:
                logger.warning(
                    "TTS failed on %s: %s",
                    name,
                    e,
                    extra={"provider": name, "status": "failed", "error": str(e)},
                )

        # No-key fallbacks.
        b64 = await self._edge_or_system(text)
        if b64:
            return b64

        logger.error(
            "All TTS providers failed",
            extra={"provider": "all", "status": "failed", "chars": len(text)},
        )
        return ""

    # ------------------------------------------------------------------ stream

    async def stream_speech(
        self, text: str, voice_id: str | None = None
    ) -> AsyncGenerator[str, None]:
        """Stream speech as base64-encoded chunks, falling back across providers."""
        for name, provider in self._ordered_providers():
            try:
                got_any = False
                async for audio in provider.stream(text, voice_id):
                    got_any = True
                    yield self._to_base64(audio)
                if got_any:
                    logger.info(
                        "TTS streamed (provider=%s, chars=%d)",
                        name,
                        len(text),
                        extra={"provider": name, "status": "completed", "chars": len(text)},
                    )
                    return
            except TTSConfigError as e:
                logger.warning(
                    "TTS config error, skipping provider %s: %s",
                    name,
                    e,
                    extra={"provider": name, "status": "config_error", "error": str(e)},
                )
            except Exception as e:
                logger.warning(
                    "TTS stream failed on %s: %s",
                    name,
                    e,
                    extra={"provider": name, "status": "failed", "error": str(e)},
                )

        got_edge = False
        async for chunk in self._edge_tts_stream(text):
            got_edge = True
            yield self._to_base64(chunk)
        if got_edge:
            return

        b64 = await self._system_tts(text)
        if b64:
            yield b64

    # ------------------------------------------------------------ keyless fallbacks

    async def _edge_or_system(self, text: str) -> str:
        if EDGE_TTS_AVAILABLE:
            try:
                audio = await self._edge_tts(text)
                if audio:
                    return self._to_base64(audio)
            except Exception as e:
                logger.warning("Edge TTS failed: %s", e)
        return await self._system_tts(text)

    async def _edge_tts(self, text: str) -> bytes:
        if not EDGE_TTS_AVAILABLE:
            return b""
        communicate = edge_tts.Communicate(text, self.edge_tts_voice)
        chunks = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio" and chunk.get("data"):
                chunks.append(chunk["data"])
        return b"".join(chunks)

    async def _edge_tts_stream(self, text: str) -> AsyncGenerator[bytes, None]:
        if not EDGE_TTS_AVAILABLE:
            return
        communicate = edge_tts.Communicate(text, self.edge_tts_voice)
        async for chunk in communicate.stream():
            if chunk["type"] == "audio" and chunk.get("data"):
                yield chunk["data"]

    async def _system_tts(self, text: str) -> str:
        engine = self._find_tts_engine()
        if not engine:
            return ""

        with tempfile.NamedTemporaryFile(suffix=".wav", prefix="jarvis_tts_", delete=False) as tmp:
            audio_path = tmp.name
        try:
            if engine in ("espeak-ng", "espeak"):
                await asyncio.to_thread(
                    subprocess.run,
                    [engine, "-w", audio_path, text],
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
            elif engine == "piper":
                await asyncio.to_thread(
                    subprocess.run,
                    ["piper", "--tts", "--voice", "alloy", "--output", audio_path, "--text", text],
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
            else:
                return ""

            with open(audio_path, "rb") as f:
                return self._to_base64(f.read())
        except subprocess.CalledProcessError as e:
            logger.error("Local TTS failed: %s", e)
            return ""
        except FileNotFoundError:
            if sys.platform == "darwin":
                return await self._macos_say(text)
            return ""
        finally:
            with contextlib.suppress(OSError):
                os.unlink(audio_path)

    async def _macos_say(self, text: str) -> str:
        with tempfile.NamedTemporaryFile(suffix=".aiff", prefix="jarvis_tts_", delete=False) as tmp:
            audio_path = tmp.name
        try:
            await asyncio.to_thread(
                subprocess.run,
                ["say", "-o", audio_path, text],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            with open(audio_path, "rb") as f:
                return self._to_base64(f.read())
        except Exception as e:
            logger.error("macOS say failed: %s", e)
            return ""
        finally:
            with contextlib.suppress(OSError):
                os.unlink(audio_path)

    def _find_tts_engine(self) -> str | None:
        for engine in ("espeak-ng", "espeak", "piper"):
            if shutil.which(engine):
                return engine
        return None

    @staticmethod
    def _to_base64(audio_data: bytes) -> str:
        return base64.b64encode(audio_data).decode("utf-8")
