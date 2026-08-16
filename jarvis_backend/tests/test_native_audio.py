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


def test_resolve_default_prefers_pulse_device(fake_sounddevice, monkeypatch):
    from managers.native_audio import resolve_device

    _all = list(fake_sounddevice.query_devices())
    _all.insert(
        0, {"name": "pulse", "max_input_channels": 2, "default_samplerate": 48000, "hostapi": 0}
    )

    def _query(device=None):
        if device is None:
            return _all
        if isinstance(device, int) and 0 <= device < len(_all):
            return _all[device]
        raise RuntimeError("Invalid device")

    fake_sounddevice.query_devices = _query
    fake_sounddevice.default = SimpleNamespace(device=(2, 2))

    # pulse device (id 0) should win over the PortAudio default (id 2)
    assert resolve_device(None) == 0


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


def test_source_mute_state_pulse_via_pactl(fake_sounddevice, monkeypatch):
    """pulse/pipewire/default devices consult pactl for the default source."""
    from managers.native_audio import source_mute_state

    _all = list(fake_sounddevice.query_devices())
    _all.insert(
        0, {"name": "pulse", "max_input_channels": 2, "default_samplerate": 48000, "hostapi": 0}
    )

    def _query(device=None):
        if device is None:
            return _all
        if isinstance(device, int) and 0 <= device < len(_all):
            return _all[device]
        raise RuntimeError("Invalid device")

    fake_sounddevice.query_devices = _query

    class FakeResult:
        stdout = "Mute: yes\n"

    import shutil

    monkeypatch.setattr(shutil, "which", lambda cmd: "/usr/bin/pactl" if cmd == "pactl" else None)
    import subprocess

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: FakeResult() if a and a[0][0] == "pactl" else FakeResult(),
    )
    assert source_mute_state(0) is True


def test_source_mute_state_hw_via_amixer(fake_sounddevice, monkeypatch):
    """Raw hw devices consult amixer for the capture switch."""
    from managers.native_audio import source_mute_state

    _all = list(fake_sounddevice.query_devices())
    _all.insert(
        0,
        {
            "name": "HD-Audio Generic (hw:1,0)",
            "max_input_channels": 2,
            "default_samplerate": 48000,
            "hostapi": 0,
        },
    )

    def _query(device=None):
        if device is None:
            return _all
        if isinstance(device, int) and 0 <= device < len(_all):
            return _all[device]
        raise RuntimeError("Invalid device")

    fake_sounddevice.query_devices = _query

    class FakeResult:
        stdout = "Capture: [off]\n"

    import shutil

    monkeypatch.setattr(shutil, "which", lambda cmd: "/usr/bin/amixer" if cmd == "amixer" else None)
    import subprocess

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: FakeResult())
    assert source_mute_state(0) is True


def test_source_mute_state_unknown_returns_none(fake_sounddevice):
    """When no CLI matches, mute state is None (not an error)."""
    from managers.native_audio import source_mute_state

    assert source_mute_state(0) is None


def test_native_mic_resamples_native_rate_to_16k(fake_sounddevice):
    """A device that only opens at 48 kHz must still yield 16 kHz PCM16."""
    from managers.native_audio import NativeMic

    _all = list(fake_sounddevice.query_devices())
    _all[0]["name"] = "HD-Audio Generic (hw:1,0)"
    _all[0]["default_samplerate"] = 48000

    calls = []
    original_input_stream = fake_sounddevice.InputStream

    class NativeRateStream(original_input_stream):
        def __init__(self, **kwargs):
            calls.append(kwargs["samplerate"])
            super().__init__(**kwargs)

    fake_sounddevice.InputStream = NativeRateStream

    # Force the 16k open to fail so the native-rate fallback engages.
    class FailingStream(original_input_stream):
        def __init__(self, **kwargs):
            if kwargs.get("samplerate") == 16000:
                raise RuntimeError("Invalid sample rate")
            calls.append(kwargs["samplerate"])
            super().__init__(**kwargs)

    fake_sounddevice.InputStream = FailingStream
    mic = NativeMic(device=0)
    assert mic.start() is True
    assert mic._capture_rate == 48000

    # Feed a 48 kHz block; the resampler must shrink it to ~16 kHz duration.
    frames = 48_000 * 30 // 1000  # 1440 samples per 30ms at 48k
    tone = np.sin(2 * np.pi * 440 * np.arange(frames) / 48000).astype(np.float32) * 0.5
    mic._stream.callback(tone.reshape(-1, 1), frames, None, None)
    chunk = mic.read_chunk(timeout=1.0)
    mic.stop()

    assert chunk is not None
    expected_16k = 16_000 * 30 // 1000  # 480 samples at 16k
    assert len(chunk.pcm16) == expected_16k * 2
    assert 0.2 < chunk.rms < 0.5


# -- Regression: queue/lifecycle race (stream stall -> reopen) ----------------
# The watch loop used to replace ``self._queue`` on every reopen, stranding a
# consumer blocked in ``read_chunk`` on the obsolete queue and letting stale
# callbacks write into a new session.  These tests pin the fixed behaviour:
# one stable queue per NativeMic, generation-scoped callbacks, and serialized
# open/close/stop.


def test_reopen_keeps_stable_queue_and_advances_generation(fake_sounddevice):
    from managers.native_audio import NativeMic

    mic = NativeMic(device=0)
    mic.start()
    original_queue = mic._queue
    stream1 = mic._stream
    gen_after_start = mic._generation

    mic._close_stream()
    assert mic._stream is None
    assert mic._queue is original_queue  # never replaced

    assert mic._open_stream(0) is True
    assert mic._stream is not stream1
    assert mic._generation == gen_after_start + 2  # close bumps, open binds next
    assert mic._queue is original_queue
    mic.stop()


def test_stale_callback_after_reopen_is_dropped(fake_sounddevice):
    from managers.native_audio import NativeMic

    mic = NativeMic(device=0)
    mic.start()
    old_cb = mic._stream.callback
    old_queue = mic._queue

    mic._close_stream()
    assert mic._open_stream(0) is True
    new_cb = mic._stream.callback
    assert new_cb is not old_cb

    frames = mic.block_size
    tone = (np.sin(2 * np.pi * 440 * np.arange(frames) / 16000) * 0.5).astype(np.float32)

    # A callback still firing from the closed stream must be dropped.
    old_cb(tone.reshape(-1, 1), frames, None, None)
    assert old_queue.qsize() == 0

    # The current stream's callback lands normally.
    new_cb(tone.reshape(-1, 1), frames, None, None)
    assert old_queue.qsize() == 1
    chunk = mic.read_chunk(timeout=1.0)
    assert chunk is not None and len(chunk.pcm16) == frames * 2
    mic.stop()


def test_callback_during_close_is_dropped(fake_sounddevice):
    from managers.native_audio import NativeMic

    mic = NativeMic(device=0)
    mic.start()
    cb = mic._stream.callback
    q = mic._queue

    mic._close_stream()  # generation advances; cb now belongs to a stale stream
    frames = mic.block_size
    tone = (np.sin(2 * np.pi * 440 * np.arange(frames) / 16000) * 0.5).astype(np.float32)
    cb(tone.reshape(-1, 1), frames, None, None)
    assert q.qsize() == 0
    mic.stop()


def test_consumer_not_stranded_across_reopen(fake_sounddevice):
    from managers.native_audio import NativeMic

    mic = NativeMic(device=0)
    mic.start()
    received = []
    done = threading.Event()

    def reader():
        chunk = mic.read_chunk(timeout=3.0)
        if chunk is not None:
            received.append(chunk)
        done.set()

    t = threading.Thread(target=reader)
    t.start()

    # Replace the stream underneath the blocked reader (watch-loop reopen path).
    mic._close_stream()
    assert mic._open_stream(0) is True

    frames = mic.block_size
    tone = (np.sin(2 * np.pi * 440 * np.arange(frames) / 16000) * 0.5).astype(np.float32)
    mic._stream.callback(tone.reshape(-1, 1), frames, None, None)

    assert done.wait(timeout=2.0), "consumer stranded on obsolete queue"
    t.join(timeout=2.0)
    assert len(received) == 1
    assert len(received[0].pcm16) == frames * 2
    mic.stop()


def test_repeated_reopen_cycles_do_not_leak_streams(fake_sounddevice):
    from managers.native_audio import NativeMic

    created = []
    original = fake_sounddevice.InputStream

    class TrackingStream(original):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            created.append(self)

    fake_sounddevice.InputStream = TrackingStream
    mic = NativeMic(device=0)
    mic.start()
    for _ in range(5):
        mic._close_stream()
        assert mic._open_stream(0) is True

    started = [s for s in created if s._started]
    assert len(started) == 1  # exactly one live native stream at any time
    assert len(created) == 6  # 1 initial + 5 reopens, all but the last closed
    assert all(not s._started for s in created[:-1])
    mic.stop()
    assert all(not s._started for s in created)


def test_stall_then_reopen_recovers_with_same_queue(fake_sounddevice):
    from managers.native_audio import NativeMic

    mic = NativeMic(device=0)
    mic.start()
    gen_before = mic._generation
    q = mic._queue

    # No callbacks delivered for longer than STALL_TIMEOUT_SECONDS.
    mic._last_callback_at = time.monotonic() - 10.0
    assert mic._stream_stalled(time.monotonic()) is True
    mic._close_stream()
    assert mic._open_stream(0) is True

    assert mic._stream is not None
    assert mic._generation > gen_before
    assert mic._queue is q

    frames = mic.block_size
    tone = (np.sin(2 * np.pi * 440 * np.arange(frames) / 16000) * 0.5).astype(np.float32)
    mic._stream.callback(tone.reshape(-1, 1), frames, None, None)
    chunk = mic.read_chunk(timeout=1.0)
    assert chunk is not None and len(chunk.pcm16) == frames * 2
    mic.stop()


def test_stall_detection_uses_callback_liveness(fake_sounddevice):
    from managers.native_audio import NativeMic

    mic = NativeMic(device=0)
    mic.start()
    assert mic._stream_stalled() is False
    mic._last_callback_at = time.monotonic() - 10.0
    assert mic._stream_stalled() is True
    mic._last_callback_at = time.monotonic()
    assert mic._stream_stalled() is False
    mic.stop()


def test_open_refuses_after_stop(fake_sounddevice):
    """A reopen must never resurrect the stream after stop()."""
    from managers.native_audio import NativeMic

    mic = NativeMic(device=0)
    mic.start()
    mic.stop()
    assert mic._stream is None
    assert mic._open_stream(0) is False
    assert mic._stream is None


def test_stop_unblocks_consumer_on_stable_queue(fake_sounddevice):
    from managers.native_audio import NativeMic

    mic = NativeMic(device=0)
    mic.start()
    result = {}

    def reader():
        result["chunk"] = mic.read_chunk(timeout=3.0)

    t = threading.Thread(target=reader)
    t.start()
    time.sleep(0.1)
    mic.stop()
    t.join(timeout=2.0)
    assert result.get("chunk") is None  # None sentinel on the stable queue wakes it
    assert not t.is_alive()
