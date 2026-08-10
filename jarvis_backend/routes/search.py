from fastapi import APIRouter, HTTPException, Request

from routes.state import memory_manager, require_session_token

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("")
async def unified_search(q: str, request: Request):
    require_session_token(request)
    if not q.strip():
        raise HTTPException(status_code=400, detail="q is required")
    results = await memory_manager.search_all(q.strip(), limit=50)
    grouped = {}
    for r in results:
        store = r.get("store", "unknown")
        grouped.setdefault(store, []).append(r)
    return {"query": q.strip(), "results": grouped, "total": len(results)}
