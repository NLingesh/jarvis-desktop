from fastapi import APIRouter

from routes.state import memory_manager

router = APIRouter(prefix="/api/memory", tags=["memory"])


@router.get("/{session_id}")
async def get_memory(session_id: str):
    """Retrieve conversation history for a session"""
    return {"conversation": await memory_manager.get_conversation(session_id)}
