"""Tests for the proactive monitor and the profile/remember commands."""

from datetime import datetime, timedelta

import pytest

import routes.state as state
from modules.proactive import ProactiveMonitor


class FakeCalendar:
    def __init__(self, events):
        self.events = events

    async def get_upcoming_events(self, days_ahead=7):
        return self.events


class FakeMailSessions:
    def __init__(self, session=None):
        self.session = session

    async def most_recent(self):
        return self.session


class FakeMailSession:
    def __init__(self, unread):
        self.unread = unread

    async def get_unread_emails(self, limit=10):
        return self.unread


class FakeVault:
    def __init__(self):
        self.notes: dict[str, str] = {}
        self.store = self

    def exists(self, path):
        return path in self.notes

    async def get_note(self, path):
        if path not in self.notes:
            raise FileNotFoundError(path)
        return {"body": self.notes[path]}

    async def create_note(self, **kwargs):
        path = f"{kwargs['folder']}/{kwargs['title']}.md"
        self.notes[path] = kwargs["content"]
        return {"body": kwargs["content"]}

    async def update_note(self, path, content=None, **kwargs):
        if content is not None:
            self.notes[path] = content
        return {"body": self.notes.get(path, "")}


def iso_offset(hours: float) -> str:
    return (datetime.now() + timedelta(hours=hours)).isoformat()


@pytest.fixture
def fake_vault(monkeypatch):
    fake = FakeVault()
    monkeypatch.setattr(state, "vault", fake)
    return fake


# --- ProactiveMonitor --------------------------------------------------------


async def test_proactive_summarizes_upcoming_event():
    cal = FakeCalendar([{"title": "Team Standup", "start": iso_offset(0.25)}])
    monitor = ProactiveMonitor(cal, FakeMailSessions(), lookahead_minutes=30)
    text = await monitor.check_once()
    assert "Team Standup" in text


async def test_proactive_ignores_distant_events():
    cal = FakeCalendar([{"title": "Project Planning", "start": iso_offset(3)}])
    monitor = ProactiveMonitor(cal, FakeMailSessions(), lookahead_minutes=30)
    assert await monitor.check_once() is None


async def test_proactive_deduplicates_events():
    cal = FakeCalendar([{"title": "Standup", "start": iso_offset(0.25)}])
    monitor = ProactiveMonitor(cal, FakeMailSessions(), lookahead_minutes=30)
    assert await monitor.check_once() is not None
    assert await monitor.check_once() is None


async def test_proactive_reports_unread_mail():
    session = FakeMailSession(
        [
            {"id": "1", "from": "a@b.c", "subject": "Hi"},
            {"id": "2", "from": "d@e.f", "subject": "Yo"},
        ]
    )
    monitor = ProactiveMonitor(FakeCalendar([]), FakeMailSessions(session), lookahead_minutes=30)
    text = await monitor.check_once()
    assert "2 unread emails" in text
    assert await monitor.check_once() is None


async def test_proactive_no_findings_returns_none():
    monitor = ProactiveMonitor(FakeCalendar([]), FakeMailSessions(), lookahead_minutes=30)
    assert await monitor.check_once() is None


# --- remember / forget / profile ---------------------------------------------
#
# Memory writes are owned exclusively by the typed tool pipeline
# (remember_memory / clear_all_memories with secret filtering, dedup,
# retention, and single-use approval).  The legacy context builder must not
# persist anything directly.


async def test_process_command_does_not_write_memory(fake_vault):
    await state.process_command("remember that I like dark mode")
    # No direct write: the orchestrator's remember flow owns persistence.
    assert "dark mode" not in fake_vault.notes.get("People/Me.md", "")


async def test_what_do_you_know_about_me_reads_profile(fake_vault):
    fake_vault.notes["People/Me.md"] = "## About\n- my name is Wiz"
    ctx = await state.process_command("what do you know about me")
    assert ctx["profile"]["action"] == "read"
    assert "Wiz" in ctx["profile"]["content"]


async def test_profile_reset_requires_confirmation_not_direct_write(fake_vault):
    fake_vault.notes["People/Me.md"] = "## About\n- my name is Wiz"
    await state.process_command("forget my profile")
    # Destructive clears are gated behind clear_all_memories approval; the
    # legacy context builder must never wipe on a bare phrase.
    assert "my name is Wiz" in fake_vault.notes["People/Me.md"]
