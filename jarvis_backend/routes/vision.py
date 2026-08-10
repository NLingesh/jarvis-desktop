"""Vision routes: screenshot, OCR, image analysis, window awareness."""

from fastapi import APIRouter, HTTPException, Request

from routes.state import require_session_token, vision_manager

router = APIRouter(prefix="/api/vision", tags=["vision"])


@router.get("/screenshot")
async def get_screenshot():
    """Capture the primary display and return it as a base64 PNG."""
    result = await vision_manager.capture_screenshot(confirm=True)
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return result


@router.post("/screenshot")
async def post_screenshot(request: Request):
    require_session_token(request)
    body = (
        await request.json()
        if request.headers.get("content-type", "").startswith("application/json")
        else {}
    )
    confirm = body.get("confirm", True)
    result = await vision_manager.capture_screenshot(confirm=confirm)
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return result


@router.post("/ocr")
async def ocr_image(request: Request):
    require_session_token(request)
    body = await request.json()
    image_b64 = body.get("image_base64", "")
    if not image_b64:
        raise HTTPException(status_code=400, detail="image_base64 is required")
    result = await vision_manager.ocr_image(image_b64)
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return result


@router.post("/analyze")
async def analyze_image(request: Request):
    require_session_token(request)
    body = await request.json()
    image_b64 = body.get("image_base64", "")
    prompt = body.get("prompt", "Describe this image in detail.")
    if not image_b64:
        raise HTTPException(status_code=400, detail="image_base64 is required")
    result = await vision_manager.analyze_image(image_b64, prompt)
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return result


@router.get("/windows")
async def list_windows(request: Request):
    require_session_token(request)
    return await vision_manager.list_windows()


@router.post("/windows/{window_id}/focus")
async def focus_window(window_id: str, request: Request):
    require_session_token(request)
    result = await vision_manager.focus_window(window_id)
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return result
