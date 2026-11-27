"""Smart-home backends. Pick one with plugins.smart_home.backend in config.yaml."""

from __future__ import annotations

from typing import Any

from home_assistant.plugins import PluginError

from .base import SmartHomeBackend, label


def make_backend(cfg: dict[str, Any]) -> SmartHomeBackend:
    """`cfg` is the plugin's config section (plugins.smart_home)."""
    backend = cfg.get("backend", "simulated")
    if backend == "simulated":
        from .simulated import SimulatedBackend
        return SimulatedBackend()
    if backend == "homeassistant":
        from .homeassistant import HomeAssistantBackend
        ha = cfg.get("homeassistant") or {}
        return HomeAssistantBackend(ha.get("url", ""), ha.get("token", ""))
    if backend == "dirigera":
        from .dirigera import DirigeraBackend
        dg = cfg.get("dirigera") or {}
        return DirigeraBackend(dg.get("host", ""), dg.get("token", ""), dg.get("include_sensors", True))
    raise PluginError(f"Unknown smart_home backend {backend!r}. Use simulated, homeassistant or dirigera.")


__all__ = ["SmartHomeBackend", "label", "make_backend"]
