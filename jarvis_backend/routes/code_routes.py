from fastapi import APIRouter, HTTPException, Request

from routes.state import code_manager

router = APIRouter(prefix="/api/code", tags=["code"])


@router.get("/search")
async def search_code(request: Request, q: str = "", paths: str = ""):
    from routes.deps import require_session_token

    require_session_token(request)
    if not q:
        raise HTTPException(status_code=400, detail="q is required")
    search_paths = paths.split(",") if paths else None
    return code_manager.search_code(q, search_paths)


@router.post("/explain")
async def explain_code(request: Request):
    from routes.deps import require_session_token

    require_session_token(request)
    body = await request.json()
    file_path = body.get("file_path", "")
    line_start = body.get("line_start")
    line_end = body.get("line_end")
    if not file_path:
        raise HTTPException(status_code=400, detail="file_path is required")
    return await code_manager.explain_code(file_path, line_start, line_end)
