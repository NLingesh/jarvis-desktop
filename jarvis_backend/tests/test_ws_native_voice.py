"""Tests for the native voice WebSocket + device REST endpoints.

Sounddevice and Silero are mocked so tests run headless; the STT manager is
stubbed so no real transcription happens.
"""

import asyncio
import importlib
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    """TestClient with known token and headless native audio stack."""
    import routes.state as state_mod

    monkeypatch.setattr(state_mod, "SESSION_TOKEN", "test-secret-token")
    monkeypatch.setattr(state_mod, "SESSION_TOKEN_PATH", "/tmp/test_session_token")

    import main as main_mod

    importlib.reload(main_mod)

    # --- fake sounddevice ---------------------------------------------------
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

    # --- fake Silero ---------------------------------------------------------
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
    monkeypatch.setattr(vad_mod, "SILERO_AVAILABLE", True)
    monkeypatch.setattr(vad_mod, "torch", fake_torch)
    monkeypatch.setattr(vad_mod, "VADIterator", FakeVADIterator)
    monkeypatch.setattr(
        vad_mod, "load_silero_vad", lambda: type("M", (), {"eval": lambda self: self})()
    )

    # --- stub STT so no real transcription is attempted -----------------------
    monkeypatch.setattr(
        state_mod, "stt_manager", SimpleNamespace(transcribe_pcm16=lambda pcm, sr: "")
    )
    monkeypatch.setattr(main_mod, "stt_manager", state_mod.stt_manager)
    monkeypatch.setattr(
        main_mod,
        "handle_user_input",
        lambda user_input, session_id, websocket, voice_uid: None,
    )

    return TestClient(main_mod.app)


def test_get_devices_endpoint(client):
    resp = client.get("/api/voice/devices")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["devices"]) == 2
    assert body["default"] == 0


def test_native_ws_rejects_missing_token(client):
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect), client.websocket_connect("/ws/voice/native") as ws:
        ws.receive_json()


def test_native_ws_ping_pong(client):
    with client.websocket_connect("/ws/voice/native?token=test-secret-token") as ws:
        _drain_server(ws)
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}


def test_native_ws_connect_returns_devices_and_ready(client):
    with client.websocket_connect("/ws/voice/native?token=test-secret-token") as ws:
        _drain_server(ws)
        ws.send_json({"type": "connect"})
        first = ws.receive_json()
        assert first["type"] == "devices"
        assert len(first["devices"]) == 2
        states = []
        for _ in range(2):
            msg = ws.receive_json()
            assert msg["type"] == "state"
            states.append(msg["state"])
        assert states == ["CONNECTING", "READY"]


def test_native_ws_start_stop_listening_flow(client):
    with client.websocket_connect("/ws/voice/native?token=test-secret-token") as ws:
        _drain_server(ws)
        ws.send_json({"type": "connect"})
        ws.receive_json()  # devices
        ws.receive_json()  # CONNECTING
        ws.receive_json()  # READY

        ws.send_json({"type": "start_listening", "mode": "ptt"})
        msg = ws.receive_json()
        assert msg["type"] == "state"
        assert msg["state"] == "LISTENING"

        ws.send_json({"type": "stop_listening"})
        # stop emits IDLE state
        msg = ws.receive_json()
        assert msg["type"] == "state"
        assert msg["state"] == "IDLE"


def test_native_ws_get_devices_message(client):
    with client.websocket_connect("/ws/voice/native?token=test-secret-token") as ws:
        _drain_server(ws)
        ws.send_json({"type": "get_devices"})
        msg = ws.receive_json()
        assert msg["type"] == "devices"
        assert len(msg["devices"]) == 2


def _drain_server(ws):
    """The server sends a ``server`` build-welcome message on connect; consume it."""
    msg = ws.receive_json()
    assert msg.get("type") == "server"
    assert msg.get("build")


def _receive_until(ws, msg_type, timeout=5.0):
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        msg = ws.receive_json()
        if msg.get("type") == msg_type:
            return msg
    raise AssertionError(f"did not receive {msg_type!r}")


def test_native_ws_mic_test_lifecycle(client):
    with client.websocket_connect("/ws/voice/native?token=test-secret-token") as ws:
        ws.send_json({"type": "mic_test_start"})
        msg = _receive_until(ws, "mic_test")
        assert msg["status"] == "started"

        ws.send_json({"type": "mic_test_stop"})
        msg = _receive_until(ws, "mic_test")
        assert msg["status"] == "stopped"


# ---------------------------------------------------------------------------
# Preflight diagnostics: local mic failures must map to clear messages.
# ---------------------------------------------------------------------------
def test_pcm_level_empty():
    import main as main_mod

    assert main_mod._pcm_level(b"") == (0.0, 0.0)


def test_pcm_level_tone():
    import array

    import numpy as np

    import main as main_mod

    tone = (np.sin(2 * np.pi * 440 * np.arange(16000) / 16000) * 0.5 * 32767).astype(np.int16)
    pcm = array.array("h", tone).tobytes()
    rms, peak = main_mod._pcm_level(pcm)
    assert 0.3 < rms < 0.5
    assert peak > 0.4


def test_pcm_level_silence():
    import main as main_mod

    assert main_mod._pcm_level(b"\x00\x00" * 8000) == (0.0, 0.0)


def test_native_connect_message_mapping(client):
    import main as main_mod

    session = SimpleNamespace(mic=SimpleNamespace(device_info=lambda: {"id": 0}))
    assert (
        main_mod._native_connect_message("no input device available", session)
        == "No microphone detected."
    )
    assert (
        main_mod._native_connect_message("sounddevice not available", session)
        == "No microphone detected."
    )
    assert (
        main_mod._native_connect_message("Invalid sample rate for device", session)
        == "No microphone detected."
    )
    assert "Could not open" in main_mod._native_connect_message("some odd failure", session)


def test_native_transcribe_silence_reports_no_signal(client, monkeypatch):
    """Silent audio with STT returning '' must report 'No usable microphone
    signal detected.' instead of a generic error."""
    import main as main_mod

    sent = []

    class FakeWS:
        async def send_json(self, payload):
            sent.append(payload)

    class FakeMic:
        def device_info(self):
            return {"id": 0}

    session = SimpleNamespace(mic=FakeMic())
    result = asyncio.run(main_mod._native_transcribe(session, b"\x00\x00" * 16000, FakeWS(), "t"))
    assert result == ""
    assert sent and sent[0]["type"] == "error"
    assert sent[0]["error_scope"] == "stream"
    assert sent[0]["message"] == "No usable microphone signal detected."


def test_native_transcribe_speech_no_text_is_no_speech_status(client, monkeypatch):
    """Audible audio with STT returning '' must be a non-blocking no-speech
    voice_status, never a hard error card."""
    import array

    import numpy as np

    import main as main_mod

    sent = []

    class FakeWS:
        async def send_json(self, payload):
            sent.append(payload)

    class FakeMic:
        def device_info(self):
            return {"id": 0}

    tone = (np.sin(2 * np.pi * 440 * np.arange(16000) / 16000) * 0.5 * 32767).astype(np.int16)
    pcm = array.array("h", tone).tobytes()
    session = SimpleNamespace(mic=FakeMic())
    result = asyncio.run(
        main_mod._native_transcribe(session, pcm, FakeWS(), "t", voice_cycle_id="cyc123")
    )
    assert result == ""
    assert sent and sent[0]["type"] == "voice_status"
    assert sent[0]["status"] == "no_speech"
    assert sent[0]["voice_cycle_id"] == "cyc123"
    assert not any(p.get("type") == "error" for p in sent)


def test_native_transcribe_no_pcm_is_no_speech_status(client, monkeypatch):
    """Empty captured audio must be a subtle no-speech status, not an error."""
    import main as main_mod

    sent = []

    class FakeWS:
        async def send_json(self, payload):
            sent.append(payload)

    session = SimpleNamespace(mic=None)
    result = asyncio.run(main_mod._native_transcribe(session, b"", FakeWS(), "t", "cyc9"))
    assert result == ""
    assert sent and sent[0]["type"] == "voice_status"
    assert sent[0]["status"] == "no_speech"


def test_native_transcribe_muted_reports_muted(client, monkeypatch):
    """A muted source must report 'Microphone is muted.' even with audio."""
    import array

    import numpy as np

    import main as main_mod

    sent = []

    class FakeWS:
        async def send_json(self, payload):
            sent.append(payload)

    class FakeMic:
        def device_info(self):
            return {"id": 0}

    monkeypatch.setattr(main_mod, "_source_muted", lambda session: True)

    tone = (np.sin(2 * np.pi * 440 * np.arange(16000) / 16000) * 0.5 * 32767).astype(np.int16)
    pcm = array.array("h", tone).tobytes()
    session = SimpleNamespace(mic=FakeMic())
    result = asyncio.run(main_mod._native_transcribe(session, pcm, FakeWS(), "t"))
    assert result == ""
    assert sent and sent[0]["type"] == "error"
    assert sent[0]["error_scope"] == "stream"
    assert sent[0]["message"] == "Microphone is muted."
