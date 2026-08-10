from fastapi import APIRouter, HTTPException, Request

from routes.state import git_manager

router = APIRouter(prefix="/api/git", tags=["git"])


@router.get("/status")
async def git_status(request: Request, project_path: str = ""):
    from routes.deps import require_session_token

    require_session_token(request)
    if not project_path:
        raise HTTPException(status_code=400, detail="project_path is required")
    return git_manager.get_status(project_path)


@router.get("/diff")
async def git_diff(request: Request, project_path: str = "", file_path: str = ""):
    from routes.deps import require_session_token

    require_session_token(request)
    if not project_path:
        raise HTTPException(status_code=400, detail="project_path is required")
    return git_manager.get_diff(project_path, file_path or None)


@router.get("/log")
async def git_log(request: Request, project_path: str = "", limit: int = 20):
    from routes.deps import require_session_token

    require_session_token(request)
    if not project_path:
        raise HTTPException(status_code=400, detail="project_path is required")
    return git_manager.get_log(project_path, limit=limit)


@router.post("/commit")
async def git_commit(request: Request):
    from routes.deps import require_session_token

    require_session_token(request)
    body = await request.json()
    project_path = body.get("project_path", "")
    message = body.get("message", "")
    if not project_path or not message:
        raise HTTPException(status_code=400, detail="project_path and message are required")
    return git_manager.create_commit(project_path, message)


@router.get("/branches")
async def git_branches(request: Request, project_path: str = ""):
    from routes.deps import require_session_token

    require_session_token(request)
    if not project_path:
        raise HTTPException(status_code=400, detail="project_path is required")
    return git_manager.get_branches(project_path)


@router.post("/branch")
async def git_create_branch(request: Request):
    from routes.deps import require_session_token

    require_session_token(request)
    body = await request.json()
    project_path = body.get("project_path", "")
    branch_name = body.get("branch_name", "")
    if not project_path or not branch_name:
        raise HTTPException(status_code=400, detail="project_path and branch_name are required")
    return git_manager.create_branch(project_path, branch_name)
