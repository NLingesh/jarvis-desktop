from fastapi import APIRouter, HTTPException, Request

from routes.state import (
    conversation_manager,
    memory_manager,
    preference_manager,
    require_session_token,
)

router = APIRouter(prefix="/api/memory", tags=["memory"])


@router.get("/{session_id}")
async def get_memory(session_id: str):
    """Retrieve conversation history for a session"""
    return {"conversation": await memory_manager.get_conversation(session_id)}


# --- Projects ---------------------------------------------------------------
@router.get("/projects")
async def list_projects(request: Request):
    require_session_token(request)
    return {"projects": await memory_manager.list_projects()}


@router.post("/projects")
async def create_project(request: Request):
    require_session_token(request)
    body = await request.json()
    name = body.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    project = await memory_manager.create_project(
        name=name,
        path=body.get("path"),
        description=body.get("description"),
        tech_stack=body.get("tech_stack"),
    )
    return project


@router.patch("/projects/{project_id}")
async def update_project(project_id: str, request: Request):
    require_session_token(request)
    body = await request.json()
    project = await memory_manager.update_project(
        project_id,
        name=body.get("name"),
        path=body.get("path"),
        description=body.get("description"),
        tech_stack=body.get("tech_stack"),
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.delete("/projects/{project_id}")
async def delete_project(project_id: str, request: Request):
    require_session_token(request)
    body = (
        await request.json()
        if request.headers.get("content-type", "").startswith("application/json")
        else {}
    )
    if not body.get("confirm"):
        raise HTTPException(status_code=400, detail="confirm=true is required")
    ok = await memory_manager.delete_project(project_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"deleted": project_id}


# --- Tasks ------------------------------------------------------------------
@router.get("/tasks")
async def list_tasks(request: Request):
    require_session_token(request)
    status = request.query_params.get("status")
    return {"tasks": await memory_manager.list_tasks(status=status)}


@router.post("/tasks")
async def create_task(request: Request):
    require_session_token(request)
    body = await request.json()
    title = body.get("title", "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="title is required")
    task = await memory_manager.create_task(
        title=title,
        status=body.get("status", "pending"),
        priority=body.get("priority", "medium"),
        due_date=body.get("due_date"),
        project_id=body.get("project_id"),
    )
    return task


@router.patch("/tasks/{task_id}")
async def update_task(task_id: str, request: Request):
    require_session_token(request)
    body = await request.json()
    task = await memory_manager.update_task(
        task_id,
        title=body.get("title"),
        status=body.get("status"),
        priority=body.get("priority"),
        due_date=body.get("due_date"),
        project_id=body.get("project_id"),
    )
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.delete("/tasks/{task_id}")
async def delete_task(task_id: str, request: Request):
    require_session_token(request)
    body = (
        await request.json()
        if request.headers.get("content-type", "").startswith("application/json")
        else {}
    )
    if not body.get("confirm"):
        raise HTTPException(status_code=400, detail="confirm=true is required")
    ok = await memory_manager.delete_task(task_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"deleted": task_id}


# --- Knowledge --------------------------------------------------------------
@router.get("/knowledge")
async def list_knowledge(request: Request):
    require_session_token(request)
    q = request.query_params.get("q", "")
    return {"knowledge": await memory_manager.list_knowledge(q=q)}


@router.post("/knowledge")
async def create_knowledge(request: Request):
    require_session_token(request)
    body = await request.json()
    content = body.get("content", "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="content is required")
    item = await memory_manager.create_knowledge(
        content=content,
        type=body.get("type", "note"),
        source=body.get("source"),
    )
    return item


@router.delete("/knowledge/{knowledge_id}")
async def delete_knowledge(knowledge_id: str, request: Request):
    require_session_token(request)
    body = (
        await request.json()
        if request.headers.get("content-type", "").startswith("application/json")
        else {}
    )
    if not body.get("confirm"):
        raise HTTPException(status_code=400, detail="confirm=true is required")
    ok = await memory_manager.delete_knowledge(knowledge_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Knowledge item not found")
    return {"deleted": knowledge_id}


# --- Preferences ------------------------------------------------------------
@router.get("/preferences/{key}")
async def get_preference(key: str, request: Request):
    require_session_token(request)
    val = await memory_manager.get_preference(key)
    if val is None:
        raise HTTPException(status_code=404, detail="Preference not found")
    return {"key": key, "value": val}


@router.put("/preferences/{key}")
async def set_preference_by_key(key: str, request: Request):
    require_session_token(request)
    body = await request.json()
    value = body.get("value")
    await memory_manager.set_preference(key, value)
    return {"key": key, "value": value}


@router.delete("/preferences/{key}")
async def delete_preference(key: str, request: Request):
    require_session_token(request)
    ok = await memory_manager.delete_preference(key)
    if not ok:
        raise HTTPException(status_code=404, detail="Preference not found")
    return {"deleted": key}


# --- Export / Clear ---------------------------------------------------------
@router.post("/export")
async def export_memory(request: Request):
    require_session_token(request)
    body = (
        await request.json()
        if request.headers.get("content-type", "").startswith("application/json")
        else {}
    )
    fmt = body.get("format", "json")
    if fmt == "markdown":
        data = await memory_manager.export_to_markdown()
    else:
        data = await memory_manager.export_to_json()
    return data


@router.post("/clear")
async def clear_memory(request: Request):
    require_session_token(request)
    body = (
        await request.json()
        if request.headers.get("content-type", "").startswith("application/json")
        else {}
    )
    if not body.get("confirm"):
        raise HTTPException(status_code=400, detail="confirm=true is required")
    await memory_manager.clear(confirm=True)
    return {"cleared": True}


@router.get("/search")
async def search_memory(request: Request):
    require_session_token(request)
    q = request.query_params.get("q", "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="q is required")
    results = await memory_manager.search_all(q, limit=50)
    return {"query": q, "results": results}


# --- Conversation summaries --------------------------------------------------
@router.get("/summaries")
async def get_summaries(request: Request):
    require_session_token(request)
    summaries = await conversation_manager.get_recent_summaries(limit=20)
    return {"summaries": summaries}


@router.post("/summaries/{session_id}")
async def summarize_session(session_id: str, request: Request):
    require_session_token(request)
    summary = await conversation_manager.summarize_session(session_id)
    topics = await conversation_manager.extract_topics(session_id)
    return {"summary": summary, "topics": topics}


# --- Preferences -------------------------------------------------------------
@router.get("/preferences")
async def get_preferences(request: Request):
    require_session_token(request)
    prefs = await preference_manager.get_preferences()
    return {"preferences": prefs}


@router.post("/preferences")
async def set_preference(request: Request):
    require_session_token(request)
    body = await request.json()
    key = body.get("key", "").strip()
    value = body.get("value")
    if not key:
        raise HTTPException(status_code=400, detail="key is required")
    await preference_manager.set_preference(key, value)
    return {"set": key}


@router.post("/preferences/infer/{session_id}")
async def infer_preferences(session_id: str, request: Request):
    require_session_token(request)
    prefs = await preference_manager.infer_preferences(session_id)
    return {"preferences": prefs}


# --- Vault daily notes -------------------------------------------------------
@router.get("/vault/daily-notes")
async def get_daily_notes(request: Request):
    require_session_token(request)
    from routes.state import vault

    notes = await vault.get_daily_notes(limit=30)
    return {"daily_notes": notes}


@router.post("/vault/daily-notes")
async def create_daily_note(request: Request):
    require_session_token(request)
    from routes.state import vault

    body = await request.json()
    date_str = body.get("date")
    note = await vault.create_daily_note(date_str)
    return note


@router.get("/vault/graph")
async def get_vault_graph(request: Request):
    require_session_token(request)
    from routes.state import vault

    graph = await vault.get_note_graph(limit=200)
    return graph
