import contextlib
import json
import os
import re
import secrets
import uuid
from pathlib import Path
from typing import Any

import aiosqlite

ALLOWED_FILE_BASE = os.path.expanduser("~")


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
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                path TEXT,
                description TEXT,
                tech_stack TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                priority TEXT DEFAULT 'medium',
                due_date DATETIME,
                project_id TEXT,
                type TEXT DEFAULT 'task',
                cron TEXT,
                next_run DATETIME,
                enabled INTEGER DEFAULT 1,
                payload TEXT DEFAULT '{}',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (project_id) REFERENCES projects (id)
            )
            """)
        for column in ["type", "cron", "next_run", "enabled", "payload"]:
            with contextlib.suppress(Exception):
                await conn.execute(f"ALTER TABLE tasks ADD COLUMN {column} ''")
        with contextlib.suppress(Exception):
            await conn.execute("ALTER TABLE tasks ADD COLUMN enabled INTEGER DEFAULT 1")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS knowledge (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                content TEXT NOT NULL,
                source TEXT,
                embedding_text TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS preferences (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id TEXT PRIMARY KEY,
                command TEXT,
                target TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                permission_used TEXT,
                result TEXT
            )
            """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS behavior_patterns (
                id TEXT PRIMARY KEY,
                pattern_type TEXT NOT NULL,
                trigger TEXT NOT NULL,
                action TEXT NOT NULL,
                confidence REAL DEFAULT 1.0,
                occurrences INTEGER DEFAULT 1,
                last_occurrence DATETIME DEFAULT CURRENT_TIMESTAMP,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS learning_feedback (
                id TEXT PRIMARY KEY,
                session_id TEXT,
                prediction TEXT,
                actual TEXT,
                correct INTEGER DEFAULT 0,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """)
        await conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS projects_fts USING fts5(name, description, tech_stack)"
        )
        await conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS tasks_fts USING fts5(title, priority)"
        )
        await conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(content, type, source)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_auth_sessions_user ON auth_sessions(user_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_conversations_session ON conversations(session_id)"
        )
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id)")
        await conn.commit()

    @staticmethod
    def _fts_escape(query: str) -> str:
        tokens = [t for t in re.findall(r"[\w'-]+", query or "") if t]
        if not tokens:
            return '""'
        return " AND ".join(f'"{t}"' for t in tokens)

    # --- Sessions / Messages -------------------------------------------------
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
        results: list[dict] = []
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
        results.extend(
            [
                {"content": c, "role": r, "session_id": s, "store": "conversations"}
                for c, r, s in rows
            ]
        )
        for _table, fts_table, store in [
            ("projects", "projects_fts", "projects"),
            ("tasks", "tasks_fts", "tasks"),
            ("knowledge", "knowledge_fts", "knowledge"),
        ]:
            try:
                cursor = await conn.execute(
                    f"SELECT rowid, content FROM {fts_table} WHERE {fts_table} MATCH ? LIMIT 10",
                    (match_expr,),
                )
                rows = await cursor.fetchall()
                await cursor.close()
                for rowid, content in rows:
                    results.append({"content": content, "rowid": rowid, "store": store})
            except Exception:
                pass
        return results

    # --- Mail sessions -------------------------------------------------------
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

    # --- User accounts / auth sessions ---------------------------------------
    async def create_user(self, username: str, password_hash: str) -> str | None:
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

    # --- Projects CRUD -------------------------------------------------------
    async def create_project(
        self, name: str, path: str = "", description: str = "", tech_stack: str = ""
    ) -> dict:
        project_id = str(uuid.uuid4())
        conn = await self._get_conn()
        await conn.execute(
            "INSERT INTO projects (id, name, path, description, tech_stack) VALUES (?, ?, ?, ?, ?)",
            (project_id, name, path, description, tech_stack),
        )
        await conn.execute(
            "INSERT INTO projects_fts (rowid, name, description, tech_stack) VALUES ((SELECT rowid FROM projects WHERE id = ?), ?, ?, ?)",
            (project_id, name, description, tech_stack),
        )
        await conn.commit()
        return await self.get_project(project_id)

    async def get_project(self, project_id: str) -> dict | None:
        conn = await self._get_conn()
        cursor = await conn.execute(
            "SELECT id, name, path, description, tech_stack, created_at, updated_at FROM projects WHERE id = ?",
            (project_id,),
        )
        row = await cursor.fetchone()
        await cursor.close()
        if row is None:
            return None
        return {
            "id": row[0],
            "name": row[1],
            "path": row[2],
            "description": row[3],
            "tech_stack": row[4],
            "created_at": row[5],
            "updated_at": row[6],
        }

    async def update_project(self, project_id: str, **kwargs) -> dict | None:
        project = await self.get_project(project_id)
        if project is None:
            return None
        allowed = {"name", "path", "description", "tech_stack"}
        sets = []
        values = []
        for key, value in kwargs.items():
            if key in allowed:
                sets.append(f"{key} = ?")
                values.append(value)
        if not sets:
            return project
        values.append(project_id)
        conn = await self._get_conn()
        await conn.execute(
            f"UPDATE projects SET {', '.join(sets)}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            values,
        )
        await conn.commit()
        return await self.get_project(project_id)

    async def delete_project(self, project_id: str) -> bool:
        conn = await self._get_conn()
        await conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        await conn.execute("DELETE FROM tasks WHERE project_id = ?", (project_id,))
        await conn.commit()
        return True

    async def list_projects(self, limit: int = 100) -> list[dict]:
        conn = await self._get_conn()
        cursor = await conn.execute(
            "SELECT id, name, path, description, tech_stack, created_at, updated_at FROM projects ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return [
            {
                "id": r[0],
                "name": r[1],
                "path": r[2],
                "description": r[3],
                "tech_stack": r[4],
                "created_at": r[5],
                "updated_at": r[6],
            }
            for r in rows
        ]

    # --- Tasks CRUD ----------------------------------------------------------
    async def create_task(
        self,
        title: str,
        status: str = "pending",
        priority: str = "medium",
        due_date: str | None = None,
        project_id: str | None = None,
        type: str = "task",
        cron: str | None = None,
        next_run: str | None = None,
        enabled: bool = True,
        payload: dict[str, Any] | None = None,
    ) -> dict:
        task_id = str(uuid.uuid4())
        conn = await self._get_conn()
        await conn.execute(
            "INSERT INTO tasks (id, title, status, priority, due_date, project_id, type, cron, next_run, enabled, payload) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                task_id,
                title,
                status,
                priority,
                due_date,
                project_id,
                type,
                cron,
                next_run,
                1 if enabled else 0,
                json.dumps(payload or {}),
            ),
        )
        await conn.execute(
            "INSERT OR REPLACE INTO tasks_fts (rowid, title, priority) VALUES ((SELECT rowid FROM tasks WHERE id = ?), ?, ?)",
            (task_id, title, priority),
        )
        await conn.commit()
        return await self.get_task(task_id)

    async def get_task(self, task_id: str) -> dict | None:
        conn = await self._get_conn()
        cursor = await conn.execute(
            "SELECT id, title, status, priority, due_date, project_id, type, cron, next_run, enabled, payload, created_at, updated_at FROM tasks WHERE id = ?",
            (task_id,),
        )
        row = await cursor.fetchone()
        await cursor.close()
        if row is None:
            return None
        return {
            "id": row[0],
            "title": row[1],
            "status": row[2],
            "priority": row[3],
            "due_date": row[4],
            "project_id": row[5],
            "type": row[6],
            "cron": row[7],
            "next_run": row[8],
            "enabled": bool(row[9]),
            "payload": json.loads(row[10] or "{}"),
            "created_at": row[11],
            "updated_at": row[12],
        }

    async def update_task(self, task_id: str, **kwargs) -> dict | None:
        task = await self.get_task(task_id)
        if task is None:
            return None
        allowed = {
            "title",
            "status",
            "priority",
            "due_date",
            "project_id",
            "type",
            "cron",
            "next_run",
            "enabled",
            "payload",
        }
        sets = []
        values = []
        for key, value in kwargs.items():
            if key in allowed:
                if key == "payload" and isinstance(value, dict):
                    value = json.dumps(value)
                sets.append(f"{key} = ?")
                values.append(value)
        if not sets:
            return task
        values.append(task_id)
        conn = await self._get_conn()
        await conn.execute(
            f"UPDATE tasks SET {', '.join(sets)}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            values,
        )
        await conn.commit()
        return await self.get_task(task_id)

    async def delete_task(self, task_id: str) -> bool:
        conn = await self._get_conn()
        await conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        await conn.commit()
        return True

    async def list_tasks(
        self, status: str | None = None, project_id: str | None = None, limit: int = 100
    ) -> list[dict]:
        conn = await self._get_conn()
        query = "SELECT id, title, status, priority, due_date, project_id, type, cron, next_run, enabled, payload, created_at, updated_at FROM tasks WHERE 1=1"
        params = []
        if status:
            query += " AND status = ?"
            params.append(status)
        if project_id:
            query += " AND project_id = ?"
            params.append(project_id)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        cursor = await conn.execute(query, params)
        rows = await cursor.fetchall()
        await cursor.close()
        return [
            {
                "id": r[0],
                "title": r[1],
                "status": r[2],
                "priority": r[3],
                "due_date": r[4],
                "project_id": r[5],
                "type": r[6],
                "cron": r[7],
                "next_run": r[8],
                "enabled": bool(r[9]),
                "payload": json.loads(r[10] or "{}"),
                "created_at": r[11],
                "updated_at": r[12],
            }
            for r in rows
        ]

    # --- Knowledge CRUD ------------------------------------------------------
    async def create_knowledge(
        self, content: str, k_type: str = "note", source: str = "", embedding_text: str = ""
    ) -> dict:
        k_id = str(uuid.uuid4())
        conn = await self._get_conn()
        await conn.execute(
            "INSERT INTO knowledge (id, type, content, source, embedding_text) VALUES (?, ?, ?, ?, ?)",
            (k_id, k_type, content, source, embedding_text),
        )
        await conn.execute(
            "INSERT INTO knowledge_fts (rowid, content, type, source) VALUES ((SELECT rowid FROM knowledge WHERE id = ?), ?, ?, ?)",
            (k_id, content, k_type, source),
        )
        await conn.commit()
        return await self.get_knowledge(k_id)

    async def get_knowledge(self, k_id: str) -> dict | None:
        conn = await self._get_conn()
        cursor = await conn.execute(
            "SELECT id, type, content, source, embedding_text, created_at FROM knowledge WHERE id = ?",
            (k_id,),
        )
        row = await cursor.fetchone()
        await cursor.close()
        if row is None:
            return None
        return {
            "id": row[0],
            "type": row[1],
            "content": row[2],
            "source": row[3],
            "embedding_text": row[4],
            "created_at": row[5],
        }

    async def update_knowledge(self, k_id: str, **kwargs) -> dict | None:
        knowledge = await self.get_knowledge(k_id)
        if knowledge is None:
            return None
        allowed = {"type", "content", "source", "embedding_text"}
        sets = []
        values = []
        for key, value in kwargs.items():
            if key in allowed:
                sets.append(f"{key} = ?")
                values.append(value)
        if not sets:
            return knowledge
        values.append(k_id)
        conn = await self._get_conn()
        await conn.execute(
            f"UPDATE knowledge SET {', '.join(sets)} WHERE id = ?",
            values,
        )
        await conn.commit()
        return await self.get_knowledge(k_id)

    async def delete_knowledge(self, k_id: str) -> bool:
        conn = await self._get_conn()
        await conn.execute("DELETE FROM knowledge WHERE id = ?", (k_id,))
        await conn.commit()
        return True

    async def list_knowledge(self, k_type: str | None = None, limit: int = 100) -> list[dict]:
        conn = await self._get_conn()
        query = (
            "SELECT id, type, content, source, embedding_text, created_at FROM knowledge WHERE 1=1"
        )
        params = []
        if k_type:
            query += " AND type = ?"
            params.append(k_type)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        cursor = await conn.execute(query, params)
        rows = await cursor.fetchall()
        await cursor.close()
        return [
            {
                "id": r[0],
                "type": r[1],
                "content": r[2],
                "source": r[3],
                "embedding_text": r[4],
                "created_at": r[5],
            }
            for r in rows
        ]

    # --- Preferences ---------------------------------------------------------
    async def set_preference(self, key: str, value: dict | str) -> None:
        conn = await self._get_conn()
        blob = json.dumps(value) if not isinstance(value, str) else value
        await conn.execute(
            "INSERT INTO preferences (key, value, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = CURRENT_TIMESTAMP",
            (key, blob),
        )
        await conn.commit()

    async def get_preference(self, key: str) -> dict | str | None:
        conn = await self._get_conn()
        cursor = await conn.execute("SELECT value FROM preferences WHERE key = ?", (key,))
        row = await cursor.fetchone()
        await cursor.close()
        if row is None:
            return None
        try:
            return json.loads(row[0])
        except (json.JSONDecodeError, TypeError):
            return row[0]

    async def delete_preference(self, key: str) -> bool:
        conn = await self._get_conn()
        await conn.execute("DELETE FROM preferences WHERE key = ?", (key,))
        await conn.commit()
        return True

    async def list_preferences(self, limit: int = 200) -> list[dict]:
        conn = await self._get_conn()
        cursor = await conn.execute(
            "SELECT key, value, created_at, updated_at FROM preferences ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        result = []
        for key, value, created_at, updated_at in rows:
            try:
                parsed = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                parsed = value
            result.append(
                {"key": key, "value": parsed, "created_at": created_at, "updated_at": updated_at}
            )
        return result

    # --- Audit Log -----------------------------------------------------------
    async def log_audit(
        self, command: str, target: str, permission_used: str = "", result: str = ""
    ) -> None:
        entry_id = str(uuid.uuid4())
        conn = await self._get_conn()
        await conn.execute(
            "INSERT INTO audit_log (id, command, target, permission_used, result) VALUES (?, ?, ?, ?, ?)",
            (entry_id, command, target, permission_used, result),
        )
        await conn.commit()

    async def get_audit_log(self, limit: int = 200) -> list[dict]:
        conn = await self._get_conn()
        cursor = await conn.execute(
            "SELECT id, command, target, timestamp, permission_used, result FROM audit_log ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        return [
            {
                "id": r[0],
                "command": r[1],
                "target": r[2],
                "timestamp": r[3],
                "permission_used": r[4],
                "result": r[5],
            }
            for r in rows
        ]

    async def clear_audit_log(self) -> None:
        conn = await self._get_conn()
        await conn.execute("DELETE FROM audit_log")
        await conn.commit()

    # --- Search across stores (LIKE fallback) ---------------------------------
    async def search_all(self, query: str, limit: int = 50) -> list[dict]:
        q = f"%{query.lower()}%"
        conn = await self._get_conn()
        results: list[dict] = []

        cursor = await conn.execute(
            "SELECT id, role, content, timestamp, 'conversation' as store FROM conversations WHERE lower(content) LIKE ? OR lower(role) LIKE ? LIMIT ?",
            (q, q, limit),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        for r in rows:
            results.append(
                {
                    "id": r[0],
                    "title": r[2][:80],
                    "content": r[2],
                    "timestamp": r[3],
                    "store": r[4],
                    "score": 1,
                }
            )

        cursor = await conn.execute(
            "SELECT id, name, description, tech_stack, 'project' as store FROM projects WHERE lower(name) LIKE ? OR lower(description) LIKE ? LIMIT ?",
            (q, q, limit),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        for r in rows:
            results.append(
                {"id": r[0], "title": r[1], "content": r[2] or "", "store": r[4], "score": 1}
            )

        cursor = await conn.execute(
            "SELECT id, title, status, priority, 'task' as store FROM tasks WHERE lower(title) LIKE ? OR lower(status) LIKE ? LIMIT ?",
            (q, q, limit),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        for r in rows:
            results.append({"id": r[0], "title": r[1], "content": r[2], "store": r[4], "score": 1})

        cursor = await conn.execute(
            "SELECT id, type, content, source, 'knowledge' as store FROM knowledge WHERE lower(content) LIKE ? OR lower(type) LIKE ? LIMIT ?",
            (q, q, limit),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        for r in rows:
            results.append(
                {"id": r[0], "title": r[2][:80], "content": r[2], "store": r[4], "score": 1}
            )

        return results[:limit]

    # --- Export --------------------------------------------------------------
    async def export_to_json(self, path: str) -> str:
        data = {
            "conversations": [],
            "projects": await self.list_projects(),
            "tasks": await self.list_tasks(),
            "knowledge": await self.list_knowledge(),
            "preferences": await self.list_preferences(),
        }
        conn = await self._get_conn()
        cursor = await conn.execute(
            "SELECT id, session_id, role, content, timestamp, metadata FROM conversations ORDER BY timestamp ASC"
        )
        rows = await cursor.fetchall()
        await cursor.close()
        for r in rows:
            data["conversations"].append(
                {
                    "id": r[0],
                    "session_id": r[1],
                    "role": r[2],
                    "content": r[3],
                    "timestamp": r[4],
                    "metadata": json.loads(r[5]) if r[5] else {},
                }
            )
        blob = json.dumps(data, indent=2, default=str)
        Path(path).write_text(blob, encoding="utf-8")
        return path

    async def export_to_markdown(self, directory: str) -> str:
        base = Path(directory)
        base.mkdir(parents=True, exist_ok=True)
        conn = await self._get_conn()
        cursor = await conn.execute(
            "SELECT id, session_id, role, content, timestamp FROM conversations ORDER BY timestamp ASC"
        )
        rows = await cursor.fetchall()
        await cursor.close()
        lines = ["# JARVIS Memory Export\n\n## Conversations\n\n"]
        for r in rows:
            lines.append(f"### {r[2].title()} — {r[4]}\n{r[3]}\n\n")
        projects = await self.list_projects()
        if projects:
            lines.append("## Projects\n\n")
            for p in projects:
                lines.append(
                    f"### {p['name']}\n- Path: {p.get('path', '')}\n- Tech: {p.get('tech_stack', '')}\n- {p.get('description', '')}\n\n"
                )
        tasks = await self.list_tasks()
        if tasks:
            lines.append("## Tasks\n\n")
            for t in tasks:
                lines.append(f"- [ ] {t['title']} ({t['status']}, {t['priority']})\n")
        knowledge = await self.list_knowledge()
        if knowledge:
            lines.append("## Knowledge\n\n")
            for k in knowledge:
                lines.append(f"### {k['type']} — {k.get('source', '')}\n{k['content']}\n\n")
        out = "".join(lines)
        (base / "memory_export.md").write_text(out, encoding="utf-8")
        return str(base / "memory_export.md")

    # --- Clear / Wipe --------------------------------------------------------
    async def clear(self, confirm: bool = False) -> bool:
        if not confirm:
            raise ValueError("confirm=True is required to clear memory")
        conn = await self._get_conn()
        await conn.execute("DELETE FROM conversations")
        await conn.execute("DELETE FROM conversations_fts")
        await conn.execute("DELETE FROM sessions")
        await conn.execute("DELETE FROM projects")
        await conn.execute("DELETE FROM projects_fts")
        await conn.execute("DELETE FROM tasks")
        await conn.execute("DELETE FROM tasks_fts")
        await conn.execute("DELETE FROM knowledge")
        await conn.execute("DELETE FROM knowledge_fts")
        await conn.execute("DELETE FROM preferences")
        await conn.execute("DELETE FROM mail_sessions")
        await conn.execute("DELETE FROM audit_log")
        await conn.execute("DELETE FROM behavior_patterns")
        await conn.execute("DELETE FROM learning_feedback")
        await conn.commit()
        return True

    # --- Learning --------------------------------------------------------------
    async def record_pattern(
        self, pattern_type: str, trigger: str, action: str, confidence: float = 1.0
    ) -> dict:
        conn = await self._get_conn()
        pattern_id = str(uuid.uuid4())
        await conn.execute(
            "INSERT INTO behavior_patterns (id, pattern_type, trigger, action, confidence) VALUES (?, ?, ?, ?, ?)",
            (pattern_id, pattern_type, trigger, action, confidence),
        )
        await conn.commit()
        return {
            "id": pattern_id,
            "pattern_type": pattern_type,
            "trigger": trigger,
            "action": action,
        }

    async def get_patterns(self, pattern_type: str | None = None, limit: int = 50) -> list[dict]:
        conn = await self._get_conn()
        query = "SELECT id, pattern_type, trigger, action, confidence, occurrences, last_occurrence FROM behavior_patterns WHERE 1=1"
        params: list[Any] = []
        if pattern_type:
            query += " AND pattern_type = ?"
            params.append(pattern_type)
        query += " ORDER BY confidence DESC, last_occurrence DESC LIMIT ?"
        params.append(limit)
        cursor = await conn.execute(query, params)
        rows = await cursor.fetchall()
        await cursor.close()
        return [
            {
                "id": r[0],
                "pattern_type": r[1],
                "trigger": r[2],
                "action": r[3],
                "confidence": r[4],
                "occurrences": r[5],
                "last_occurrence": r[6],
            }
            for r in rows
        ]

    async def record_feedback(
        self, session_id: str, prediction: str, actual: str, correct: bool
    ) -> dict:
        conn = await self._get_conn()
        feedback_id = str(uuid.uuid4())
        await conn.execute(
            "INSERT INTO learning_feedback (id, session_id, prediction, actual, correct) VALUES (?, ?, ?, ?, ?)",
            (feedback_id, session_id, prediction, actual, 1 if correct else 0),
        )
        await conn.commit()
        return {
            "id": feedback_id,
            "session_id": session_id,
            "prediction": prediction,
            "actual": actual,
            "correct": correct,
        }

    async def get_feedback_stats(self, limit: int = 100) -> dict:
        conn = await self._get_conn()
        cursor = await conn.execute(
            "SELECT prediction, actual, correct FROM learning_feedback ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        await cursor.close()
        total = len(rows)
        correct = sum(1 for r in rows if r[2])
        accuracy = correct / total if total else 0.0
        return {"total": total, "correct": correct, "accuracy": accuracy}

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
