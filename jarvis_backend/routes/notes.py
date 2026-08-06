from fastapi import APIRouter, HTTPException, Request

from routes.state import notes

router = APIRouter(prefix="/api/notes", tags=["notes"])


@router.post("")
async def create_note(request: Request):
    """Create a new note"""
    body = (
        await request.json()
        if request.headers.get("content-type", "").startswith("application/json")
        else {}
    )
    title = body.get("title", "Untitled")
    content = body.get("content", "")
    notebook = body.get("notebook", "default")
    note = await notes.create_note(title, content, notebook=notebook)
    return {"note": note}


@router.get("")
async def get_notes(notebook: str = "default"):
    """Get saved notes"""
    return {"notes": await notes.get_notes(notebook)}


@router.get("/search")
async def search_notes(q: str, notebook: str = "default"):
    """Search notes by title, content, or tag."""
    if not q.strip():
        raise HTTPException(status_code=400, detail="q query parameter is required")
    return {"notes": await notes.search_notes(q.strip(), notebook)}


@router.get("/{note_id}")
async def get_note(note_id: str, notebook: str = "default"):
    """Get a single note by id."""
    note = await notes.get_note(note_id, notebook)
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")
    return {"note": note}
