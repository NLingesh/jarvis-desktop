"""NotesModule — adapter from the JSON notes API onto the Markdown vault.

Keeps the legacy ``/api/notes`` interface (``notebook``-scoped, id-based)
while delegating all storage to the vault. Notebooks map to vault folders
(``default`` -> the ``Notes/`` folder, anything else -> ``<name>/``) and every
note becomes a plain Obsidian-compatible ``.md`` file.

The vault holds a stable UUID ``id`` in each note's frontmatter, which is what
the id-based operations below key on.
"""

import logging

from modules.vault.manager import VaultManager

logger = logging.getLogger(__name__)

DEFAULT_NOTEBOOK_FOLDER = "Notes"


def _folder_for(notebook: str) -> str:
    notebook = (notebook or "default").strip().strip("/")
    return notebook if notebook and notebook != "default" else DEFAULT_NOTEBOOK_FOLDER


class NotesModule:
    def __init__(self, notes_dir: str | None = None, vault: VaultManager | None = None):
        if vault is not None:
            self._vault = vault
        else:
            self._vault = VaultManager(notes_dir or "~/.jarvis/notes")

    def _to_note(self, meta: dict, notebook: str) -> dict:
        return {
            "id": meta["id"],
            "title": meta["title"],
            "content": meta["body"],
            "tags": meta["tags"],
            "notebook": notebook,
            "created_at": meta.get("created"),
            "modified_at": meta.get("modified"),
            "path": meta["path"],
        }

    async def _find(self, note_id: str, notebook: str) -> dict | None:
        folder = _folder_for(notebook)
        notes = await self._vault.list_notes(folder=folder, limit=100000)
        for meta in notes:
            if meta["id"] == note_id:
                return meta
        return None

    async def create_note(
        self, title: str, content: str, tags: list[str] | None = None, notebook: str = "default"
    ) -> dict:
        """Create a new note in the vault's notebook folder."""
        try:
            meta = await self._vault.create_note(
                title, content=content, tags=tags or [], folder=_folder_for(notebook)
            )
            return self._to_note(meta, notebook)
        except Exception as e:
            logger.error("Failed to create note: %s", e)
            return {}

    async def get_notes(self, notebook: str = "default") -> list[dict]:
        """Get all notes from a notebook (newest first)."""
        folder = _folder_for(notebook)
        try:
            notes = await self._vault.list_notes(folder=folder, limit=100000)
            return [self._to_note(meta, notebook) for meta in notes]
        except Exception as e:
            logger.error("Failed to get notes: %s", e)
            return []

    async def get_note(self, note_id: str, notebook: str = "default") -> dict | None:
        """Get a specific note by id."""
        meta = await self._find(note_id, notebook)
        if meta is None:
            return None
        return self._to_note(meta, notebook)

    async def update_note(
        self,
        note_id: str,
        title: str | None = None,
        content: str | None = None,
        tags: list[str] | None = None,
        notebook: str = "default",
    ) -> bool:
        """Update an existing note."""
        meta = await self._find(note_id, notebook)
        if meta is None:
            return False
        try:
            await self._vault.update_note(meta["path"], title=title, content=content, tags=tags)
            return True
        except Exception as e:
            logger.error("Failed to update note %s: %s", note_id, e)
            return False

    async def delete_note(self, note_id: str, notebook: str = "default") -> bool:
        """Delete a note."""
        meta = await self._find(note_id, notebook)
        if meta is None:
            return False
        try:
            await self._vault.delete_note(meta["path"])
            return True
        except Exception as e:
            logger.error("Failed to delete note %s: %s", note_id, e)
            return False

    async def search_notes(self, query: str, notebook: str = "default") -> list[dict]:
        """Search notes by title, content, or tag."""
        query_lower = (query or "").lower()
        notes = await self.get_notes(notebook)
        results = [
            note
            for note in notes
            if query_lower in note.get("title", "").lower()
            or query_lower in note.get("content", "").lower()
            or any(query_lower in tag.lower() for tag in note.get("tags", []))
        ]
        return results
