"""Discovers, loads and aggregates plugins."""

from __future__ import annotations

import importlib
import importlib.metadata
import importlib.util
import logging
import pkgutil
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

from langchain_core.tools import BaseTool

from ..config import PROJECT_ROOT
from ..events import EventBus
from ..storage import JsonStore
from .base import Command, Plugin, PluginContext

log = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "home_assistant.plugins"


def _plugin_class(module: ModuleType, source: str) -> type[Plugin]:
    cls = getattr(module, "plugin", None)
    if not (isinstance(cls, type) and issubclass(cls, Plugin)):
        raise TypeError(f"{source} must define `plugin = <Plugin subclass>`")
    if not getattr(cls, "id", None) or not getattr(cls, "name", None):
        raise TypeError(f"{source}: plugin class needs `id` and `name`")
    return cls


def _load_from_dir(path: Path) -> type[Plugin]:
    """Import a plugin package from an arbitrary folder (e.g. ./plugins/weather)."""
    module_name = f"home_assistant_ext.{path.name}"
    spec = importlib.util.spec_from_file_location(
        module_name, path / "__init__.py", submodule_search_locations=[str(path)]
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return _plugin_class(module, str(path))


def discover(cfg: dict[str, Any]) -> dict[str, type[Plugin]]:
    """Find plugins from three sources, in order of precedence (later wins):
    1. built-ins in home_assistant/builtin_plugins/
    2. pip-installed packages declaring the `home_assistant.plugins` entry point
    3. folders listed in plugins.paths (default: ./plugins)
    """
    found: dict[str, type[Plugin]] = {}

    def add(cls: type[Plugin], source: str) -> None:
        if cls.id in found:
            log.info("Plugin %r from %s overrides an earlier one", cls.id, source)
        found[cls.id] = cls

    from .. import builtin_plugins

    for info in pkgutil.iter_modules(builtin_plugins.__path__):
        name = f"{builtin_plugins.__name__}.{info.name}"
        try:
            add(_plugin_class(importlib.import_module(name), name), "built-in")
        except Exception:
            log.exception("Failed to import built-in plugin %s", name)

    for ep in importlib.metadata.entry_points(group=ENTRY_POINT_GROUP):
        try:
            cls = ep.load()
            if not (isinstance(cls, type) and issubclass(cls, Plugin)):
                raise TypeError("entry point must reference a Plugin subclass")
            add(cls, f"entry point {ep.name}")
        except Exception:
            log.exception("Failed to load plugin entry point %s", ep.name)

    for folder in cfg.get("plugins", {}).get("paths", ["plugins"]):
        root = Path(folder) if Path(folder).is_absolute() else PROJECT_ROOT / folder
        if not root.is_dir():
            continue
        for path in sorted(p for p in root.iterdir() if (p / "__init__.py").is_file()):
            try:
                add(_load_from_dir(path), str(path))
            except Exception:
                log.exception("Failed to load plugin from %s", path)
    return found


class PluginManager:
    def __init__(self, cfg: dict[str, Any], events: EventBus) -> None:
        self.cfg = cfg
        self.events = events
        self.plugins: dict[str, Plugin] = {}

    def load(self) -> None:
        plugin_cfg = self.cfg.get("plugins", {})
        enabled = plugin_cfg.get("enabled")  # None = everything discovered
        disabled = set(plugin_cfg.get("disabled") or [])
        available = discover(self.cfg)

        for missing in set(enabled or []) - set(available):
            log.warning("Enabled plugin %r was not found", missing)

        order = enabled if enabled is not None else sorted(available)
        for pid in order:
            if pid in disabled or pid not in available:
                continue
            cls = available[pid]
            ctx = PluginContext(
                plugin_id=pid,
                config=plugin_cfg.get(pid) or {},
                store=JsonStore(self.cfg["data_dir"] / f"{pid}.json"),
                events=self.events,
                log=logging.getLogger(f"plugin.{pid}"),
                app_config=self.cfg,
            )
            try:
                self.plugins[pid] = cls(ctx)
            except Exception:
                # One broken plugin shouldn't take the whole assistant down.
                log.exception("Plugin %r failed to start; skipping it", pid)
        log.info("Loaded plugins: %s", ", ".join(self.plugins) or "(none)")

    def get(self, plugin_id: str) -> Plugin | None:
        return self.plugins.get(plugin_id)

    def __iter__(self):
        return iter(self.plugins.values())

    def tools(self) -> list[BaseTool]:
        tools: list[BaseTool] = []
        owner: dict[str, str] = {}
        for p in self:
            for t in p.tools():
                if t.name in owner:
                    raise ValueError(f"Tool name {t.name!r} is defined by both {owner[t.name]!r} and {p.id!r}")
                owner[t.name] = p.id
                tools.append(t)
        return tools

    def prompts(self) -> str:
        parts = [f"## {p.name}\n{text.strip()}" for p in self if (text := p.prompt())]
        return "\n\n".join(parts)

    def commands(self) -> dict[str, Command]:
        merged: dict[str, Command] = {}
        for p in self:
            for name, cmd in p.commands().items():
                key = "/" + name.lstrip("/")
                if key in merged:
                    log.warning("Command %s from %r shadows an earlier plugin's", key, p.id)
                merged[key] = cmd
        return merged

    def shutdown(self) -> None:
        for p in self:
            try:
                p.shutdown()
            except Exception:
                log.exception("Plugin %r failed to shut down cleanly", p.id)
