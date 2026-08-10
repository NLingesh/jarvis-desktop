"""Tests for the native voice WebSocket + device REST endpoints.

Sounddevice and Silero are mocked so tests run headless; the STT manager is
stubbed so no real transcription happens.
"""

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
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}


def test_native_ws_connect_returns_devices_and_ready(client):
    with client.websocket_connect("/ws/voice/native?token=test-secret-token") as ws:
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
        ws.send_json({"type": "get_devices"})
        msg = ws.receive_json()
        assert msg["type"] == "devices"
        assert len(msg["devices"]) == 2


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
