"""Dynamic plugin loader for JARVIS plugins."""

from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path

from plugins.base import BasePlugin

logger = logging.getLogger(__name__)


class PluginLoader:
    """Loads plugins from Python files and packages."""

    def __init__(self, plugin_dirs: list[Path] | None = None):
        self.plugin_dirs = plugin_dirs or [Path(__file__).parent / "builtin"]
        self._loaded_paths: set[Path] = set()

    def discover(self) -> list[type[BasePlugin]]:
        """Discover all plugin classes in plugin directories."""
        discovered: list[type[BasePlugin]] = []
        for directory in self.plugin_dirs:
            if not directory.exists():
                continue
            for path in directory.rglob("*.py"):
                if path.name.startswith("_") or path.name == "base.py":
                    continue
                try:
                    cls = self._load_class_from_path(path)
                    if cls is not None and issubclass(cls, BasePlugin) and cls is not BasePlugin:
                        discovered.append(cls)
                        self._loaded_paths.add(path)
                except Exception as e:
                    logger.warning("Failed to load plugin from %s: %s", path, e)
        return discovered

    def _load_class_from_path(self, path: Path) -> type[BasePlugin] | None:
        """Import a Python file and return the first BasePlugin subclass."""
        module_name = f"_jarvis_plugin_{path.stem}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        for attr in dir(module):
            obj = getattr(module, attr)
            if isinstance(obj, type) and issubclass(obj, BasePlugin) and obj is not BasePlugin:
                return obj
        return None

    async def load_all(self, registry) -> list[BasePlugin]:
        """Discover and load all plugins into the registry."""
        loaded = []
        for plugin_cls in self.discover():
            try:
                plugin = await registry.load_plugin(plugin_cls)
                loaded.append(plugin)
            except Exception as e:
                logger.error("Failed to load plugin %s: %s", plugin_cls.__name__, e)
        return loaded
