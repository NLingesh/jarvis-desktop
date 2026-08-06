"""Vision routes: desktop screenshot capture."""

from fastapi import APIRouter, HTTPException

from routes.state import vision

router = APIRouter(prefix="/api/vision", tags=["vision"])


@router.get("/screenshot")
async def get_screenshot():
    """Capture the primary display and return it as a base64 PNG."""
    if not vision.supports_capture():
        raise HTTPException(
            status_code=503,
            detail="No screen-capture tool found. Install gnome-screenshot, scrot, or ImageMagick.",
        )
    png_b64 = await vision.capture_screenshot()
    if not png_b64:
        raise HTTPException(status_code=500, detail="Screen capture failed")
    return {"format": "png", "data": png_b64}
