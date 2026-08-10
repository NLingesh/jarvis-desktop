import asyncio
import sqlite3

from managers.memory_manager import MemoryManager


def make_manager(tmp_path):
    return MemoryManager(db_path=str(tmp_path / "test_memory.db"))


def run(mm, coro):
    async def wrapped():
        try:
            return await coro
        finally:
            await mm.close()
            await asyncio.sleep(0.02)

    return asyncio.run(wrapped())


def test_mail_session_creation(tmp_path):
    mm = make_manager(tmp_path)

    async def scenario():
        token = await mm.create_mail_session("user@example.com")
        assert token
        assert await mm.get_mail_session(token) == "user@example.com"

    run(mm, scenario())


def test_invalid_token_returns_none(tmp_path):
    mm = make_manager(tmp_path)

    async def scenario():
        assert await mm.get_mail_session("does-not-exist") is None

    run(mm, scenario())


def _insert_expired_session(mm, token, email):
    conn = sqlite3.connect(mm.db_path)
    try:
        conn.execute(
            "INSERT INTO mail_sessions (token, email_address, expires_at) "
            "VALUES (?, ?, datetime('now', '-1 day'))",
            (token, email),
        )
        conn.commit()
    finally:
        conn.close()


def test_expired_mail_session_is_filtered_out(tmp_path):
    mm = make_manager(tmp_path)

    async def scenario():
        # Bootstrap the schema within this loop, then insert an expired row.
        await mm.create_mail_session("bootstrap@example.com")
        _insert_expired_session(mm, "expired-token", "old@example.com")
        assert await mm.get_mail_session("expired-token") is None

    run(mm, scenario())


def test_cleanup_removes_only_expired_sessions(tmp_path):
    mm = make_manager(tmp_path)

    async def scenario():
        fresh = await mm.create_mail_session("fresh@example.com")
        _insert_expired_session(mm, "expired-token", "old@example.com")

        await mm.cleanup_expired_mail_sessions()

        assert await mm.get_mail_session(fresh) == "fresh@example.com"
        assert await mm.get_mail_session("expired-token") is None

        conn = sqlite3.connect(mm.db_path)
        try:
            remaining = conn.execute("SELECT COUNT(*) FROM mail_sessions").fetchone()[0]
        finally:
            conn.close()
        assert remaining == 1

    run(mm, scenario())


def test_add_and_get_conversation(tmp_path):
    mm = make_manager(tmp_path)

    async def scenario():
        session_id = await mm.create_session()
        await mm.add_message(session_id, "user", "hello")
        await mm.add_message(session_id, "assistant", "hi there")
        conv = await mm.get_conversation(session_id)
        assert [m["role"] for m in conv] == ["user", "assistant"]
        assert conv[-1]["content"] == "hi there"

    run(mm, scenario())


def test_search_memory_handles_special_characters(tmp_path):
    mm = make_manager(tmp_path)

    async def scenario():
        session_id = await mm.create_session()
        await mm.add_message(session_id, "user", "Remind me about the project deadline.")
        results = await mm.search_memory("project?", session_id=session_id)
        assert len(results) >= 1
        assert "project" in results[0]["content"]

    run(mm, scenario())
