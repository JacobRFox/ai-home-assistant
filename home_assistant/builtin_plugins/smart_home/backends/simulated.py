"""In-memory demo devices, so everything works without any hardware."""

from __future__ import annotations

import copy
import threading
from typing import Any

from home_assistant.plugins import PluginError

from .base import SmartHomeBackend, label

DEVICES: list[dict[str, Any]] = [
    {"id": "light.living_room", "name": "Living Room Light", "room": "Living Room", "type": "light", "on": False, "brightness": 80},
    {"id": "light.kitchen", "name": "Kitchen Light", "room": "Kitchen", "type": "light", "on": True, "brightness": 100},
    {"id": "light.bedroom", "name": "Bedroom Lamp", "room": "Bedroom", "type": "light", "on": False, "brightness": 40},
    {"id": "cover.bedroom", "name": "Bedroom Blinds", "room": "Bedroom", "type": "cover", "on": True, "position": 100},
    {"id": "switch.coffee_maker", "name": "Coffee Maker", "room": "Kitchen", "type": "switch", "on": False},
    {"id": "climate.thermostat", "name": "Thermostat", "room": "Hallway", "type": "climate", "on": True, "target_temp": 21.0},
    {"id": "lock.front_door", "name": "Front Door Lock", "room": "Hallway", "type": "lock", "on": True},
    {"id": "sensor.living_room", "name": "Air Sensor", "room": "Living Room", "type": "sensor", "on": False,
     "readings": {"temperature": 21.4, "humidity": 45}},
]

# scene name -> {device id: changes}
SCENES: dict[str, dict[str, dict[str, Any]]] = {
    "Movie Night": {"light.living_room": {"on": True, "brightness": 20}, "light.kitchen": {"on": False},
                    "cover.bedroom": {"on": False, "position": 0}},
    "Good Morning": {"light.bedroom": {"on": True, "brightness": 60}, "cover.bedroom": {"on": True, "position": 100},
                     "switch.coffee_maker": {"on": True}},
    "Away": {"light.living_room": {"on": False}, "light.kitchen": {"on": False}, "light.bedroom": {"on": False},
             "switch.coffee_maker": {"on": False}, "lock.front_door": {"on": True}},
}


class SimulatedBackend(SmartHomeBackend):
    def __init__(self) -> None:
        self.devices = {d["id"]: copy.deepcopy(d) for d in DEVICES}
        self._lock = threading.Lock()

    def list_devices(self) -> list[dict[str, Any]]:
        with self._lock:
            return [{"reachable": True, **copy.deepcopy(d)} for d in self.devices.values()]

    def _device(self, device: str) -> dict[str, Any]:
        return self.devices[self.find(device)["id"]]

    def set_power(self, device: str, on: bool) -> str:
        d = self._device(device)
        if d["type"] == "sensor":
            raise PluginError(f"{label(d)} is a sensor and can't be switched.")
        with self._lock:
            d["on"] = on
            if d["type"] == "cover":
                d["position"] = 100 if on else 0
        words = {"lock": ("locked", "unlocked"), "cover": ("open", "closed")}.get(d["type"], ("on", "off"))
        return f"{label(d)} is now {words[0] if on else words[1]}."

    def set_brightness(self, device: str, percent: int) -> str:
        d = self._device(device)
        if d["type"] != "light":
            raise PluginError(f"{label(d)} is not a dimmable light.")
        with self._lock:
            d["brightness"] = max(0, min(100, percent))
            d["on"] = d["brightness"] > 0
        return f"{label(d)} brightness set to {d['brightness']}%."

    def set_temperature(self, device: str, temperature: float) -> str:
        d = self._device(device)
        if d["type"] != "climate":
            raise PluginError(f"{label(d)} is not a thermostat.")
        with self._lock:
            d["target_temp"] = temperature
        return f"{label(d)} target set to {temperature}°."

    def set_position(self, device: str, percent: int) -> str:
        d = self._device(device)
        if d["type"] != "cover":
            raise PluginError(f"{label(d)} is not a blind.")
        with self._lock:
            d["position"] = max(0, min(100, percent))
            d["on"] = d["position"] > 0
        return f"{label(d)} set to {d['position']}% open."

    def list_scenes(self) -> list[dict[str, Any]]:
        return [{"id": name.lower().replace(" ", "_"), "name": name} for name in SCENES]

    def trigger_scene(self, scene: str) -> str:
        found = self.find_scene(scene)
        with self._lock:
            for device_id, changes in SCENES[found["name"]].items():
                self.devices[device_id].update(changes)
        return f"Activated scene {found['name']}."
