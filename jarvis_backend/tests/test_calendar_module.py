"""Tests for CalendarModule — mock events, availability, and khal parsing."""

import asyncio
from datetime import datetime, timedelta

from modules.calendar_module import CalendarModule


def run(coro):
    return asyncio.run(coro)


def make_module():
    module = CalendarModule()
    # Force the no-app fallback path so tests don't depend on installed tools.
    module.calendar_app = None
    return module


def test_detect_calendar_app_returns_none_when_missing(monkeypatch):
    monkeypatch.setattr(
        "modules.calendar_module.subprocess.run",
        lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError),
    )
    module = CalendarModule()
    assert module.calendar_app is None


def test_mock_events_are_in_future():
    module = make_module()
    events = module._get_mock_events(7)
    assert len(events) == 4
    for event in events:
        assert datetime.fromisoformat(event["start"]) > datetime.now()
        assert datetime.fromisoformat(event["end"]) > datetime.fromisoformat(event["start"])


def test_get_upcoming_events_falls_back_to_mock(tmp_path, monkeypatch):
    module = make_module()
    events = run(module.get_upcoming_events())
    assert len(events) == 4


def test_create_event_returns_true():
    module = make_module()
    assert (
        run(
            module.create_event(
                "Standup",
                datetime.now(),
                datetime.now() + timedelta(hours=1),
            )
        )
        is True
    )


def test_check_availability_no_overlap(monkeypatch):
    module = make_module()
    future = datetime.now() + timedelta(days=1)
    events = [{"start": future.isoformat(), "end": (future + timedelta(hours=1)).isoformat()}]

    async def fake_events():
        return events

    monkeypatch.setattr(module, "get_upcoming_events", fake_events)
    assert (
        run(module.check_availability(future + timedelta(hours=2), future + timedelta(hours=3)))
        is True
    )


def test_check_availability_with_overlap(monkeypatch):
    module = make_module()
    future = datetime.now() + timedelta(days=1)
    events = [{"start": future.isoformat(), "end": (future + timedelta(hours=1)).isoformat()}]

    async def fake_events():
        return events

    monkeypatch.setattr(module, "get_upcoming_events", fake_events)
    assert (
        run(module.check_availability(future + timedelta(minutes=30), future + timedelta(hours=2)))
        is False
    )


def test_find_available_slot_returns_slot(monkeypatch):
    module = make_module()

    async def fake_availability(start, end):
        return True

    monkeypatch.setattr(module, "check_availability", fake_availability)
    slot = run(module.find_available_slot(duration_minutes=30, days_ahead=3))
    assert slot is not None
    assert slot["duration_minutes"] == 30
    assert datetime.fromisoformat(slot["end"]) > datetime.fromisoformat(slot["start"])


def test_khal_parses_lines(monkeypatch):
    module = make_module()
    result = type(
        "Result",
        (),
        {"returncode": 0, "stdout": "2026-08-07 09:00 → 09:30 Kickoff\n", "stderr": ""},
    )()

    def fake_run(*args, **kwargs):
        return result

    monkeypatch.setattr("modules.calendar_module.subprocess.run", fake_run)
    events = run(module._get_khal_events(1))
    assert len(events) == 1
    assert events[0]["title"] == "Kickoff"


def test_khal_ignores_bad_lines(monkeypatch):
    module = make_module()
    result = type(
        "Result", (), {"returncode": 0, "stdout": "# comment\nnot a date line\n", "stderr": ""}
    )()

    def fake_run(*args, **kwargs):
        return result

    monkeypatch.setattr("modules.calendar_module.subprocess.run", fake_run)
    assert run(module._get_khal_events(1)) == []


def test_khal_nonzero_exit_returns_empty(monkeypatch):
    module = make_module()
    result = type("Result", (), {"returncode": 1, "stdout": "", "stderr": "boom"})()

    def fake_run(*args, **kwargs):
        return result

    monkeypatch.setattr("modules.calendar_module.subprocess.run", fake_run)
    assert run(module._get_khal_events(1)) == []
