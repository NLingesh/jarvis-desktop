"""Unit tests for NativeVoiceSession orchestration (managers/native_voice.py)."""

import time
from types import SimpleNamespace

import numpy as np
import pytest


@pytest.fixture(autouse=True)
def fake_audio(monkeypatch):
    """Provide fake sounddevice + fake Silero so the session runs headless."""

    class FakeStream:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.callback = kwargs["callback"]
            self._started = False

        def start(self):
            self._started = True

        def stop(self):
            self._started = False

        def close(self):
            self._started = False

    _all = [
        {
            "name": "Built-in Analog",
            "max_input_channels": 2,
            "default_samplerate": 48000,
            "hostapi": 0,
        },
        {"name": "USB Headset", "max_input_channels": 1, "default_samplerate": 44100, "hostapi": 0},
    ]

    def _query(device=None):
        if device is None:
            return _all
        if isinstance(device, int) and 0 <= device < len(_all):
            return _all[device]
        raise RuntimeError("Invalid device")

    fake_sd = type("fake_sd", (), {})
    fake_sd.InputStream = FakeStream
    fake_sd.query_devices = _query
    fake_sd.query_hostapis = lambda: [{"name": "ALSA"}]
    fake_sd.default = SimpleNamespace(device=(0, 0))
    fake_sd.PortAudioError = RuntimeError

    import managers.native_audio as na
    import managers.native_voice as nv

    monkeypatch.setattr(na, "sd", fake_sd)
    monkeypatch.setattr(na, "SOUNDDEVICE_AVAILABLE", True)
    monkeypatch.setattr(nv, "list_input_devices", na.list_input_devices)
    monkeypatch.setattr(nv, "resolve_device", na.resolve_device)

    # Stub Silero so VAD runs deterministically.
    import managers.vad as vad_mod

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

        def reset_states(self):
            self.current = 0
            self.speech = False
            self.silence_count = 0

        def __call__(self, frame):
            self.current += frame.shape[1]
            if hasattr(frame, "detach"):
                frame = frame.detach().cpu().numpy()
            energy = float(np.mean(frame**2))
            speaking = energy > 0.01
            if speaking and not self.speech:
                self.speech = True
                self.silence_count = 0
                return {"start": self.current / self.sr}
            if not speaking and self.speech:
                self.silence_count += frame.shape[1]
                if self.silence_count >= self.min_silence_samples:
                    self.speech = False
                    return {"end": self.current / self.sr}
            return None

    fake_torch = type("fake_torch", (), {"from_numpy": lambda a: a, "no_grad": lambda fn: fn})
    fake_vad_mod = type("fake_vad_mod", (), {})
    fake_vad_mod.VADIterator = FakeVADIterator
    fake_vad_mod.load_silero_vad = lambda: type("M", (), {"eval": lambda self: self})()
    monkeypatch.setattr(vad_mod, "SILERO_AVAILABLE", True)
    monkeypatch.setattr(vad_mod, "torch", fake_torch)
    monkeypatch.setattr(vad_mod, "VADIterator", fake_vad_mod.VADIterator)
    monkeypatch.setattr(vad_mod, "load_silero_vad", fake_vad_mod.load_silero_vad)
    yield


def _push_audio(session, seconds, loud=True):
    """Push simulated audio through the consumer loop."""
    n = int(16000 * seconds)
    data = np.random.randn(n).astype(np.float32) * (0.3 if loud else 0.001)
    pcm = (data * 32767).astype(np.int16).tobytes()
    for i in range(0, len(pcm), 480):
        chunk = pcm[i : i + 480]
        if len(chunk) < 480:
            break
        session.mic._queue.put_nowait(
            SimpleNamespace(pcm16=chunk, timestamp=0, rms=0.5 if loud else 0.001, peak=0.6)
        )


def test_connect_reaches_ready(fake_audio):
    from managers.native_voice import STATE_READY, NativeVoiceSession

    states = []
    s = NativeVoiceSession(on_state=lambda st, d: states.append(st))
    assert s.connect() is True
    assert s.state == STATE_READY
    assert states == ["CONNECTING", "READY"]
    s.disconnect()


def test_ptt_records_and_returns_pcm(fake_audio):
    from managers.native_voice import NativeVoiceSession

    s = NativeVoiceSession()
    s.connect()
    assert s.start_listening("ptt") is True
    _push_audio(s, 0.5, loud=True)
    # Let the consumer thread drain the queue into the utterance buffer.
    for _ in range(100):
        if s.mic._queue.empty():
            break
        time.sleep(0.02)
    pcm = s.stop_listening()
    s.disconnect()
    assert len(pcm) > 0
    assert s.state == "IDLE"


def test_ptt_stop_empty_when_not_recording(fake_audio):
    from managers.native_voice import NativeVoiceSession

    s = NativeVoiceSession()
    s.connect()
    assert s.stop_listening() == b""
    s.disconnect()


def test_hands_free_auto_ends_utterance(fake_audio):
    from managers.native_voice import NativeVoiceSession

    utterances = []
    s = NativeVoiceSession(on_utterance=lambda pcm: utterances.append(pcm))
    s.connect()
    s.vad.start()
    assert s.start_listening("hands_free") is True
    # Speech then silence -> VAD fires speech_end -> utterance emitted.
    _push_audio(s, 1.0, loud=True)
    _push_audio(s, 1.0, loud=False)
    time.sleep(0.2)
    s.disconnect()
    assert len(utterances) == 1
    assert len(utterances[0]) > 0


def test_cancel_discards_recording(fake_audio):
    from managers.native_voice import NativeVoiceSession

    s = NativeVoiceSession()
    s.connect()
    s.start_listening("ptt")
    _push_audio(s, 0.5, loud=True)
    s.cancel()
    assert s.state == "IDLE"
    assert s.stop_listening() == b""
    s.disconnect()


def test_invalid_mode_errors(fake_audio):
    from managers.native_voice import STATE_ERROR, NativeVoiceSession

    s = NativeVoiceSession()
    s.connect()
    ok = s.start_listening("bogus")
    assert ok is False
    assert s.state == STATE_ERROR
    s.disconnect()


def test_set_device_reports_list(fake_audio):
    from managers.native_voice import NativeVoiceSession

    s = NativeVoiceSession()
    result = s.set_device(1)
    assert result["active"] == 1
    assert len(result["devices"]) == 2
    s.disconnect()


def test_diagnostics_shape(fake_audio):
    from managers.native_voice import NativeVoiceSession

    s = NativeVoiceSession()
    s.connect()
    d = s.diagnostics()
    assert d["state"] == "READY"
    assert "mic" in d and "vad" in d and "mode" in d
    s.disconnect()


# -- Regression: consumer-thread lifecycle -----------------------------------
# ``mic_test`` used to spawn a consumer thread without the alive-check that
# ``connect`` had, so a session reused across a mic test + connect (or a
# reconnect after the stream was reopened) could end up with two consumers
# draining the same queue.  These tests pin the guarded ``_start_consumer``.


def test_no_duplicate_consumer_thread_on_reconnect(fake_audio):
    from managers.native_voice import NativeVoiceSession

    s = NativeVoiceSession()
    s.connect()
    first = s._consumer_thread
    assert first is not None and first.is_alive()

    # A guarded re-start while the consumer is alive must not spawn a second.
    s._start_consumer()
    assert s._consumer_thread is first

    s.disconnect()
    assert not first.is_alive()
    s.connect()
    second = s._consumer_thread
    assert second is not None and second.is_alive()
    assert second is not first
    s.disconnect()
    assert not second.is_alive()


def test_mic_test_and_connect_share_single_consumer(fake_audio):
    from managers.native_voice import NativeVoiceSession

    s = NativeVoiceSession()
    assert s.mic_test() is True
    consumer = s._consumer_thread
    assert consumer is not None and consumer.is_alive()

    # connect() on an already-running session must reuse the existing consumer.
    assert s.connect() is True
    assert s._consumer_thread is consumer
    s.disconnect()
    assert not consumer.is_alive()


def test_disconnect_stops_consumer_thread(fake_audio):
    from managers.native_voice import NativeVoiceSession

    s = NativeVoiceSession()
    s.connect()
    t = s._consumer_thread
    assert t is not None and t.is_alive()
    s.disconnect()
    t.join(timeout=2.0)
    assert not t.is_alive()
