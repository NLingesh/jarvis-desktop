from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from routes.state import workflow_manager

router = APIRouter(prefix="/api/automation", tags=["automation"])


class WorkflowCreate(BaseModel):
    name: str
    trigger: dict[str, object]
    actions: list[dict[str, object]]
    enabled: bool = True


class WorkflowExecute(BaseModel):
    context: dict[str, object] | None = None


@router.get("/workflows")
async def list_workflows(request: Request):
    from routes.deps import require_session_token

    require_session_token(request)
    return {"workflows": workflow_manager.list_workflows()}


@router.post("/workflows")
async def create_workflow(workflow: WorkflowCreate, request: Request):
    from routes.deps import require_session_token

    require_session_token(request)
    result = await workflow_manager.create_workflow(
        name=workflow.name,
        trigger=workflow.trigger,
        actions=workflow.actions,
        enabled=workflow.enabled,
    )
    return result


@router.post("/workflows/{workflow_id}/execute")
async def execute_workflow(workflow_id: str, body: WorkflowExecute, request: Request):
    from routes.deps import require_session_token

    require_session_token(request)
    result = await workflow_manager.execute_workflow(workflow_id, body.context)
    return result


@router.delete("/workflows/{workflow_id}")
async def delete_workflow(workflow_id: str, request: Request):
    from routes.deps import require_session_token

    require_session_token(request)
    ok = await workflow_manager.delete_workflow(workflow_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return {"deleted": True}
