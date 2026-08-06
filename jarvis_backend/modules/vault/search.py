"""Search backends for the vault.

:class:`SearchBackend` is a protocol so a future vector/embedding backend can
replace :class:`Fts5SearchBackend` without changing any caller (§9 of the
design). The FTS backend mirrors the vault in a SQLite FTS5 table and also
answers structural filters (tag, type, favorite, modified) and title fuzzy
matches.
"""

import difflib
import logging
import os
import re
from typing import Protocol

import aiosqlite

logger = logging.getLogger(__name__)


def fts_escape(query: str) -> str:
    """Escape a user query into a safe FTS5 MATCH expression (AND of quoted tokens)."""
    tokens = [t for t in re.findall(r"[\w'-]+", query or "") if t]
    if not tokens:
        return '""'
    return " AND ".join(f'"{t}"' for t in tokens)


class SearchBackend(Protocol):
    async def reindex(self) -> None: ...
    async def upsert(self, meta: dict) -> None: ...
    async def delete(self, rel_path: str) -> None: ...
    async def known_titles(self) -> list[str]: ...
    async def backlinks(self, title: str) -> list[dict]: ...
    async def search(
        self, query: str | None, tag: str | None, note_type: str | None, favorite: bool, limit: int
    ) -> list[dict]: ...
    async def all_rows(self) -> list[dict]: ...
    async def close(self) -> None: ...


class Fts5SearchBackend:
    """SQLite FTS5 index over the vault, kept in sync by the VaultManager."""

    def __init__(self, db_path: str = "vault_index.db"):
        self.db_path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def _get_conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
            conn = await aiosqlite.connect(self.db_path)
            await conn.execute("PRAGMA journal_mode=WAL")
            await conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS vault_fts USING fts5(
                    path UNINDEXED,
                    title,
                    tags,
                    content,
                    note_type UNINDEXED,
                    favorite UNINDEXED,
                    modified UNINDEXED
                )
                """)
            self._conn = conn
        return self._conn

    async def _run(self, sql: str, params: tuple = ()) -> list[dict]:
        conn = await self._get_conn()
        cursor = await conn.execute(sql, params)
        rows = await cursor.fetchall()
        await cursor.close()
        columns = [d[0] for d in cursor.description]
        return [dict(zip(columns, row, strict=False)) for row in rows]

    async def upsert(self, meta: dict) -> None:
        conn = await self._get_conn()
        await conn.execute("DELETE FROM vault_fts WHERE path = ?", (meta["path"],))
        await conn.execute(
            "INSERT INTO vault_fts (path, title, tags, content, note_type, favorite, modified)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                meta["path"],
                meta.get("title", ""),
                " ".join(meta.get("tags") or []),
                meta.get("body", ""),
                meta.get("type", "knowledge"),
                1 if meta.get("favorite") else 0,
                meta.get("modified", ""),
            ),
        )
        await conn.commit()

    async def delete(self, rel_path: str) -> None:
        conn = await self._get_conn()
        await conn.execute("DELETE FROM vault_fts WHERE path = ?", (rel_path,))
        await conn.commit()

    async def reindex(self) -> None:
        await self._get_conn()
        conn = await self._get_conn()
        await conn.execute("DELETE FROM vault_fts")
        await conn.commit()

    async def known_titles(self) -> list[str]:
        rows = await self._run("SELECT title FROM vault_fts")
        return [r["title"] for r in rows]

    async def backlinks(self, title: str) -> list[dict]:
        if not title:
            return []
        pattern = f"%[[{title}]]%"
        rows = await self._run(
            "SELECT path, title FROM vault_fts WHERE content LIKE ? OR title LIKE ?",
            (pattern, pattern),
        )
        return rows

    async def search(
        self,
        query: str | None = None,
        tag: str | None = None,
        note_type: str | None = None,
        favorite: bool = False,
        limit: int = 20,
    ) -> list[dict]:
        sql = "SELECT path, title, tags, note_type, favorite, modified FROM vault_fts"
        conditions: list[str] = []
        params: list = []
        if tag:
            conditions.append("tags LIKE ?")
            params.append(f"%{tag}%")
        if note_type:
            conditions.append("note_type = ?")
            params.append(note_type)
        if favorite:
            conditions.append("favorite = 1")
        if query:
            conditions.append("vault_fts MATCH ?")
            params.append(fts_escape(query))
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        rows = await self._run(sql, tuple(params))
        return [self._decorate(r, query) for r in rows]

    def _decorate(self, row: dict, query: str | None) -> dict:
        row["score"] = 0
        if query:
            row["score"] = _title_score(row["title"], query)
        return row

    async def all_rows(self) -> list[dict]:
        return await self._run(
            "SELECT path, title, tags, note_type, favorite, modified FROM vault_fts"
        )

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None


def _title_score(title: str, query: str) -> float:
    """0..1 heuristic: exact title > prefix > token overlap > substring."""
    title_l = title.lower()
    query_l = query.lower().strip()
    if not query_l:
        return 0.0
    if title_l == query_l:
        return 1.0
    if title_l.startswith(query_l):
        return 0.9
    ratio = difflib.SequenceMatcher(None, title_l, query_l).ratio()
    if ratio >= 0.6:
        return ratio
    if query_l in title_l or title_l in query_l:
        return 0.6
    return 0.0


class ScanSearchBackend:
    """Zero-index backend: every search falls through to the direct content
    scan in :class:`VaultManager`.

    Enabled with ``VAULT_SEARCH_BACKEND=scan``. Keeps the vault fully usable
    without an FTS index at the cost of linear scans and no link autocompletion.
    """

    async def reindex(self) -> None:
        return None

    async def upsert(self, meta: dict) -> None:
        return None

    async def delete(self, rel_path: str) -> None:
        return None

    async def known_titles(self) -> list[str]:
        return []

    async def backlinks(self, title: str) -> list[dict]:
        return []

    async def search(
        self,
        query: str | None = None,
        tag: str | None = None,
        note_type: str | None = None,
        favorite: bool = False,
        limit: int = 20,
    ) -> list[dict]:
        return []

    async def all_rows(self) -> list[dict]:
        return []

    async def close(self) -> None:
        return None
