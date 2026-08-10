"""Builtin JARVIS plugins migrated from the skill registry."""

from __future__ import annotations

import logging
import re
from typing import Any

from plugins.base import BasePlugin, PluginManifest
from routes.state import calendar, mail_sessions, notes, system_actions, web_browse

logger = logging.getLogger(__name__)


class CalendarPlugin(BasePlugin):
    manifest = PluginManifest(
        name="calendar",
        version="1.0.0",
        description="Calendar events and scheduling",
        permissions=["calendar.read"],
        tools=["get_upcoming_events"],
        intents=["calendar", "schedule", "meeting", "event"],
    )

    async def handle_intent(
        self, intent: str, user_input: str, session_id: str | None = None
    ) -> dict[str, Any]:
        return {"calendar": await calendar.get_upcoming_events()}


class EmailPlugin(BasePlugin):
    manifest = PluginManifest(
        name="email",
        version="1.0.0",
        description="Email reading and management",
        permissions=["email.read"],
        tools=["get_recent_emails"],
        intents=["email", "mail", "inbox", "message"],
    )

    async def handle_intent(
        self, intent: str, user_input: str, session_id: str | None = None
    ) -> dict[str, Any]:
        session = await mail_sessions.most_recent()
        if session is None:
            return {"emails": {"error": "No email session configured. Authenticate in Settings."}}
        return {"emails": await session.get_recent_emails(limit=5)}


class WebSearchPlugin(BasePlugin):
    manifest = PluginManifest(
        name="web_search",
        version="1.0.0",
        description="Web search and browsing",
        permissions=["web.search"],
        tools=["search"],
        intents=["search", "browse", "look up", "find", "what is"],
    )

    async def handle_intent(
        self, intent: str, user_input: str, session_id: str | None = None
    ) -> dict[str, Any]:
        return {"web_results": await web_browse.search(user_input)}


class WeatherPlugin(BasePlugin):
    manifest = PluginManifest(
        name="weather",
        version="1.0.0",
        description="Weather forecast and conditions",
        permissions=["web.search"],
        tools=["get_weather"],
        intents=["weather", "forecast", "temperature", "how is the"],
    )

    async def handle_intent(
        self, intent: str, user_input: str, session_id: str | None = None
    ) -> dict[str, Any]:
        location_match = re.search(
            r"(?:weather|forecast)\s+(?:in|for|at)\s+(.+)", user_input, re.IGNORECASE
        )
        location = location_match.group(1).strip() if location_match else "local"
        weather = await web_browse.get_weather(location)
        if weather is None:
            return {"weather": {"error": "Could not fetch weather."}}
        return {"weather": weather}


class TranslatePlugin(BasePlugin):
    manifest = PluginManifest(
        name="translate",
        version="1.0.0",
        description="Translate text to another language",
        permissions=["web.search"],
        tools=["translate_text"],
        intents=["translate"],
    )

    async def handle_intent(
        self, intent: str, user_input: str, session_id: str | None = None
    ) -> dict[str, Any]:
        match = re.search(r"translate\s+['\"](.+)['\"]\s+to\s+(\w+)", user_input, re.IGNORECASE)
        if not match:
            match = re.search(r"translate\s+(.+)\s+to\s+(\w+)$", user_input, re.IGNORECASE)
        if not match:
            return {"translate": {"error": "Usage: translate '<text>' to <language>"}}
        text, target = match.group(1).strip(), match.group(2).strip()
        translated = await web_browse.translate_text(text, target)
        if translated is None:
            return {"translate": {"error": "Translation failed."}}
        return {"translate": {"source": text, "target_language": target, "text": translated}}


class SystemPlugin(BasePlugin):
    manifest = PluginManifest(
        name="system",
        version="1.0.0",
        description="System information and status",
        permissions=["system.info"],
        tools=["get_system_info"],
        intents=["system", "status", "cpu", "memory", "disk"],
    )

    def handle_intent(
        self, intent: str, user_input: str, session_id: str | None = None
    ) -> dict[str, Any]:
        return {"system_info": system_actions.get_system_info()}


class NotesPlugin(BasePlugin):
    manifest = PluginManifest(
        name="notes",
        version="1.0.0",
        description="Note creation and organization",
        permissions=["notes.create"],
        tools=["create_note"],
        intents=[
            "remember",
            "note",
            "take a note",
            "create note",
            "save note",
            "write down",
            "jot down",
        ],
    )

    async def handle_intent(
        self, intent: str, user_input: str, session_id: str | None = None
    ) -> dict[str, Any]:
        note_match = re.search(
            r"(?:remember|note|take a note|create note|save note|write down|jot down)\s+(?:that\s+)?(.+)",
            user_input,
            re.IGNORECASE,
        )
        if note_match:
            note_text = note_match.group(1).strip()
            title = note_text[:60].strip() or "Note"
            note = await notes.create_note(title, note_text)
            return {
                "notes": (
                    {
                        "action": "created",
                        "note": note,
                    }
                    if note
                    else {"action": "failed", "error": "Could not save note"}
                )
            }
        return {"notes": {"action": "no_match"}}
