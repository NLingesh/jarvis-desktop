"""Vision module — desktop screenshot capture as a base64 PNG.

The screen is captured with a platform-appropriate CLI tool
(``gnome-screenshot``, ``import``/ImageMagick, ``scrot`` on Linux; ``screencapture``
on macOS). All capture runs off the event loop via ``asyncio.to_thread``.
"""

import asyncio
import base64
import contextlib
import logging
import os
import shutil
import subprocess
import sys
import tempfile

logger = logging.getLogger(__name__)

_MAX_CAPTURE_BYTES = 4 * 1024 * 1024


class VisionModule:
    """Capture the primary display and return a base64-encoded PNG."""

    def __init__(self):
        self._tool = None

    def _find_capture_tool(self) -> str | None:
        """Return the name of an available screen-capture tool."""
        if self._tool is not None:
            return self._tool
        candidates = {
            "gnome-screenshot": ["gnome-screenshot", "-f"],
            "scrot": ["scrot"],
            "import": ["import", "-window", "root"],
            "screencapture": ["screencapture", "-x", "-T", "0"],
        }
        for tool in candidates:
            if shutil.which(tool):
                self._tool = tool
                return tool
        return None

    def _capture_to_file(self, path: str) -> bool:
        tool = self._find_capture_tool()
        if tool is None:
            logger.error(
                "No screen-capture tool found (gnome-screenshot, scrot, import, screencapture)"
            )
            return False
        cmd_map = {
            "gnome-screenshot": [tool, "-f", path],
            "scrot": [tool, path],
            "import": [tool, "-window", "root", path],
            "screencapture": [tool, "-x", "-T", "0", path],
        }
        try:
            subprocess.run(
                cmd_map[tool],
                check=True,
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (subprocess.CalledProcessError, FileNotFoundError, OSError) as e:
            logger.error("Screen capture with %s failed: %s", tool, e)
            return False
        return os.path.isfile(path) and os.path.getsize(path) > 0

    def _encode_file(self, path: str) -> str | None:
        with open(path, "rb") as f:
            data = f.read()
        if len(data) > _MAX_CAPTURE_BYTES:
            logger.warning("Screenshot is too large (%d bytes); skipping", len(data))
            return None
        return base64.b64encode(data).decode("ascii")

    async def capture_screenshot(self) -> str | None:
        """Capture the screen and return a base64 PNG string, or None on failure."""
        with tempfile.NamedTemporaryFile(suffix=".png", prefix="jarvis_shot_", delete=False) as tmp:
            path = tmp.name
        try:
            ok = await asyncio.to_thread(self._capture_to_file, path)
            if not ok:
                return None
            return await asyncio.to_thread(self._encode_file, path)
        finally:
            with contextlib.suppress(OSError):
                os.unlink(path)

    @staticmethod
    def supports_capture() -> bool:
        return any(
            shutil.which(t) for t in ("gnome-screenshot", "scrot", "import", "screencapture")
        )


def _is_macos() -> bool:
    return sys.platform == "darwin"
