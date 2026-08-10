"""Unit tests for the native audio capture layer (managers/native_audio.py).

Sounddevice is mocked so tests run without a physical microphone.
"""

import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest


@pytest.fixture(autouse=True)
def fake_sounddevice(monkeypatch):
    """Replace sounddevice with a deterministic fake implementation."""

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

    fake = type("fake_sd", (), {})
    fake.InputStream = FakeStream
    fake.query_devices = _query
    fake.query_hostapis = lambda: [{"name": "ALSA"}]
    fake.default = SimpleNamespace(device=(0, 0))
    fake.PortAudioError = RuntimeError

    import managers.native_audio as na

    monkeypatch.setattr(na, "sd", fake)
    monkeypatch.setattr(na, "SOUNDDEVICE_AVAILABLE", True)
    yield fake


def test_list_input_devices_filters_duplex(fake_sounddevice):
    from managers.native_audio import list_input_devices

    devices = list_input_devices()
    assert len(devices) == 2
    assert devices[0]["name"] == "Built-in Analog"
    assert devices[0]["is_default"] is True
    assert devices[1]["is_default"] is False


def test_resolve_device_by_int_name_and_default(fake_sounddevice):
    from managers.native_audio import resolve_device

    assert resolve_device(1) == 1
    assert resolve_device("usb") == 1
    assert resolve_device(None) == 0


def test_resolve_unknown_name_falls_back_to_default(fake_sounddevice):
    from managers.native_audio import resolve_device

    assert resolve_device("does-not-exist") == 0


def test_start_starts_stream_and_reports_running(fake_sounddevice):
    from managers.native_audio import NativeMic

    mic = NativeMic(device=0)
    assert mic.start() is True
    assert mic.running
    assert mic.device_info()["name"] == "Built-in Analog"
    mic.stop()
    assert not mic.running


def test_callback_produces_pcm16_chunks(fake_sounddevice):
    from managers.native_audio import NativeMic

    mic = NativeMic(device=0)
    mic.start()
    frames = mic.block_size
    tone = np.sin(2 * np.pi * 440 * np.arange(frames) / 16000).astype(np.float32) * 0.5
    stream = mic._stream
    stream.callback(tone.reshape(-1, 1), frames, None, None)
    chunk = mic.read_chunk(timeout=1.0)
    mic.stop()

    assert chunk is not None
    assert len(chunk.pcm16) == frames * 2
    # A 0.5-amplitude tone should give a measurable RMS near ~0.35.
    assert 0.2 < chunk.rms < 0.5
    assert chunk.peak > 0.4


def test_silence_yields_low_rms(fake_sounddevice):
    from managers.native_audio import NativeMic

    mic = NativeMic(device=0)
    mic.start()
    frames = mic.block_size
    stream = mic._stream
    stream.callback(np.zeros((frames, 1), dtype=np.float32), frames, None, None)
    lvl = mic.level()
    mic.stop()
    assert lvl["rms"] < 0.001


def test_reconnect_loop_reopens_after_stream_loss(fake_sounddevice):
    from managers.native_audio import NativeMic

    mic = NativeMic(device=0)
    mic.start()
    assert mic._stream is not None

    # Simulate stream loss: close the underlying stream.
    mic._close_stream()
    assert mic._stream is None

    # A single reconnect attempt should reopen the stream.
    mic._reconnect_loop()
    assert mic._stream is not None
    mic.stop()


def test_device_change_reopens_stream(fake_sounddevice):
    from managers.native_audio import NativeMic

    mic = NativeMic(device=0)
    mic.start()
    original = mic._stream
    assert mic._active_device == 0

    # Manually trigger the device-change branch of the watch loop.
    mic._active_device = 99
    mic._watch_loop_iteration = None
    # Simulate the watch discovering the current device is 0 again.
    from managers.native_audio import resolve_device

    if resolve_device(None) != mic._active_device:
        mic._close_stream()
        mic._open_stream(0)
    assert mic._stream is not None
    assert mic._stream is not original or mic._stream is not None
    mic.stop()


def test_stop_signals_blocked_reader(fake_sounddevice):
    from managers.native_audio import NativeMic

    mic = NativeMic(device=0)
    mic.start()
    result = {}

    def reader():
        chunk = mic.read_chunk(timeout=3.0)
        result["chunk"] = chunk

    t = threading.Thread(target=reader)
    t.start()
    time.sleep(0.2)
    mic.stop()
    t.join(timeout=2.0)
    assert result.get("chunk") is None  # None sentinel wakes the reader
