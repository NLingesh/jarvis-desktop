from fastapi import APIRouter, HTTPException, Request

from routes.state import permission_manager, plugin_registry, require_session_token

router = APIRouter(prefix="/api/plugins", tags=["plugins"])


@router.get("/")
async def list_plugins(request: Request):
    require_session_token(request)
    return {"plugins": plugin_registry.list_plugins()}


@router.post("/{name}/enable")
async def enable_plugin(name: str, request: Request):
    require_session_token(request)
    plugin = plugin_registry.get(name)
    if not plugin:
        raise HTTPException(status_code=404, detail="Plugin not found")
    plugin.enabled = True
    return {"name": name, "enabled": True}


@router.post("/{name}/disable")
async def disable_plugin(name: str, request: Request):
    require_session_token(request)
    plugin = plugin_registry.get(name)
    if not plugin:
        raise HTTPException(status_code=404, detail="Plugin not found")
    plugin.enabled = False
    return {"name": name, "enabled": False}


@router.get("/{name}/permissions")
async def get_plugin_permissions(name: str, request: Request):
    require_session_token(request)
    plugin = plugin_registry.get(name)
    if not plugin:
        raise HTTPException(status_code=404, detail="Plugin not found")
    return {
        "name": name,
        "permissions": plugin.permissions,
        "grants": permission_manager.get_plugin_permissions(name),
    }


@router.post("/{name}/grant")
async def grant_permission(name: str, request: Request):
    require_session_token(request)
    body = await request.json()
    permission = body.get("permission", "").strip()
    if not permission:
        raise HTTPException(status_code=400, detail="permission is required")
    permission_manager.grant(name, permission)
    return {"name": name, "permission": permission, "granted": True}


@router.post("/{name}/revoke")
async def revoke_permission(name: str, request: Request):
    require_session_token(request)
    body = await request.json()
    permission = body.get("permission", "").strip()
    if not permission:
        raise HTTPException(status_code=400, detail="permission is required")
    permission_manager.revoke(name, permission)
    return {"name": name, "permission": permission, "revoked": True}
