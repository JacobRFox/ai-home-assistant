"""The interface every smart-home backend implements.

Backends report devices in one normalized shape so the tools, API, dashboard and
chat commands work the same for every hub:

    {
      "id": str, "name": str, "room": str | None, "reachable": bool,
      "type": "light" | "switch" | "cover" | "fan" | "climate" | "lock" | "sensor",
      "on": bool,                 # on / open / locked / running
      "brightness": int,          # light, 0-100
      "position": int,            # cover, 0 = closed, 100 = fully open
      "target_temp": float,       # climate
      "readings": dict,           # sensor values, e.g. {"temperature": 21.5}
    }
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable

from home_assistant.plugins import PluginError


def label(device: dict[str, Any]) -> str:
    """Human-readable name, including the room unless the name already says it."""
    room = device.get("room")
    return f"{device['name']} ({room})" if room and room.lower() not in device["name"].lower() else device["name"]


def _match(query: str, items: list[dict[str, Any]], kind: str) -> dict[str, Any]:
    """Find exactly one item by id, name, or "room name", tolerating partial names."""
    q = " ".join(query.lower().split())
    if not q:
        raise PluginError(f"Which {kind}?")

    def keys(item: dict[str, Any]) -> list[str]:
        name = item["name"].lower()
        room = (item.get("room") or "").lower()
        return [item["id"].lower(), name, f"{room} {name}".strip(), f"{name} {room}".strip()]

    exact = [i for i in items if q in keys(i)]
    if len(exact) == 1:
        return exact[0]
    words = q.split()
    partial = exact or [i for i in items if any(q in k for k in keys(i)) or all(w in keys(i)[2] for w in words)]
    if len(partial) == 1:
        return partial[0]
    if not partial:
        raise PluginError(f"No {kind} matches '{query}'.")
    raise PluginError(f"'{query}' is ambiguous; it matches: {', '.join(label(i) for i in partial)}.")


class SmartHomeBackend(ABC):
    @abstractmethod
    def list_devices(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    def set_power(self, device: str, on: bool) -> str: ...

    # Optional features: backends override what their hub supports.
    def set_brightness(self, device: str, percent: int) -> str:
        raise PluginError("This hub doesn't support brightness control.")

    def set_temperature(self, device: str, temperature: float) -> str:
        raise PluginError("This hub doesn't support thermostats.")

    def set_position(self, device: str, percent: int) -> str:
        raise PluginError("This hub doesn't support blinds.")

    def list_scenes(self) -> list[dict[str, Any]]:
        """[{"id": str, "name": str}]"""
        return []

    def trigger_scene(self, scene: str) -> str:
        raise PluginError("This hub has no scenes.")

    def start(self, on_change: Callable[[], None]) -> None:
        """Begin pushing updates: call `on_change()` when devices change outside this app."""

    def stop(self) -> None:
        """Stop background work started by `start()`."""

    # Helpers
    def find(self, device: str) -> dict[str, Any]:
        return _match(device, self.list_devices(), "device")

    def find_scene(self, scene: str) -> dict[str, Any]:
        scenes = self.list_scenes()
        if not scenes:
            raise PluginError("There are no scenes set up.")
        return _match(scene, scenes, "scene")
