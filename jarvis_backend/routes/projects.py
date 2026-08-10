from fastapi import APIRouter, HTTPException, Request

from routes.state import project_manager

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("/")
async def list_projects(request: Request):
    from routes.deps import require_session_token

    require_session_token(request)
    projects = await project_manager.detect_projects()
    return {"projects": projects}


@router.get("/{project_id}/analysis")
async def analyze_project(project_id: str, request: Request):
    from routes.deps import require_session_token

    require_session_token(request)
    project_id = project_id.replace("-", "/")
    analysis = await project_manager.analyze_project(project_id)
    if analysis.get("error"):
        raise HTTPException(status_code=404, detail=analysis["error"])
    return analysis


@router.post("/{project_id}/analyze")
async def deep_analyze_project(project_id: str, request: Request):
    from routes.deps import require_session_token

    require_session_token(request)
    project_id = project_id.replace("-", "/")
    analysis = await project_manager.analyze_project(project_id)
    if analysis.get("error"):
        raise HTTPException(status_code=404, detail=analysis["error"])
    return analysis
