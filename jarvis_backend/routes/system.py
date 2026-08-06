from fastapi import APIRouter, Request

from routes.state import require_session_token, system_actions, validate_system_command

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/info")
async def get_system_info():
    """Get current system information"""
    return system_actions.get_system_info()


@router.post("/execute")
async def execute_system_command(request: Request):
    """Execute a safe system command (allowlisted)"""
    require_session_token(request)
    body = (
        await request.json()
        if request.headers.get("content-type", "").startswith("application/json")
        else {}
    )
    command = body.get("command", "").strip()
    validate_system_command(command)
    output = await system_actions.execute_command(command)
    return {"output": output}
