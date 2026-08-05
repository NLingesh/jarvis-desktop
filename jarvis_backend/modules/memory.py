import json
import uuid
import secrets
from datetime import datetime
from typing import List, Dict, Optional
import sqlite3

class MemoryManager:
    def __init__(self, db_path: str = "jarvis_memory.db"):
        self.db_path = db_path
        self.init_db()
        self.current_sessions = {}
    
    def init_db(self):
        """Initialize SQLite database with FTS5 for full-text search"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Create conversations table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                session_id TEXT,
                role TEXT,
                content TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                metadata TEXT
            )
        """)
        
        # Create FTS5 virtual table for search
        cursor.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS conversations_fts USING fts5(
                content,
                role,
                session_id
            )
        """)
        
        # Create sessions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_active DATETIME DEFAULT CURRENT_TIMESTAMP,
                metadata TEXT
            )
        """)
        
        # Create notes table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS notes (
                id TEXT PRIMARY KEY,
                session_id TEXT,
                title TEXT,
                content TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                tags TEXT
            )
        """)

        # Create mail_sessions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS mail_sessions (
                token TEXT PRIMARY KEY,
                email_address TEXT NOT NULL,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                expires_at DATETIME NOT NULL
            )
        """)

        conn.commit()
        conn.close()
    
    def create_session(self) -> str:
        """Create a new session"""
        session_id = str(uuid.uuid4())
        self.current_sessions[session_id] = {
            "created_at": datetime.now(),
            "messages": []
        }
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO sessions (id) VALUES (?)",
            (session_id,)
        )
        conn.commit()
        conn.close()
        
        return session_id
    
    def add_message(self, session_id: str, role: str, content: str, metadata: Optional[dict] = None):
        """Add message to conversation"""
        msg_id = str(uuid.uuid4())
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Insert into conversations table
        cursor.execute("""
            INSERT INTO conversations (id, session_id, role, content, metadata)
            VALUES (?, ?, ?, ?, ?)
        """, (msg_id, session_id, role, content, json.dumps(metadata or {})))
        
        # Insert into FTS5 for search
        cursor.execute("""
            INSERT INTO conversations_fts (content, role, session_id)
            VALUES (?, ?, ?)
        """, (content, role, session_id))
        
        # Update session last_active
        cursor.execute(
            "UPDATE sessions SET last_active = CURRENT_TIMESTAMP WHERE id = ?",
            (session_id,)
        )
        
        conn.commit()
        conn.close()
        
        # Store in memory for quick access
        if session_id in self.current_sessions:
            self.current_sessions[session_id]["messages"].append({
                "id": msg_id,
                "role": role,
                "content": content,
                "timestamp": datetime.now()
            })
    
    def get_conversation(self, session_id: str, limit: int = 20) -> List[Dict]:
        """Get conversation history for a session"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT role, content FROM conversations
            WHERE session_id = ?
            ORDER BY timestamp DESC
            LIMIT ?
        """, (session_id, limit))
        
        messages = []
        for role, content in reversed(cursor.fetchall()):
            messages.append({"role": role, "content": content})
        
        conn.close()
        return messages
    
    def search_memory(self, query: str, session_id: Optional[str] = None) -> List[Dict]:
        """Full-text search across conversations"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        if session_id:
            cursor.execute("""
                SELECT content, role, session_id FROM conversations_fts
                WHERE conversations_fts MATCH ?
                AND session_id = ?
                LIMIT 10
            """, (query, session_id))
        else:
            cursor.execute("""
                SELECT content, role, session_id FROM conversations_fts
                WHERE conversations_fts MATCH ?
                LIMIT 10
            """, (query,))
        
        results = []
        for content, role, sid in cursor.fetchall():
            results.append({
                "content": content,
                "role": role,
                "session_id": sid
            })
        
        conn.close()
        return results
    
    def create_note(self, session_id: str, title: str, content: str, tags: Optional[List[str]] = None) -> str:
        """Create and store a note"""
        note_id = str(uuid.uuid4())
        
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO notes (id, session_id, title, content, tags)
            VALUES (?, ?, ?, ?, ?)
        """, (note_id, session_id, title, content, json.dumps(tags or [])))
        
        conn.commit()
        conn.close()
        
        return note_id
    
    def get_notes(self, session_id: str) -> List[Dict]:
        """Get all notes for a session"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, title, content, tags, created_at FROM notes
            WHERE session_id = ?
            ORDER BY created_at DESC
        """, (session_id,))
        
        notes = []
        for note_id, title, content, tags, created_at in cursor.fetchall():
            notes.append({
                "id": note_id,
                "title": title,
                "content": content,
                "tags": json.loads(tags),
                "created_at": created_at
            })
        
        conn.close()
        return notes
    
    def load_history(self):
        """Load conversation history from database"""
        pass  # Already handled by SQLite
    
    def save_history(self):
        """Save conversation history (already persisted to SQLite)"""
        pass

    def create_mail_session(self, email_address: str, ttl_hours: int = 24) -> str:
        """Create a new mail session token."""
        token = secrets.token_urlsafe(32)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO mail_sessions (token, email_address, expires_at) VALUES (?, ?, datetime('now', ?))",
            (token, email_address, f"+{ttl_hours} hours"),
        )
        conn.commit()
        conn.close()
        return token

    def get_mail_session(self, token: str) -> Optional[str]:
        """Get email address for a valid mail session token, or None if missing/expired."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT email_address FROM mail_sessions WHERE token = ? AND expires_at > datetime('now')",
            (token,),
        )
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else None

    def cleanup_expired_mail_sessions(self) -> None:
        """Remove expired mail sessions."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM mail_sessions WHERE expires_at <= datetime('now')")
        conn.commit()
        conn.close()
