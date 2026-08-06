"""Tests for VisionModule — screenshot capture with mocked capture tools."""

import asyncio
import base64
import os

from modules.vision_module import VisionModule


def run(coro):
    return asyncio.run(coro)


def test_find_capture_tool_none(monkeypatch):
    monkeypatch.setattr("modules.vision_module.shutil.which", lambda name: None)
    assert VisionModule()._find_capture_tool() is None


def test_find_capture_tool_detects(monkeypatch):
    monkeypatch.setattr(
        "modules.vision_module.shutil.which",
        lambda name: "/usr/bin/" + name if name == "gnome-screenshot" else None,
    )
    assert VisionModule()._find_capture_tool() == "gnome-screenshot"


def test_capture_screenshot_returns_base64_png(monkeypatch):
    vision = VisionModule()
    fake_png = b"\x89PNG\r\n\x1a\n" + b"0" * 32
    calls = []

    def fake_capture(path):
        calls.append(path)
        with open(path, "wb") as f:
            f.write(fake_png)
        return True

    monkeypatch.setattr(vision, "_capture_to_file", fake_capture)
    result = run(vision.capture_screenshot())
    assert result is not None
    assert base64.b64decode(result) == fake_png
    assert len(calls) == 1
    assert not os.path.exists(calls[0])


def test_capture_screenshot_none_when_capture_fails(monkeypatch):
    vision = VisionModule()
    monkeypatch.setattr(vision, "_capture_to_file", lambda path: False)
    assert run(vision.capture_screenshot()) is None


def test_capture_to_file_uses_tool(monkeypatch):
    vision = VisionModule()
    vision._tool = "scrot"
    captured = []

    def fake_run(cmd, **kwargs):
        captured.append(cmd)

    monkeypatch.setattr("modules.vision_module.subprocess.run", fake_run)
    ok = vision._capture_to_file("/tmp/out.png")
    assert ok is False  # file does not exist after "run"
    assert captured == [["scrot", "/tmp/out.png"]]


def test_capture_to_file_catches_errors(monkeypatch, tmp_path):
    vision = VisionModule()
    vision._tool = "scrot"

    def boom(*args, **kwargs):
        raise OSError("no display")

    monkeypatch.setattr("modules.vision_module.subprocess.run", boom)
    assert vision._capture_to_file(str(tmp_path / "out.png")) is False


def test_capture_to_file_success(monkeypatch, tmp_path):
    vision = VisionModule()
    vision._tool = "import"
    target = str(tmp_path / "out.png")

    def fake_run(cmd, **kwargs):
        with open(target, "wb") as f:
            f.write(b"png-data")

    monkeypatch.setattr("modules.vision_module.subprocess.run", fake_run)
    assert vision._capture_to_file(target) is True


def test_supports_capture(monkeypatch):
    monkeypatch.setattr("modules.vision_module.shutil.which", lambda name: None)
    assert VisionModule.supports_capture() is False
