"""Voice Manager — orchestrates the end-to-end voice pipeline.

Wires AudioManager → STTManager → LLMProvider → TTSManager with
state tracking, error recovery, and streaming support.
"""

import asyncio
import json
import logging
from collections.abc import AsyncGenerator, Callable

from managers.audio_manager import AudioManager
from managers.stt_manager import STTManager
from managers.tts_manager import TTSManager
from modules.llm_provider import LLMProvider

logger = logging.getLogger(__name__)


class VoiceManager:
    """End-to-end voice pipeline orchestrator."""

    def __init__(
        self,
        audio_manager: AudioManager,
        stt_manager: STTManager,
        tts_manager: TTSManager,
        llm_provider: LLMProvider,
    ):
        self.audio = audio_manager
        self.stt = stt_manager
        self.tts = tts_manager
        self.llm = llm_provider

        self._listening = False
        self._processing = False
        self._speaking = False
        self._interrupt_event = asyncio.Event()
        self._lock = asyncio.Lock()

    async def start_listening(self) -> bool:
        if not self.audio.start():
            return False
        self._listening = True
        self._interrupt_event.clear()
        return True

    async def stop_listening(self) -> bytes:
        self._listening = False
        chunks = self.audio.read_all()
        self.audio.stop()
        return b"".join(chunks)

    async def cancel_listening(self) -> None:
        self._listening = False
        self.audio.stop()

    async def process_audio(
        self,
        pcm: bytes,
        sample_rate: int,
        conversation_history: list[dict],
        on_partial: Callable[[str], None] | None = None,
    ) -> AsyncGenerator[str, None]:
        """Full pipeline: STT → LLM → TTS stream."""
        async with self._lock:
            self._processing = True
            self._interrupt_event.clear()

        try:
            user_text = await asyncio.to_thread(self.stt.transcribe_pcm16, pcm, sample_rate)
            if not user_text:
                yield json.dumps({"type": "error", "message": "I couldn't hear anything."})
                return

            yield json.dumps({"type": "transcript", "text": user_text})

            response_text = ""
            async for chunk in self.llm.get_response_stream(
                user_text,
                conversation_history,
            ):
                if self._interrupt_event.is_set():
                    break
                response_text += chunk
                yield json.dumps({"type": "partial", "text": response_text})

            if not response_text:
                response_text = "I'm sorry, I couldn't generate a response."

            yield json.dumps({"type": "response", "text": response_text})

            async for audio_chunk in self.tts.stream_speech(response_text):
                if self._interrupt_event.is_set():
                    break
                yield json.dumps({"type": "audio_chunk", "chunk": audio_chunk})

            yield json.dumps({"type": "audio_end"})

        except Exception as e:
            logger.error("Voice pipeline failed: %s", e)
            yield json.dumps({"type": "error", "message": str(e)})
        finally:
            async with self._lock:
                self._processing = False

    async def interrupt(self) -> None:
        self._interrupt_event.set()
        await self.cancel_listening()
        async with self._lock:
            self._processing = False

    @property
    def is_listening(self) -> bool:
        return self._listening

    @property
    def is_processing(self) -> bool:
        return self._processing

    @property
    def is_speaking(self) -> bool:
        return self._speaking

    def diagnostics(self) -> dict:
        return {
            "listening": self._listening,
            "processing": self._processing,
            "speaking": self._speaking,
            "audio": self.audio.diagnostics(),
            "stt": self.stt.diagnostics(),
            "tts": self.tts.diagnostics(),
        }
