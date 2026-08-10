from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from routes.state import task_manager

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


class TaskCreate(BaseModel):
    title: str
    type: str = "task"
    cron: str | None = None
    due_date: str | None = None
    payload: dict[str, object] | None = None
    project_id: str | None = None


class TaskUpdate(BaseModel):
    title: str | None = None
    status: str | None = None
    priority: str | None = None
    due_date: str | None = None
    project_id: str | None = None
    enabled: bool | None = None


@router.get("/")
async def list_tasks(request: Request, type: str | None = None, status: str | None = None):
    from routes.deps import require_session_token

    require_session_token(request)
    tasks = await task_manager.list_tasks(type=type, status=status)
    return {"tasks": tasks}


@router.get("/{task_id}")
async def get_task(task_id: str, request: Request):
    from routes.deps import require_session_token

    require_session_token(request)
    task = await task_manager.memory.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.post("/")
async def create_task(task: TaskCreate, request: Request):
    from routes.deps import require_session_token

    require_session_token(request)
    result = await task_manager.create_task(
        title=task.title,
        type=task.type,
        cron=task.cron,
        due_date=task.due_date,
        payload=task.payload,
        project_id=task.project_id,
    )
    if result.get("error"):
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.patch("/{task_id}")
async def update_task(task_id: str, task: TaskUpdate, request: Request):
    from routes.deps import require_session_token

    require_session_token(request)
    updates = task.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No updates provided")
    result = await task_manager.memory.update_task(task_id, **updates)
    if result is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return result


@router.post("/{task_id}/complete")
async def complete_task(task_id: str, request: Request):
    from routes.deps import require_session_token

    require_session_token(request)
    result = await task_manager.complete_task(task_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return result


@router.delete("/{task_id}")
async def delete_task(task_id: str, request: Request):
    from routes.deps import require_session_token

    require_session_token(request)
    ok = await task_manager.delete_task(task_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"deleted": True}
