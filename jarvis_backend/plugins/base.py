"""Plugin base class and manifest definitions."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class PluginManifest:
    """Declarative plugin metadata."""

    name: str
    version: str = "1.0.0"
    description: str = ""
    author: str = ""
    permissions: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    settings: list[dict] = field(default_factory=list)
    intents: list[str] = field(default_factory=list)
    enabled: bool = True


class BasePlugin:
    """Abstract base class for all JARVIS plugins.

    Plugins must implement the manifest property and can optionally
    implement setup/teardown lifecycle hooks and intent handlers.
    """

    manifest: PluginManifest

    def __init__(self):
        self._enabled = True
        self._settings: dict[str, Any] = {}

    @property
    def name(self) -> str:
        return self.manifest.name

    @property
    def version(self) -> str:
        return self.manifest.version

    @property
    def permissions(self) -> list[str]:
        return list(self.manifest.permissions)

    @property
    def tools(self) -> list[str]:
        return list(self.manifest.tools)

    @property
    def intents(self) -> list[str]:
        return list(self.manifest.intents)

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value

    def get_setting(self, key: str, default: Any = None) -> Any:
        return self._settings.get(key, default)

    def set_setting(self, key: str, value: Any) -> None:
        self._settings[key] = value

    async def setup(self) -> None:
        """Called when the plugin is loaded. Override to initialize resources."""
        return None

    async def teardown(self) -> None:
        """Called when the plugin is unloaded. Override to clean up resources."""
        return None

    async def handle_intent(
        self, intent: str, user_input: str, session_id: str | None = None
    ) -> dict[str, Any]:
        """Handle a detected intent. Override to implement intent routing."""
        return {}

    async def execute_tool(self, tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Execute a tool provided by this plugin."""
        raise NotImplementedError(f"Tool {tool_name} not implemented in {self.name}")

    def __repr__(self) -> str:
        return f"<Plugin {self.name} v{self.version} enabled={self._enabled}>"
