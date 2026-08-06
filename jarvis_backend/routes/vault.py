"""HTTP API for the Markdown memory vault.

All endpoints delegate to the single :class:`VaultManager` singleton
(``routes.state.vault``). Errors are mapped to HTTP status codes:
missing notes -> 404, duplicate paths -> 409, bad input -> 400.
"""

from fastapi import APIRouter, HTTPException, Request

from modules.vault.templates import templates
from routes.state import vault

router = APIRouter(prefix="/api/vault", tags=["vault"])


async def _guard(coro):
    try:
        return await coro
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=f"Note not found: {e}") from e
    except FileExistsError as e:
        raise HTTPException(status_code=409, detail=f"Note already exists: {e}") from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/meta")
async def vault_meta():
    """Stats, vault root path and templates for the UI."""
    stats = await vault.stats()
    stats["templates"] = templates()
    stats["folders"] = await vault.list_folders()
    return {"meta": stats}


# --- notes ------------------------------------------------------------------


@router.post("/notes")
async def create_note(request: Request):
    body = (
        await request.json()
        if request.headers.get("content-type", "").startswith("application/json")
        else {}
    )
    note = await _guard(
        vault.create_note(
            title=body.get("title", ""),
            folder=body.get("folder"),
            note_type=body.get("type"),
            tags=body.get("tags"),
            content=body.get("content", ""),
            status=body.get("status"),
            source=body.get("source"),
            favorite=body.get("favorite", False),
        )
    )
    return {"note": note}


@router.get("/notes")
async def list_notes(
    folder: str | None = None,
    tag: str | None = None,
    type: str | None = None,
    favorite: bool = False,
    limit: int = 100,
):
    return {
        "notes": await vault.list_notes(
            folder=folder, tag=tag, note_type=type, favorite=favorite, limit=limit
        )
    }


@router.get("/note/{rel_path:path}")
async def get_note(rel_path: str):
    return {"note": await _guard(vault.get_note(rel_path))}


@router.put("/note/{rel_path:path}")
async def update_note(rel_path: str, request: Request):
    body = (
        await request.json()
        if request.headers.get("content-type", "").startswith("application/json")
        else {}
    )
    note = await _guard(
        vault.update_note(
            rel_path,
            content=body.get("content"),
            title=body.get("title"),
            tags=body.get("tags"),
            status=body.get("status"),
            favorite=body.get("favorite"),
        )
    )
    return {"note": note}


@router.delete("/note/{rel_path:path}")
async def delete_note(rel_path: str):
    await _guard(vault.delete_note(rel_path))
    return {"deleted": rel_path}


# --- note actions -----------------------------------------------------------


@router.post("/note/append")
async def append_note(request: Request):
    body = await request.json()
    note = await _guard(vault.append_note(body.get("path", ""), body.get("text", "")))
    return {"note": note}


@router.post("/note/rename")
async def rename_note(request: Request):
    body = await request.json()
    note = await _guard(vault.rename_note(body.get("path", ""), body.get("title", "")))
    return {"note": note}


@router.post("/note/move")
async def move_note(request: Request):
    body = await request.json()
    note = await _guard(vault.move_note(body.get("path", ""), body.get("folder", "")))
    return {"note": note}


@router.post("/note/archive")
async def archive_note(request: Request):
    body = await request.json()
    note = await _guard(vault.archive_note(body.get("path", "")))
    return {"note": note}


@router.get("/links/{rel_path:path}")
async def links(rel_path: str):
    return {"links": await _guard(vault.get_links(rel_path))}


@router.get("/backlinks/{rel_path:path}")
async def backlinks(rel_path: str):
    return {"backlinks": await _guard(vault.get_backlinks(rel_path))}


# --- search / folders / tags ------------------------------------------------


@router.get("/search")
async def search(
    q: str | None = None,
    tag: str | None = None,
    type: str | None = None,
    recent: bool = False,
    favorite: bool = False,
    limit: int = 20,
):
    if not (q or tag or type or favorite or recent):
        raise HTTPException(status_code=400, detail="Provide q, tag, type, favorite or recent")
    return {
        "results": await vault.search(
            query=q, tag=tag, note_type=type, recent=recent, favorite=favorite, limit=limit
        )
    }


@router.get("/folders")
async def folders():
    return {"folders": await vault.list_folders()}


@router.post("/folders")
async def create_folder(request: Request):
    body = await request.json()
    return await _guard(vault.create_folder(body.get("folder", "")))


@router.get("/tags")
async def tags():
    return {"tags": await vault.list_tags()}


@router.post("/index")
async def reindex():
    """Force a full re-sync of the FTS search index from disk."""
    await vault.reindex()
    return {"status": "reindexed"}
