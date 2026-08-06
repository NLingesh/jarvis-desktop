import json
import re
import secrets
import uuid

import aiosqlite


class MemoryManager:
    """Async SQLite-backed conversation memory with FTS5 search.

    Uses a single aiosqlite connection, so database operations never block the
    event loop and connections are not opened/closed per call.
    """

    def __init__(self, db_path: str = "jarvis_memory.db"):
        self.db_path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def _get_conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            conn = await aiosqlite.connect(self.db_path)
            await conn.execute("PRAGMA journal_mode=WAL")
            self._conn = conn
            await self._init_schema(conn)
        return self._conn

    async def _init_schema(self, conn: aiosqlite.Connection) -> None:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                session_id TEXT,
                role TEXT,
                content TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                metadata TEXT
            )
            """)
        await conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS conversations_fts USING fts5(
                content,
                role,
                session_id
            )
            """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_active DATETIME DEFAULT CURRENT_TIMESTAMP,
                metadata TEXT
            )
            """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS mail_sessions (
                token TEXT PRIMARY KEY,
                email_address TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                expires_at DATETIME NOT NULL
            )
            """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS auth_sessions (
                token TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                expires_at DATETIME NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
            """)
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_auth_sessions_user ON auth_sessions(user_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_conversations_session ON conversations(session_id)"
        )
        await conn.commit()

    @staticmethod
    def _fts_escape(query: str) -> str:
        """Escape a user query into a safe FTS5 MATCH expression.

        Unquoted user input containing FTS5 special characters would raise a
        syntax error; build a quoted AND-of-tokens expression instead.
        """
        tokens = [t for t in re.findall(r"[\w'-]+", query or "") if t]
        if not tokens:
            return '""'
        return " AND ".join(f'"{t}"' for t in tokens)

    async def create_session(self) -> str:
        session_id = str(uuid.uuid4())
        conn = await self._get_conn()
        await conn.execute("INSERT INTO sessions (id) VALUES (?)", (session_id,))
        await conn.commit()
        return session_id

    async def add_message(
        self, session_id: str, role: str, content: str, metadata: dict | None = None
    ) -> None:
        msg_id = str(uuid.uuid4())
        conn = await self._get_conn()

        await conn.execute(
            "INSERT INTO conversations (id, session_id, role, content, metadata)"
            " VALUES (?, ?, ?, ?, ?)",
            (msg_id, session_id, role, content, json.dumps(metadata or {})),
        )
        await conn.execute(
            "INSERT INTO conversations_fts (content, role, session_id) VALUES (?, ?, ?)",
            (content, role, session_id),
        )
        await conn.execute(
            "UPDATE sessions SET last_active = CURRENT_TIMESTAMP WHERE id = ?",
            (session_id,),
        )
        await conn.commit()

    async def get_conversation(self, session_id: str, limit: int = 20) -> list[dict]:
        conn = await self._get_conn()
        cursor = await conn.execute(
            "SELECT role, content FROM conversations"
            " WHERE session_id = ?"
            " ORDER BY timestamp DESC, rowid DESC LIMIT ?",
            (session_id, limit),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        messages = [{"role": role, "content": content} for role, content in reversed(rows)]
        return messages

    async def search_memory(self, query: str, session_id: str | None = None) -> list[dict]:
        conn = await self._get_conn()
        match_expr = self._fts_escape(query)
        if session_id:
            cursor = await conn.execute(
                "SELECT content, role, session_id FROM conversations_fts"
                " WHERE conversations_fts MATCH ? AND session_id = ? LIMIT 10",
                (match_expr, session_id),
            )
        else:
            cursor = await conn.execute(
                "SELECT content, role, session_id FROM conversations_fts"
                " WHERE conversations_fts MATCH ? LIMIT 10",
                (match_expr,),
            )
        rows = await cursor.fetchall()
        await cursor.close()
        return [
            {"content": content, "role": role, "session_id": sid} for content, role, sid in rows
        ]

    async def create_mail_session(self, email_address: str, ttl_hours: int = 24) -> str:
        token = secrets.token_urlsafe(32)
        conn = await self._get_conn()
        await conn.execute(
            "INSERT INTO mail_sessions (token, email_address, expires_at)"
            " VALUES (?, ?, datetime('now', ?))",
            (token, email_address, f"+{ttl_hours} hours"),
        )
        await conn.commit()
        return token

    async def get_mail_session(self, token: str) -> str | None:
        conn = await self._get_conn()
        cursor = await conn.execute(
            "SELECT email_address FROM mail_sessions"
            " WHERE token = ? AND expires_at > datetime('now')",
            (token,),
        )
        row = await cursor.fetchone()
        await cursor.close()
        return row[0] if row else None

    async def cleanup_expired_mail_sessions(self) -> None:
        conn = await self._get_conn()
        await conn.execute("DELETE FROM mail_sessions WHERE expires_at <= datetime('now')")
        await conn.commit()

    # --- User accounts / auth sessions -------------------------------------
    async def create_user(self, username: str, password_hash: str) -> str | None:
        """Create a user account. Returns the user id, or None if the username exists."""
        conn = await self._get_conn()
        existing = await conn.execute("SELECT 1 FROM users WHERE username = ?", (username,))
        if await existing.fetchone():
            await existing.close()
            return None
        await existing.close()
        user_id = str(uuid.uuid4())
        await conn.execute(
            "INSERT INTO users (id, username, password_hash) VALUES (?, ?, ?)",
            (user_id, username, password_hash),
        )
        await conn.commit()
        return user_id

    async def get_user(self, username: str) -> dict | None:
        conn = await self._get_conn()
        cursor = await conn.execute(
            "SELECT id, username, password_hash FROM users WHERE username = ?",
            (username,),
        )
        row = await cursor.fetchone()
        await cursor.close()
        if row is None:
            return None
        return {"id": row[0], "username": row[1], "password_hash": row[2]}

    async def get_user_by_id(self, user_id: str) -> dict | None:
        conn = await self._get_conn()
        cursor = await conn.execute("SELECT id, username FROM users WHERE id = ?", (user_id,))
        row = await cursor.fetchone()
        await cursor.close()
        if row is None:
            return None
        return {"id": row[0], "username": row[1]}

    async def create_auth_session(self, user_id: str, ttl_hours: int = 24) -> str:
        token = secrets.token_urlsafe(48)
        conn = await self._get_conn()
        await conn.execute(
            "INSERT INTO auth_sessions (token, user_id, expires_at)"
            " VALUES (?, ?, datetime('now', ?))",
            (token, user_id, f"+{ttl_hours} hours"),
        )
        await conn.commit()
        return token

    async def get_auth_session(self, token: str) -> dict | None:
        conn = await self._get_conn()
        cursor = await conn.execute(
            "SELECT token, user_id FROM auth_sessions"
            " WHERE token = ? AND expires_at > datetime('now')",
            (token,),
        )
        row = await cursor.fetchone()
        await cursor.close()
        if row is None:
            return None
        return {"token": row[0], "user_id": row[1]}

    async def delete_auth_session(self, token: str) -> None:
        conn = await self._get_conn()
        await conn.execute("DELETE FROM auth_sessions WHERE token = ?", (token,))
        await conn.commit()

    async def cleanup_expired_auth_sessions(self) -> None:
        conn = await self._get_conn()
        await conn.execute("DELETE FROM auth_sessions WHERE expires_at <= datetime('now')")
        await conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
