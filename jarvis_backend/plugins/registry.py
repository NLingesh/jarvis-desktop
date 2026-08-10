"""Plugin registry with enable/disable, permission gating, and intent routing."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from plugins.base import BasePlugin

logger = logging.getLogger(__name__)


class PluginRegistry:
    """Central registry for JARVIS plugins.

    Manages plugin lifecycle, intent routing, and tool dispatch.
    """

    def __init__(self):
        self._plugins: dict[str, BasePlugin] = {}
        self._intent_map: dict[str, str] = {}
        self._tool_map: dict[str, str] = {}
        self._loaded_paths: set[str] = set()

    def register(self, plugin: BasePlugin) -> None:
        """Register a plugin instance."""
        name = plugin.name
        if name in self._plugins:
            raise ValueError(f"Plugin {name} is already registered")
        self._plugins[name] = plugin
        for intent in plugin.intents:
            self._intent_map[intent.lower()] = name
        for tool in plugin.tools:
            self._tool_map[tool] = name
        logger.info("Registered plugin: %s v%s", name, plugin.version)

    def unregister(self, name: str) -> None:
        """Unregister a plugin by name."""
        plugin = self._plugins.pop(name, None)
        if plugin is None:
            return
        self._intent_map = {k: v for k, v in self._intent_map.items() if v != name}
        self._tool_map = {k: v for k, v in self._tool_map.items() if v != name}
        logger.info("Unregistered plugin: %s", name)

    def get(self, name: str) -> BasePlugin | None:
        return self._plugins.get(name)

    def list_plugins(self) -> list[dict[str, Any]]:
        result = []
        for plugin in self._plugins.values():
            result.append(
                {
                    "name": plugin.name,
                    "version": plugin.version,
                    "description": plugin.manifest.description,
                    "permissions": plugin.permissions,
                    "tools": plugin.tools,
                    "intents": plugin.intents,
                    "enabled": plugin.enabled,
                }
            )
        return result

    def detect_intents(self, user_input: str) -> list[str]:
        """Return plugin names whose intents match the user input."""
        lower = user_input.lower()
        matches = []
        for intent, plugin_name in self._intent_map.items():
            if intent in lower:
                matches.append(plugin_name)
        return list(dict.fromkeys(matches))

    async def execute_intents(
        self, user_input: str, session_id: str | None = None
    ) -> dict[str, Any]:
        """Run matched plugin intents and merge results."""
        plugin_names = self.detect_intents(user_input)
        if not plugin_names:
            return {}

        merged: dict[str, Any] = {}
        for name in plugin_names:
            plugin = self._plugins.get(name)
            if not plugin or not plugin.enabled:
                continue
            try:
                result = await plugin.handle_intent(name, user_input, session_id)
                merged[name] = result
            except Exception as e:
                logger.error("Plugin %s intent failed: %s", name, e)
                merged[name] = {"error": str(e)}
        return merged

    async def execute_tool(
        self, tool_name: str, payload: dict[str, Any], permissions: Callable[[str], bool]
    ) -> dict[str, Any]:
        """Execute a tool with permission check."""
        plugin_name = self._tool_map.get(tool_name)
        if not plugin_name:
            raise ValueError(f"Unknown tool: {tool_name}")
        plugin = self._plugins.get(plugin_name)
        if not plugin or not plugin.enabled:
            raise ValueError(f"Plugin {plugin_name} is not available")
        for perm in plugin.permissions:
            if not permissions(perm):
                raise PermissionError(f"Permission denied: {perm} for tool {tool_name}")
        return await plugin.execute_tool(tool_name, payload)

    async def load_plugin(self, plugin_class: type[BasePlugin]) -> BasePlugin:
        """Instantiate, setup, and register a plugin class."""
        plugin = plugin_class()
        await plugin.setup()
        self.register(plugin)
        return plugin

    async def unload_plugin(self, name: str) -> None:
        """Teardown and unregister a plugin."""
        plugin = self._plugins.get(name)
        if plugin:
            await plugin.teardown()
            self.unregister(name)

    async def shutdown(self) -> None:
        """Teardown all plugins."""
        for name in list(self._plugins.keys()):
            await self.unload_plugin(name)
