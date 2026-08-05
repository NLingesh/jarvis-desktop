import os
import base64
import subprocess
import shutil
import sys
import tempfile
from typing import Optional
import logging

logger = logging.getLogger(__name__)

class TextToSpeechModule:
    def __init__(self):
        self.elevenlabs_api_key = os.getenv("ELEVENLABS_API_KEY")
        self.voice_id = "9BBfe6637e99185c8b146cb8f3523044"  # Default ElevenLabs voice
        self.use_elevenlabs = bool(self.elevenlabs_api_key)
        self.edge_tts_voice = os.getenv("EDGE_TTS_VOICE", "en-US-GuyNeural")

    async def generate_speech(self, text: str, voice_id: Optional[str] = None) -> str:
        """Generate speech and return as base64 audio"""
        if self.use_elevenlabs:
            try:
                audio_data = await self._elevenlabs_tts(text, voice_id)
                return self._to_base64(audio_data)
            except Exception as e:
                logger.warning(f"ElevenLabs failed, falling back to local TTS: {e}")

        try:
            audio_data = await self._edge_tts(text)
            return self._to_base64(audio_data)
        except Exception as e:
            logger.warning(f"Edge TTS failed, falling back to system TTS: {e}")

        return await self._system_tts(text)

    async def _elevenlabs_tts(self, text: str, voice_id: Optional[str] = None) -> bytes:
        """Call ElevenLabs API"""
        import httpx

        voice_id = voice_id or self.voice_id

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
                headers={
                    "xi-api-key": self.elevenlabs_api_key,
                    "Content-Type": "application/json"
                },
                json={
                    "text": text,
                    "model_id": "eleven_monolingual_v1",
                    "voice_settings": {
                        "stability": 0.75,
                        "similarity_boost": 0.75
                    }
                }
            )

            if response.status_code == 200:
                return response.content

            raise Exception(f"ElevenLabs API error: {response.status_code} {response.text}")

    async def stream_speech(self, text: str, voice_id: Optional[str] = None):
        """Stream speech audio in base64-encoded chunks.

        Yields base64 strings for successive chunks. If ElevenLabs is not available,
        yields a single full base64 audio chunk from the local TTS fallback.
        """
        if self.use_elevenlabs:
            import httpx
            voice_id = voice_id or self.voice_id

            async with httpx.AsyncClient(timeout=None) as client:
                url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
                headers = {
                    "xi-api-key": self.elevenlabs_api_key,
                    "Content-Type": "application/json"
                }
                payload = {
                    "text": text,
                    "model_id": "eleven_monolingual_v1",
                    "voice_settings": {"stability": 0.75, "similarity_boost": 0.75}
                }
                try:
                    async with client.stream("POST", url, headers=headers, json=payload) as r:
                        r.raise_for_status()
                        # stream raw bytes and yield base64-encoded chunks
                        async for chunk in r.aiter_bytes():
                            if not chunk:
                                continue
                            yield base64.b64encode(chunk).decode("utf-8")
                        return
                except Exception as e:
                    logger.warning(f"ElevenLabs streaming failed: {e}")

        # Edge TTS (Microsoft neural voices, no API key required)
        try:
            import edge_tts
            communicate = edge_tts.Communicate(text, self.edge_tts_voice)
            async for chunk in communicate.stream():
                if chunk["type"] == "audio" and chunk.get("data"):
                    yield base64.b64encode(chunk["data"]).decode("utf-8")
            return
        except Exception as e:
            logger.warning(f"Edge TTS streaming failed: {e}")

        # Fallback: generate a full audio blob and yield once
        audio_b64 = await self.generate_speech(text, voice_id)
        if audio_b64:
            yield audio_b64
        return

    async def _edge_tts(self, text: str) -> bytes:
        """Generate speech using Microsoft Edge TTS (no API key required)."""
        import edge_tts

        chunks = []
        communicate = edge_tts.Communicate(text, self.edge_tts_voice)
        async for chunk in communicate.stream():
            if chunk["type"] == "audio" and chunk.get("data"):
                chunks.append(chunk["data"])
        return b"".join(chunks)

    async def _system_tts(self, text: str) -> str:
        """Fallback to local TTS engines on Linux or macOS"""
        tts_engine = self._find_tts_engine()
        if not tts_engine:
            logger.error("No local TTS engine available")
            return ""

        suffix = ".wav" if tts_engine != "piper" else ".wav"
        tmp = tempfile.NamedTemporaryFile(suffix=suffix, prefix="jarvis_tts_", delete=False)
        audio_path = tmp.name
        tmp.close()
        try:
            if tts_engine in ["espeak-ng", "espeak"]:
                subprocess.run(
                    [tts_engine, "-w", audio_path, text],
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                )
            elif tts_engine == "piper":
                subprocess.run(
                    ["piper", "--tts", "--voice", "alloy", "--output", audio_path, "--text", text],
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                )
            else:
                raise FileNotFoundError("Unsupported TTS engine")

            with open(audio_path, "rb") as f:
                audio_data = f.read()

            return self._to_base64(audio_data)

        except subprocess.CalledProcessError as e:
            logger.error(f"Local TTS engine failed: {e.stderr}")
            return ""
        except FileNotFoundError:
            if sys.platform == "darwin":
                return await self._macos_say(text)
            logger.error("Local TTS binary not found")
            return ""
        finally:
            try:
                os.unlink(audio_path)
            except OSError:
                pass

    async def _macos_say(self, text: str) -> str:
        """Fallback to macOS say command"""
        tmp = tempfile.NamedTemporaryFile(suffix=".aiff", prefix="jarvis_tts_", delete=False)
        audio_path = tmp.name
        tmp.close()
        try:
            subprocess.run(
                ["say", "-o", audio_path, text],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )

            with open(audio_path, "rb") as f:
                audio_data = f.read()

            return self._to_base64(audio_data)
        except Exception as e:
            logger.error(f"macOS say failed: {e}")
            return ""
        finally:
            try:
                os.unlink(audio_path)
            except OSError:
                pass

    def _find_tts_engine(self) -> Optional[str]:
        """Detect an available local TTS engine"""
        for engine in ["espeak-ng", "espeak", "piper"]:
            if shutil.which(engine):
                return engine
        return None

    def _to_base64(self, audio_data: bytes) -> str:
        """Convert audio bytes to base64 string"""
        return base64.b64encode(audio_data).decode("utf-8")

    @staticmethod
    def get_supported_voices() -> list:
        """Return list of supported ElevenLabs voices"""
        return [
            {"id": "9BBfe6637e99185c8b146cb8f3523044", "name": "British Male"},
            {"id": "EXAVITQu4vr4xnSDxMaL", "name": "Bella"},
            {"id": "XB0fDUnXU5powFXDhCwa", "name": "Alice"},
            {"id": "21m00Tcm4TlvDq8ikWAM", "name": "Ryan"},
        ]
