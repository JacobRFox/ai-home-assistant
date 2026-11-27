"""Smart-home backends: a simulated one for demos and a Home Assistant REST client."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import requests


class SmartHomeBackend(ABC):
    @abstractmethod
    def list_devices(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    def set_power(self, device_id: str, on: bool) -> str: ...

    @abstractmethod
    def set_brightness(self, device_id: str, percent: int) -> str: ...

    @abstractmethod
    def set_temperature(self, device_id: str, temperature: float) -> str: ...

    def resolve(self, name_or_id: str) -> str:
        """Match a friendly name, area, or id to a single device id."""
        query = name_or_id.strip().lower()
        devices = self.list_devices()
        for d in devices:
            if query in (d["id"].lower(), d["name"].lower()):
                return d["id"]
        matches = [d for d in devices if query in d["name"].lower() or query in d["id"].lower()]
        if len(matches) == 1:
            return matches[0]["id"]
        if not matches:
            raise ValueError(f"No device matches '{name_or_id}'.")
        names = ", ".join(d["name"] for d in matches)
        raise ValueError(f"'{name_or_id}' is ambiguous; it matches: {names}.")


class SimulatedBackend(SmartHomeBackend):
    def __init__(self) -> None:
        self.devices: dict[str, dict[str, Any]] = {
            "light.living_room": {"name": "Living Room Light", "type": "light", "on": False, "brightness": 80},
            "light.kitchen": {"name": "Kitchen Light", "type": "light", "on": True, "brightness": 100},
            "light.bedroom": {"name": "Bedroom Lamp", "type": "light", "on": False, "brightness": 40},
            "switch.coffee_maker": {"name": "Coffee Maker", "type": "switch", "on": False},
            "climate.thermostat": {"name": "Thermostat", "type": "climate", "on": True, "target_temp": 21.0},
            "lock.front_door": {"name": "Front Door Lock", "type": "lock", "on": True},
        }

    def list_devices(self) -> list[dict[str, Any]]:
        return [{"id": k, **v} for k, v in self.devices.items()]

    def _get(self, device_id: str) -> dict[str, Any]:
        return self.devices[self.resolve(device_id)]

    def set_power(self, device_id: str, on: bool) -> str:
        d = self._get(device_id)
        d["on"] = on
        word = ("locked" if on else "unlocked") if d["type"] == "lock" else ("on" if on else "off")
        return f"{d['name']} is now {word}."

    def set_brightness(self, device_id: str, percent: int) -> str:
        d = self._get(device_id)
        if d["type"] != "light":
            raise ValueError(f"{d['name']} is not a dimmable light.")
        d["brightness"] = max(0, min(100, percent))
        d["on"] = d["brightness"] > 0
        return f"{d['name']} brightness set to {d['brightness']}%."

    def set_temperature(self, device_id: str, temperature: float) -> str:
        d = self._get(device_id)
        if d["type"] != "climate":
            raise ValueError(f"{d['name']} is not a thermostat.")
        d["target_temp"] = temperature
        return f"{d['name']} target set to {temperature}°."


class HomeAssistantBackend(SmartHomeBackend):
    """Talks to a Home Assistant instance via its REST API."""

    DOMAINS = ("light", "switch", "fan", "climate", "lock", "cover", "media_player")

    def __init__(self, url: str, token: str) -> None:
        if not token:
            raise ValueError("Home Assistant backend needs a token (smart_home.homeassistant.token or HASS_TOKEN).")
        self.url = url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {token}", "Content-Type": "application/json"})

    def _call(self, domain: str, service: str, data: dict[str, Any]) -> None:
        r = self.session.post(f"{self.url}/api/services/{domain}/{service}", json=data, timeout=10)
        r.raise_for_status()

    def list_devices(self) -> list[dict[str, Any]]:
        r = self.session.get(f"{self.url}/api/states", timeout=10)
        r.raise_for_status()
        devices = []
        for s in r.json():
            domain = s["entity_id"].split(".")[0]
            if domain not in self.DOMAINS:
                continue
            attrs = s.get("attributes", {})
            dev = {
                "id": s["entity_id"],
                "name": attrs.get("friendly_name", s["entity_id"]),
                "type": domain,
                "state": s["state"],
            }
            if "brightness" in attrs and attrs["brightness"] is not None:
                dev["brightness"] = round(attrs["brightness"] / 255 * 100)
            if "temperature" in attrs:
                dev["target_temp"] = attrs["temperature"]
            devices.append(dev)
        return devices

    def set_power(self, device_id: str, on: bool) -> str:
        entity = self.resolve(device_id)
        domain = entity.split(".")[0]
        if domain == "lock":
            self._call("lock", "lock" if on else "unlock", {"entity_id": entity})
        elif domain == "cover":
            self._call("cover", "open_cover" if on else "close_cover", {"entity_id": entity})
        else:
            self._call("homeassistant", "turn_on" if on else "turn_off", {"entity_id": entity})
        return f"Sent {'on' if on else 'off'} to {entity}."

    def set_brightness(self, device_id: str, percent: int) -> str:
        entity = self.resolve(device_id)
        self._call("light", "turn_on", {"entity_id": entity, "brightness_pct": max(0, min(100, percent))})
        return f"{entity} brightness set to {percent}%."

    def set_temperature(self, device_id: str, temperature: float) -> str:
        entity = self.resolve(device_id)
        self._call("climate", "set_temperature", {"entity_id": entity, "temperature": temperature})
        return f"{entity} target set to {temperature}°."


def make_backend(cfg: dict[str, Any]) -> SmartHomeBackend:
    sh = cfg.get("smart_home", {})
    backend = sh.get("backend", "simulated")
    if backend == "homeassistant":
        ha = sh.get("homeassistant", {})
        return HomeAssistantBackend(ha.get("url", ""), ha.get("token", ""))
    if backend == "simulated":
        return SimulatedBackend()
    raise ValueError(f"Unknown smart_home.backend: {backend!r}")
