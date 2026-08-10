from fastapi import APIRouter, HTTPException, Request

from routes.state import security_manager

router = APIRouter(prefix="/api/security", tags=["security"])


@router.get("/status")
async def get_security_status(request: Request):
    from routes.deps import require_session_token

    require_session_token(request)
    return await security_manager.get_security_status()


@router.get("/privacy")
async def get_privacy_settings(request: Request):
    from routes.deps import require_session_token

    require_session_token(request)
    return await security_manager.get_privacy_settings()


@router.post("/privacy")
async def update_privacy_setting(request: Request):
    from routes.deps import require_session_token

    require_session_token(request)
    body = await request.json()
    key = body.get("key", "").strip()
    value = body.get("value", "")
    if not key or not value:
        raise HTTPException(status_code=400, detail="key and value are required")
    result = await security_manager.update_privacy_setting(key, value)
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.get("/export")
async def export_data(request: Request):
    from routes.deps import require_session_token

    require_session_token(request)
    return await security_manager.export_user_data()


@router.delete("/data")
async def delete_data(request: Request):
    from routes.deps import require_session_token

    require_session_token(request)
    body = (
        await request.json()
        if request.headers.get("content-type", "").startswith("application/json")
        else {}
    )
    confirm = bool(body.get("confirm", False))
    result = await security_manager.delete_user_data(confirm=confirm)
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result
