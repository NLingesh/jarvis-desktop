"""Standalone CLI test for the native audio capture layer.

Usage:
    python -m scripts.test_native_audio list
    python -m scripts.test_native_audio capture [seconds] [device_index_or_name]
    python -m scripts.test_native_audio level [seconds]

Captures real microphone audio via sounddevice and reports device
enumeration, input level, and chunk delivery.  Run from jarvis_backend/.
"""

import sys
import time

from managers.native_audio import NativeMic, list_input_devices, resolve_device


def cmd_list():
    devices = list_input_devices()
    if not devices:
        print("NO INPUT DEVICES FOUND")
        sys.exit(1)
    print(f"Found {len(devices)} input devices:")
    for d in devices:
        default = "  (default)" if d["is_default"] else ""
        print(f"  [{d['id']}] {d['name']}  sr={d['default_samplerate']}{default}")
    resolved = resolve_device(None)
    print(f"Resolved default device: {resolved}")


def cmd_capture(duration, selector):
    device_id = resolve_device(selector)
    print(f"Capturing {duration}s from device {device_id} ({selector!r})")
    mic = NativeMic(device=device_id)
    ok = mic.start()
    if not ok:
        print(f"FAILED to start capture: {mic.diagnostics()}")
        sys.exit(1)
    print(f"Stream open: {mic.device_info()}")
    start = time.monotonic()
    total_bytes = 0
    chunks = 0
    max_rms = 0.0
    while time.monotonic() - start < duration:
        chunk = mic.read_chunk(timeout=0.5)
        if chunk is None:
            print(f"  ... no chunk within 0.5s (rms={mic.level()['rms']:.4f})")
            continue
        total_bytes += len(chunk.pcm16)
        chunks += 1
        max_rms = max(max_rms, chunk.rms)
        if chunks % 20 == 0:
            print(
                f"  chunks={chunks} bytes={total_bytes} rms={chunk.rms:.4f} peak={chunk.peak:.4f}"
            )
    mic.stop()
    print(
        f"Captured {chunks} chunks, {total_bytes} bytes (~{total_bytes / 32000:.1f}s @16k), "
        f"max_rms={max_rms:.4f}"
    )
    if chunks == 0 or total_bytes == 0:
        print("ERROR: no audio captured")
        sys.exit(1)
    if max_rms < 0.001:
        print("WARNING: captured only silence — check mic gain / mute")
    print("CAPTURE OK")


def cmd_level(duration, selector):
    device_id = resolve_device(selector)
    mic = NativeMic(device=device_id)
    if not mic.start():
        print("FAILED to start capture")
        sys.exit(1)
    print(f"Live level for {duration}s (device {device_id}). Speak/move to see response...")
    start = time.monotonic()
    while time.monotonic() - start < duration:
        mic.read_chunk(timeout=0.5)
        lvl = mic.level()
        bar = "#" * int(min(lvl["rms"], 1.0) * 50)
        print(f"\r  rms={lvl['rms']:.4f} peak={lvl['peak']:.4f} |{bar}", end="", flush=True)
        time.sleep(0.05)
    print()
    mic.stop()
    print("LEVEL OK")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == "list":
        cmd_list()
    elif cmd == "capture":
        dur = float(sys.argv[2]) if len(sys.argv) > 2 else 3
        sel = sys.argv[3] if len(sys.argv) > 3 else None
        cmd_capture(dur, sel)
    elif cmd == "level":
        dur = float(sys.argv[2]) if len(sys.argv) > 2 else 5
        sel = sys.argv[3] if len(sys.argv) > 3 else None
        cmd_level(dur, sel)
    else:
        print(__doc__)
        sys.exit(1)
