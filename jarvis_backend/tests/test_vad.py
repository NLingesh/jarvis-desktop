"""Unit tests for Silero voice-activity detection (managers/vad.py).

The Silero model itself is not needed in CI: a deterministic fake model
produces speech events from frame energy so endpointing logic is verified.
"""

import time

import numpy as np
import pytest


@pytest.fixture(autouse=True)
def fake_silero(monkeypatch):
    """Stub torch/silero_vad with a fake VADIterator driven by frame energy."""

    class FakeVADIterator:
        def __init__(
            self,
            model,
            threshold=0.5,
            sampling_rate=16000,
            min_silence_duration_ms=100,
            speech_pad_ms=30,
        ):
            self.threshold = threshold
            self.sr = sampling_rate
            self.min_silence_samples = int(sampling_rate * min_silence_duration_ms / 1000)
            self.current = 0
            self.speech = False
            self.silence_count = 0
            self.last_start = 0

        def reset_states(self):
            self.current = 0
            self.speech = False
            self.silence_count = 0

        def __call__(self, frame):
            self.current += frame.shape[1]
            if hasattr(frame, "detach"):
                frame = frame.detach().cpu().numpy()
            energy = float(np.mean(frame**2))
            speaking = energy > 0.01  # loud frame counts as speech
            if speaking and not self.speech:
                self.speech = True
                self.silence_count = 0
                self.last_start = self.current
                return {"start": self.current / self.sr}
            if not speaking and self.speech:
                self.silence_count += frame.shape[1]
                if self.silence_count >= self.min_silence_samples:
                    self.speech = False
                    return {"end": self.current / self.sr}
            return None

    fake_torch = type("fake_torch", (), {"from_numpy": torch_from_numpy, "no_grad": lambda fn: fn})
    fake_vad = type("fake_vad", (), {})
    fake_vad.VADIterator = FakeVADIterator
    fake_vad.load_silero_vad = lambda: type("M", (), {"eval": lambda self: self})()

    import managers.vad as vad_mod

    monkeypatch.setattr(vad_mod, "SILERO_AVAILABLE", True)
    monkeypatch.setattr(vad_mod, "torch", fake_torch)
    monkeypatch.setattr(vad_mod, "VADIterator", fake_vad.VADIterator)
    monkeypatch.setattr(vad_mod, "load_silero_vad", fake_vad.load_silero_vad)
    yield


def torch_from_numpy(arr):
    return arr


def test_vad_reports_speech_start_and_end(fake_silero):
    from managers.vad import VoiceActivityDetector

    events = []
    vad = VoiceActivityDetector(
        on_speech_start=lambda: events.append("start"),
        on_speech_end=lambda: events.append("end"),
    )
    assert vad.start() is True

    # Feed ~2s of loud audio, then ~0.8s of silence.
    loud = np.random.randn(1600).astype(np.float32) * 0.3
    silent = np.zeros(1600, dtype=np.float32)
    loud_pcm = (loud * 32767).astype(np.int16).tobytes()
    silent_pcm = (silent * 32767).astype(np.int16).tobytes()

    for _ in range(2):
        vad.feed(loud_pcm)
    assert vad.speaking
    for _ in range(12):
        vad.feed(silent_pcm)
    assert not vad.speaking
    assert events.count("start") >= 1
    assert events.count("end") >= 1


def test_vad_ignores_quiet_audio(fake_silero):
    from managers.vad import VoiceActivityDetector

    events = []
    vad = VoiceActivityDetector(
        on_speech_start=lambda: events.append("start"),
        on_speech_end=lambda: events.append("end"),
    )
    vad.start()
    quiet = (np.zeros(1600, dtype=np.float32)).astype(np.int16).tobytes()
    for _ in range(10):
        vad.feed(quiet)
    assert not vad.speaking
    assert events == []


def test_vad_buffers_partial_frames(fake_silero):
    from managers.vad import VoiceActivityDetector

    vad = VoiceActivityDetector()
    vad.start()
    # Feed a chunk smaller than the 512-sample Silero window; must not crash.
    tiny = (np.zeros(100, dtype=np.float32)).astype(np.int16).tobytes()
    vad.feed(tiny)
    assert vad.diagnostics()["buffered_samples"] == 100


def test_vad_max_utterance_cap(fake_silero):
    from managers.vad import VoiceActivityDetector

    events = []
    vad = VoiceActivityDetector(
        max_utterance_ms=100,
        on_speech_end=lambda: events.append("end"),
    )
    vad.start()
    loud = np.random.randn(1600).astype(np.float32) * 0.3
    loud_pcm = (loud * 32767).astype(np.int16).tobytes()
    for _ in range(6):
        vad.feed(loud_pcm)
        time.sleep(0.02)
    assert events.count("end") >= 1
    assert not vad.speaking


def test_vad_reset_clears_utterance(fake_silero):
    from managers.vad import VoiceActivityDetector

    vad = VoiceActivityDetector()
    vad.start()
    loud = np.random.randn(1600).astype(np.float32) * 0.3
    vad.feed((loud * 32767).astype(np.int16).tobytes())
    assert vad.speaking
    vad.reset()
    assert not vad.speaking
    assert vad.diagnostics()["buffered_samples"] == 0
