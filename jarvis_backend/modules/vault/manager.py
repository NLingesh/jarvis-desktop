"""VaultManager — the single public entry point for the Markdown memory vault.

Every note operation (create, read, update, append, rename, move, delete,
archive, tag, folder, search, links) is exposed here. All file access goes
through :class:`~modules.vault.store.VaultStore` and all queries through a
:class:`~modules.vault.search.SearchBackend`; no other module should touch
vault files directly.

Design notes (see architecture doc §2):
* Filenames are the canonical Obsidian link targets; a UUID ``id`` is also
  stored in frontmatter for stable renames and future graph/vector layers.
* Mutations are serialized with an ``asyncio.Lock`` and written atomically so
  the vault stays safe even when the user edits notes in Obsidian concurrently.
* Search correctness is guaranteed by a content scan that is unioned with the
  FTS index, so stale/absent indexes never hide notes.
"""

import asyncio
import logging
import os
import re

from modules.vault.codec import (
    extract_links,
    extract_tags,
    new_id,
    now_iso,
    parse,
    serialize,
    title_from_filename,
)
from modules.vault.search import Fts5SearchBackend, SearchBackend
from modules.vault.store import VaultStore
from modules.vault.templates import TYPES, slugify

logger = logging.getLogger(__name__)

ARCHIVE_FOLDER = "Archive"

_WIKILINK_TARGET_RE = re.compile(r"\[\[([^\]|#]+)(?:[#|][^\]]*)?\]\]")


class VaultManager:
    def __init__(self, root: str, search_backend: SearchBackend | None = None):
        self.store = VaultStore(root)
        self._search = search_backend or Fts5SearchBackend(
            os.path.join(self.store.root, ".jarvis", "vault_index.db")
        )
        self._lock = asyncio.Lock()
        self._listeners: dict[str, list] = {
            "created": [],
            "updated": [],
            "renamed": [],
            "deleted": [],
        }

    # --- lifecycle ----------------------------------------------------------
    async def initialize(self) -> None:
        """Create the standard folders and re-sync the search index from disk."""
        await asyncio.to_thread(self.store.init_folders)
        os.makedirs(os.path.join(self.store.root, ".jarvis"), exist_ok=True)
        await self.reindex()

    async def reindex(self) -> None:
        await self._search.reindex()
        files = await asyncio.to_thread(self.store.list_files)
        for rel in files:
            await self._search.upsert(await self._meta_async(rel))

    async def close(self) -> None:
        await self._search.close()

    # --- events -------------------------------------------------------------
    def on(self, event: str, callback) -> None:
        """Subscribe to ``created``/``updated``/``renamed``/``deleted`` events."""
        if event in self._listeners:
            self._listeners[event].append(callback)

    def _emit(self, event: str, **kwargs) -> None:
        for cb in self._listeners[event]:
            try:
                asyncio.ensure_future(cb(**kwargs))
            except Exception as e:  # noqa: BLE001 - listener must not break the caller
                logger.error("Vault event listener %s failed: %s", event, e)

    # --- metadata -----------------------------------------------------------
    def _meta(self, rel_path: str) -> dict:
        content = self.store.read(rel_path)
        frontmatter, body = parse(content)
        folder = os.path.dirname(rel_path).replace(os.sep, "/")
        return {
            "path": rel_path,
            "id": frontmatter.get("id") or new_id(),
            "title": frontmatter.get("title") or title_from_filename(rel_path),
            "type": frontmatter.get("type", "knowledge"),
            "tags": extract_tags(content),
            "aliases": list(frontmatter.get("aliases") or []),
            "favorite": bool(frontmatter.get("favorite", False)),
            "status": frontmatter.get("status"),
            "created": frontmatter.get("created"),
            "modified": frontmatter.get("modified"),
            "links": extract_links(content),
            "body": body,
            "folder": folder,
        }

    async def _meta_async(self, rel_path: str) -> dict:
        return await asyncio.to_thread(self._meta, rel_path)

    # --- create / read / update --------------------------------------------
    async def create_note(
        self,
        title: str,
        folder: str | None = None,
        note_type: str = "knowledge",
        tags: list[str] | None = None,
        content: str = "",
        status: str | None = None,
        source: str | None = None,
        favorite: bool = False,
    ) -> dict:
        title = (title or "").strip()
        if not title:
            raise ValueError("title is required")
        note_type = note_type if note_type in TYPES else "knowledge"
        folder = (folder or "").strip().strip("/")
        filename = f"{slugify(title)}.md"
        rel_path = f"{folder}/{filename}" if folder else filename

        async with self._lock:
            if self.store.exists(rel_path):
                raise FileExistsError(f"Note already exists: {rel_path}")
            stamp = now_iso()
            frontmatter = {
                "type": note_type,
                "title": title,
                "id": new_id(),
                "created": stamp,
                "modified": stamp,
                "tags": [str(t).lower() for t in (tags or []) if t],
                "favorite": favorite,
            }
            if status:
                frontmatter["status"] = status
            if source:
                frontmatter["source"] = source
            body = await self._auto_link(content, title)
            full = serialize(frontmatter, body)
            await asyncio.to_thread(self.store.write, rel_path, full)
            meta = await self._meta_async(rel_path)
            await self._search.upsert(meta)
        self._emit("created", rel_path=rel_path, meta=meta)
        return meta

    async def get_note(self, rel_path: str) -> dict:
        if not self.store.exists(rel_path):
            raise FileNotFoundError(rel_path)
        return await self._meta_async(rel_path)

    async def update_note(
        self,
        rel_path: str,
        content: str | None = None,
        title: str | None = None,
        tags: list[str] | None = None,
        status: str | None = None,
        favorite: bool | None = None,
    ) -> dict:
        async with self._lock:
            if not self.store.exists(rel_path):
                raise FileNotFoundError(rel_path)
            raw = await asyncio.to_thread(self.store.read, rel_path)
            frontmatter, body = parse(raw)
            if content is not None:
                body = content
            if title is not None:
                frontmatter["title"] = title.strip()
            if tags is not None:
                frontmatter["tags"] = [str(t).lower() for t in tags if t]
            if status is not None:
                frontmatter["status"] = status
            if favorite is not None:
                frontmatter["favorite"] = bool(favorite)
            frontmatter["modified"] = now_iso()
            full = serialize(frontmatter, body)
            await asyncio.to_thread(self.store.write, rel_path, full)
            meta = await self._meta_async(rel_path)
            await self._search.upsert(meta)
        self._emit("updated", rel_path=rel_path, meta=meta)
        return meta

    async def append_note(self, rel_path: str, text: str) -> dict:
        if not text:
            raise ValueError("Nothing to append")
        async with self._lock:
            if not self.store.exists(rel_path):
                raise FileNotFoundError(rel_path)
            raw = await asyncio.to_thread(self.store.read, rel_path)
            frontmatter, body = parse(raw)
            body = f"{body}\n{text}".strip("\n")
            frontmatter["modified"] = now_iso()
            await asyncio.to_thread(self.store.write, rel_path, serialize(frontmatter, body))
            meta = await self._meta_async(rel_path)
            await self._search.upsert(meta)
        self._emit("updated", rel_path=rel_path, meta=meta)
        return meta

    # --- rename / move / delete / archive ----------------------------------
    async def rename_note(self, rel_path: str, new_title: str) -> dict:
        new_title = (new_title or "").strip()
        if not new_title:
            raise ValueError("new_title is required")
        folder = os.path.dirname(rel_path).replace(os.sep, "/")
        new_rel = f"{folder}/{slugify(new_title)}.md" if folder else f"{slugify(new_title)}.md"
        async with self._lock:
            if not self.store.exists(rel_path):
                raise FileNotFoundError(rel_path)
            if rel_path == new_rel:
                return await self._meta_async(rel_path)
            if self.store.exists(new_rel):
                raise FileExistsError(new_rel)
            raw = await asyncio.to_thread(self.store.read, rel_path)
            frontmatter, body = parse(raw)
            old_title = frontmatter.get("title") or title_from_filename(rel_path)
            aliases = list(frontmatter.get("aliases") or [])
            if old_title and old_title not in aliases:
                aliases.append(old_title)
            frontmatter["title"] = new_title
            frontmatter["aliases"] = aliases
            frontmatter["modified"] = now_iso()
            await asyncio.to_thread(self.store.write, new_rel, serialize(frontmatter, body))
            await asyncio.to_thread(self.store.delete, rel_path)
            await self._search.delete(rel_path)
            meta = await self._meta_async(new_rel)
            await self._search.upsert(meta)
        await self._rewrite_backlinks(old_title, new_title)
        self._emit("renamed", old_path=rel_path, rel_path=new_rel, meta=meta)
        return meta

    async def move_note(self, rel_path: str, dest_folder: str) -> dict:
        dest_folder = (dest_folder or "").strip().strip("/")
        new_rel = (
            f"{dest_folder}/{os.path.basename(rel_path)}"
            if dest_folder
            else os.path.basename(rel_path)
        )
        async with self._lock:
            if not self.store.exists(rel_path):
                raise FileNotFoundError(rel_path)
            if self.store.exists(new_rel):
                raise FileExistsError(new_rel)
            await asyncio.to_thread(self.store.move, rel_path, new_rel)
            await self._search.delete(rel_path)
            meta = await self._meta_async(new_rel)
            await self._search.upsert(meta)
        self._emit("renamed", old_path=rel_path, rel_path=new_rel, meta=meta)
        return meta

    async def archive_note(self, rel_path: str) -> dict:
        return await self._archive_unique(rel_path, os.path.basename(rel_path))

    async def _archive_unique(self, rel_path: str, base: str) -> dict:
        async with self._lock:
            if not self.store.exists(rel_path):
                raise FileNotFoundError(rel_path)
            dest = f"{ARCHIVE_FOLDER}/{base}"
            n = 1
            while self.store.exists(dest):
                stem, ext = os.path.splitext(base)
                dest = f"{ARCHIVE_FOLDER}/{stem}-{n}{ext}"
                n += 1
            await asyncio.to_thread(self.store.move, rel_path, dest)
            await self._search.delete(rel_path)
            meta = await self._meta_async(dest)
            await self._search.upsert(meta)
        self._emit("renamed", old_path=rel_path, rel_path=dest, meta=meta)
        return meta

    async def delete_note(self, rel_path: str) -> None:
        async with self._lock:
            if not self.store.exists(rel_path):
                raise FileNotFoundError(rel_path)
            await asyncio.to_thread(self.store.delete, rel_path)
            await self._search.delete(rel_path)
        self._emit("deleted", rel_path=rel_path)

    # --- listing / tags / folders ------------------------------------------
    async def list_notes(
        self,
        folder: str | None = None,
        tag: str | None = None,
        note_type: str | None = None,
        favorite: bool = False,
        limit: int = 100,
    ) -> list[dict]:
        files = await asyncio.to_thread(self.store.list_files, folder)
        notes = [await self._meta_async(rel) for rel in files]
        notes.sort(key=lambda n: n["modified"] or "", reverse=True)
        return self._filter(notes, tag, note_type, favorite, limit)

    @staticmethod
    def _filter(
        notes: list[dict],
        tag: str | None,
        note_type: str | None,
        favorite: bool,
        limit: int,
    ) -> list[dict]:
        result = []
        for n in notes:
            if tag and tag.lower() not in [t.lower() for t in n["tags"]]:
                continue
            if note_type and n["type"] != note_type:
                continue
            if favorite and not n["favorite"]:
                continue
            result.append(n)
            if limit and len(result) >= limit:
                break
        return result

    async def list_folders(self) -> list[str]:
        return await asyncio.to_thread(self.store.list_folders)

    async def create_folder(self, folder: str) -> dict:
        folder = (folder or "").strip().strip("/")
        if not folder:
            raise ValueError("folder is required")
        await asyncio.to_thread(self.store.mkdir, folder)
        return {"folder": folder}

    async def list_tags(self) -> list[dict]:
        counts: dict[str, int] = {}
        notes = await self.list_notes(limit=100000)
        for n in notes:
            for t in n["tags"]:
                counts[t] = counts.get(t, 0) + 1
        return [{"tag": t, "count": c} for t, c in sorted(counts.items())]

    async def stats(self) -> dict:
        notes = await self.list_notes(limit=100000)
        by_type: dict[str, int] = {}
        for n in notes:
            by_type[n["type"]] = by_type.get(n["type"], 0) + 1
        return {
            "total": len(notes),
            "by_type": by_type,
            "root": self.store.root,
            "favorites": sum(1 for n in notes if n["favorite"]),
        }

    # --- links --------------------------------------------------------------
    async def get_links(self, rel_path: str) -> list[str]:
        meta = await self.get_note(rel_path)
        return meta["links"]

    async def get_backlinks(self, rel_path: str) -> list[dict]:
        meta = await self.get_note(rel_path)
        title = meta["title"]
        hits = await self._search.backlinks(title)
        return [{"path": h["path"], "title": h["title"]} for h in hits if h["path"] != rel_path]

    async def known_titles(self) -> list[str]:
        titles = await self._search.known_titles()
        files = await asyncio.to_thread(self.store.list_files)
        for rel in files:
            titles.append(title_from_filename(rel))
        return list(dict.fromkeys(titles))

    async def _auto_link(self, content: str, exclude_title: str) -> str:
        """Replace bare mentions of known note titles with [[wikilinks]]."""
        known = [t for t in await self.known_titles() if t and t != exclude_title]
        if not known or not content:
            return content
        for title in sorted(known, key=len, reverse=True):
            escaped = re.escape(title)
            pattern = re.compile(rf"(?<!\[\[)\b{escaped}\b")
            content = pattern.sub(f"[[{title}]]", content)
        return content

    async def _rewrite_backlinks(self, old_title: str, new_title: str) -> None:
        if not old_title or old_title == new_title:
            return
        hits = await self._search.backlinks(old_title)
        for hit in hits:
            rel = hit["path"]
            async with self._lock:
                raw = await asyncio.to_thread(self.store.read, rel)
                updated = _WIKILINK_TARGET_RE.sub(
                    lambda m: (
                        m.group(0).replace(old_title, new_title, 1)
                        if m.group(1).strip() == old_title
                        else m.group(0)
                    ),
                    raw,
                )
                if updated != raw:
                    await asyncio.to_thread(self.store.write, rel, updated)
                    meta = await self._meta_async(rel)
                    await self._search.upsert(meta)

    # --- search -------------------------------------------------------------
    async def search(
        self,
        query: str | None = None,
        tag: str | None = None,
        note_type: str | None = None,
        recent: bool = False,
        favorite: bool = False,
        limit: int = 20,
    ) -> list[dict]:
        hits = await self._search.search(
            query=query, tag=tag, note_type=note_type, favorite=favorite, limit=limit * 4
        )
        if query:
            hits = [
                h for h in hits if h["score"] > 0 or query.lower() in (h["title"] or "").lower()
            ]
        # Union with a direct content scan so results are correct even when the
        # FTS index is stale or empty.
        scan = await self.scan_notes(query, tag=tag, note_type=note_type, favorite=favorite)
        by_path = {h["path"]: h for h in hits}
        for s in scan:
            by_path.setdefault(s["path"], s)
        results = list(by_path.values())
        if recent:
            results.sort(key=lambda r: r.get("modified") or "", reverse=True)
        else:
            results.sort(key=lambda r: r.get("score", 0), reverse=True)
        return results[:limit]

    async def scan_notes(
        self,
        query: str | None = None,
        folder: str | None = None,
        tag: str | None = None,
        note_type: str | None = None,
        favorite: bool = False,
    ) -> list[dict]:
        """Direct content scan (correctness fallback for search)."""
        files = await asyncio.to_thread(self.store.list_files, folder)
        q = (query or "").lower()
        out: list[dict] = []
        for rel in files:
            meta = await self._meta_async(rel)
            if tag and tag.lower() not in [t.lower() for t in meta["tags"]]:
                continue
            if note_type and meta["type"] != note_type:
                continue
            if favorite and not meta["favorite"]:
                continue
            if q:
                haystack = " ".join([meta["title"], meta["body"], " ".join(meta["tags"])]).lower()
                if q not in haystack:
                    continue
            out.append(meta)
        return out

    # --- Daily notes ----------------------------------------------------------
    async def create_daily_note(self, date_str: str | None = None) -> dict:
        """Create or retrieve a daily note for the given date."""
        from datetime import datetime

        date_str = date_str or datetime.now().strftime("%Y-%m-%d")
        folder = "Daily Notes"
        filename = f"{date_str}.md"
        rel_path = f"{folder}/{filename}"

        if await asyncio.to_thread(self.store.exists, rel_path):
            return await self.get_note(rel_path)

        content = f"# {date_str}\n\n## Tasks\n\n## Notes\n\n## Reflections\n"
        return await self.create_note(
            title=date_str,
            folder=folder,
            note_type="daily",
            tags=["daily", date_str[:7]],
            content=content,
        )

    async def get_daily_notes(self, limit: int = 30) -> list[dict]:
        """List recent daily notes."""
        return await self.search_notes(folder="Daily Notes", limit=limit)

    # --- Graph / links --------------------------------------------------------
    async def get_note_graph(self, limit: int = 100) -> dict:
        """Build a simple link graph from vault notes."""
        files = await asyncio.to_thread(self.store.list_files)
        nodes: list[dict] = []
        edges: list[dict] = []
        seen_paths: set[str] = set()

        for rel in files:
            if rel in seen_paths:
                continue
            seen_paths.add(rel)
            try:
                meta = await self._meta_async(rel)
                nodes.append(
                    {
                        "id": meta.get("id", rel),
                        "title": meta["title"],
                        "path": rel,
                        "type": meta["type"],
                        "tags": meta["tags"],
                    }
                )
                for link in meta.get("links", []):
                    edges.append({"source": rel, "target": link})
            except Exception:
                continue

        return {"nodes": nodes[:limit], "edges": edges[:limit]}
