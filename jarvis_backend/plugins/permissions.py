"""Permission management for plugins."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class PluginPermission:
    """Granular permission grant for a plugin."""

    name: str
    granted: bool = False
    granted_at: str | None = None
    granted_by: str = "user"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "granted": self.granted,
            "granted_at": self.granted_at,
            "granted_by": self.granted_by,
        }


class PermissionManager:
    """Manages permission grants for plugins."""

    def __init__(self):
        self._grants: dict[str, dict[str, PluginPermission]] = {}

    def grant(self, plugin_name: str, permission_name: str, granted_by: str = "user") -> None:
        if plugin_name not in self._grants:
            self._grants[plugin_name] = {}
        self._grants[plugin_name][permission_name] = PluginPermission(
            name=permission_name,
            granted=True,
            granted_by=granted_by,
        )
        logger.info("Granted %s to %s", permission_name, plugin_name)

    def revoke(self, plugin_name: str, permission_name: str) -> None:
        if plugin_name in self._grants:
            self._grants[plugin_name].pop(permission_name, None)
            if not self._grants[plugin_name]:
                del self._grants[plugin_name]

    def has_permission(self, plugin_name: str, permission_name: str) -> bool:
        return (
            self._grants.get(plugin_name, {})
            .get(permission_name, PluginPermission(name=permission_name))
            .granted
        )

    def get_plugin_permissions(self, plugin_name: str) -> list[dict[str, Any]]:
        return [p.to_dict() for p in self._grants.get(plugin_name, {}).values()]

    def list_all_grants(self) -> dict[str, list[dict[str, Any]]]:
        return {name: self.get_plugin_permissions(name) for name in self._grants}
