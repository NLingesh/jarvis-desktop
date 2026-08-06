import asyncio

from fastapi import APIRouter, HTTPException, Request

from modules.settings import KEY_NAMES, _mask_secret, _write_env_keys, restart_backend_after
from routes.state import ENV_FILE_PATH, require_session_token

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("/keys")
async def get_settings_keys(request: Request):
    """Return masked previews of configured API keys / mail credentials."""
    require_session_token(request)
    import os

    result = {}
    for name in KEY_NAMES:
        result[name] = _mask_secret(os.getenv(name))
    return {"keys": result}


@router.post("/keys")
async def save_settings_keys(request: Request):
    """Persist API keys / mail credentials to the .env file, then restart the backend."""
    require_session_token(request)
    body = await request.json()
    keys = body.get("keys")
    if not isinstance(keys, dict) or not keys:
        raise HTTPException(status_code=400, detail="No keys provided")

    for name in keys:
        if name not in KEY_NAMES:
            raise HTTPException(status_code=400, detail=f"Unsupported key: {name}")

    _write_env_keys(ENV_FILE_PATH, keys)
    asyncio.create_task(restart_backend_after())
    return {
        "success": True,
        "restarting": True,
        "message": "API keys saved. The backend is restarting to apply them.",
    }
