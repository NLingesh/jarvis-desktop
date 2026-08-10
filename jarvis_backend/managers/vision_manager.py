"""Vision Manager — screenshot capture, OCR, image analysis, and window awareness.

Consolidates vision capabilities under a single manager interface.
"""

import asyncio
import base64
import contextlib
import io
import logging
import os
import secrets
import shutil
import subprocess
from typing import Any

import pytesseract
from PIL import Image

logger = logging.getLogger(__name__)


class VisionManager:
    """Unified vision capabilities: screenshot, OCR, image analysis, windows."""

    def __init__(self, memory_manager: Any = None):
        self.memory_manager = memory_manager
        self._capture_tool: str | None = None

    def diagnostics(self) -> dict:
        return {
            "capture_tool": self._find_capture_tool(),
            "tesseract_available": self._check_tesseract(),
            "pytesseract_available": True,
        }

    def _find_capture_tool(self) -> str | None:
        if self._capture_tool is not None:
            return self._capture_tool
        candidates = {
            "gnome-screenshot": ["gnome-screenshot", "-f"],
            "scrot": ["scrot"],
            "import": ["import", "-window", "root"],
            "screencapture": ["screencapture", "-x", "-T", "0"],
        }
        for tool, _cmd in candidates.items():
            if shutil.which(tool):
                self._capture_tool = tool
                return tool
        return None

    def _check_tesseract(self) -> bool:
        try:
            pytesseract.get_tesseract_version()
            return True
        except Exception:
            return False

    async def capture_screenshot(self, confirm: bool = False) -> dict:
        """Capture the primary display and return base64 PNG."""
        if not confirm:
            return {"error": "confirm=true is required for screenshot"}

        tool = self._find_capture_tool()
        if tool is None:
            return {
                "error": "No screen-capture tool found. Install gnome-screenshot, scrot, or ImageMagick."
            }

        tmp_path = f"/tmp/jarvis_shot_{secrets.token_hex(8)}.png"
        try:
            cmd_map = {
                "gnome-screenshot": [tool, "-f", tmp_path],
                "scrot": [tool, tmp_path],
                "import": [tool, "-window", "root", tmp_path],
                "screencapture": [tool, "-x", "-T", "0", tmp_path],
            }
            await asyncio.to_thread(
                subprocess.run,
                cmd_map[tool],
                check=True,
                capture_output=True,
                text=True,
                timeout=15,
            )
            if not os.path.isfile(tmp_path) or os.path.getsize(tmp_path) == 0:
                return {"error": "Screen capture produced an empty image"}

            with open(tmp_path, "rb") as f:
                data = f.read()
            b64 = base64.b64encode(data).decode("ascii")
            await self._audit("vision.screenshot", "display", "success")
            return {"format": "png", "image_base64": b64}
        except subprocess.CalledProcessError as e:
            logger.error("Screenshot capture failed: %s", e)
            await self._audit("vision.screenshot", "display", f"error: {e}")
            return {"error": f"Capture failed: {e}"}
        except Exception as e:
            logger.error("Screenshot capture error: %s", e)
            await self._audit("vision.screenshot", "display", f"error: {e}")
            return {"error": str(e)}
        finally:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)

    async def ocr_image(self, image_base64: str) -> dict:
        """Run OCR on a base64-encoded image."""
        try:
            raw = base64.b64decode(image_base64)
            img = Image.open(io.BytesIO(raw))
            text = await asyncio.to_thread(pytesseract.image_to_string, img)
            await self._audit("vision.ocr", "image", "success")
            return {"text": text.strip()}
        except Exception as e:
            logger.error("OCR failed: %s", e)
            await self._audit("vision.ocr", "image", f"error: {e}")
            return {"error": str(e)}

    async def analyze_image(
        self, image_base64: str, prompt: str = "Describe this image in detail."
    ) -> dict:
        """Send image to LLM for analysis (requires vision-capable model)."""
        try:
            from routes.state import llm

            result = await llm.analyze_image(image_base64, prompt)
            await self._audit("vision.analyze", "image", "success")
            return {"analysis": result}
        except Exception as e:
            logger.error("Image analysis failed: %s", e)
            await self._audit("vision.analyze", "image", f"error: {e}")
            return {"error": str(e)}

    async def list_windows(self) -> dict:
        """List open windows using EWMH/xprop."""
        try:
            windows = await asyncio.to_thread(self._list_windows_sync)
            return {"windows": windows}
        except Exception as e:
            logger.error("Failed to list windows: %s", e)
            return {"error": str(e), "windows": []}

    async def focus_window(self, window_id: str) -> dict:
        """Focus a window by its X11 window ID."""
        try:
            await asyncio.to_thread(self._focus_window_sync, window_id)
            return {"focused": window_id}
        except Exception as e:
            logger.error("Failed to focus window %s: %s", window_id, e)
            return {"error": str(e)}

    def _list_windows_sync(self) -> list[dict]:
        if not shutil.which("xdotool"):
            return [{"error": "xdotool not installed. Install xdotool for window enumeration."}]
        try:
            result = subprocess.run(
                ["xdotool", "search", "--onlyvisible", "--class", ""],
                capture_output=True,
                text=True,
                timeout=10,
            )
            ids = result.stdout.strip().split("\n") if result.stdout.strip() else []
            windows = []
            for wid in ids[:50]:
                name_result = subprocess.run(
                    ["xdotool", "getwindowname", wid],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                title = name_result.stdout.strip() or wid
                windows.append({"id": wid, "title": title})
            return windows
        except Exception as e:
            return [{"error": str(e)}]

    def _focus_window_sync(self, window_id: str) -> None:
        subprocess.run(
            ["xdotool", "windowactivate", "--sync", window_id],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )

    async def _audit(self, command: str, target: str, result: str) -> None:
        try:
            from modules.audit import log_action

            await log_action(command, target, "vision_manager", result)
        except Exception:
            pass
