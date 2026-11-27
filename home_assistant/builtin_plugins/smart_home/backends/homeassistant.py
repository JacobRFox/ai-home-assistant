"""Devices and scenes from a Home Assistant instance, via its REST API."""

from __future__ import annotations

from typing import Any

import requests

from home_assistant.plugins import PluginError

from .base import SmartHomeBackend, label

DOMAINS = {"light": "light", "switch": "switch", "fan": "fan", "climate": "climate",
           "lock": "lock", "cover": "cover", "media_player": "switch"}
# Home Assistant states normalized to the shared `on` flag (on / locked / open / heating ...).
ON_STATES = {"on", "locked", "open", "opening", "heat", "cool", "heat_cool", "auto", "playing"}


class HomeAssistantBackend(SmartHomeBackend):
    def __init__(self, url: str, token: str) -> None:
        if not token:
            raise PluginError("Home Assistant backend needs a token (plugins.smart_home.homeassistant.token or HASS_TOKEN).")
        self.url = url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {token}", "Content-Type": "application/json"})

    def _request(self, method: str, path: str, **kw: Any) -> Any:
        try:
            r = self.session.request(method, f"{self.url}{path}", timeout=10, **kw)
            r.raise_for_status()
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 401:
                raise PluginError("Home Assistant rejected the access token.") from e
            raise PluginError(f"Home Assistant returned an error: {e}") from e
        except requests.RequestException as e:
            raise PluginError(f"Couldn't reach Home Assistant at {self.url}.") from e
        return r.json() if r.content else None

    def _call(self, domain: str, service: str, data: dict[str, Any]) -> None:
        self._request("POST", f"/api/services/{domain}/{service}", json=data)

    def _states(self) -> list[dict[str, Any]]:
        return self._request("GET", "/api/states")

    def list_devices(self) -> list[dict[str, Any]]:
        devices = []
        for s in self._states():
            domain = s["entity_id"].split(".")[0]
            if domain not in DOMAINS:
                continue
            attrs = s.get("attributes", {})
            dev = {
                "id": s["entity_id"],
                "name": attrs.get("friendly_name", s["entity_id"]),
                "room": None,
                "type": DOMAINS[domain],
                "on": s["state"] in ON_STATES,
                "reachable": s["state"] != "unavailable",
            }
            if domain == "lock":
                dev["on"] = s["state"] == "locked"
            if attrs.get("brightness") is not None:
                dev["brightness"] = round(attrs["brightness"] / 255 * 100)
            if attrs.get("current_position") is not None:
                dev["position"] = attrs["current_position"]
            if attrs.get("temperature") is not None:
                dev["target_temp"] = attrs["temperature"]
            devices.append(dev)
        return devices

    def set_power(self, device: str, on: bool) -> str:
        d = self.find(device)
        entity, domain = d["id"], d["id"].split(".")[0]
        if domain == "lock":
            self._call("lock", "lock" if on else "unlock", {"entity_id": entity})
        elif domain == "cover":
            self._call("cover", "open_cover" if on else "close_cover", {"entity_id": entity})
        else:
            self._call("homeassistant", "turn_on" if on else "turn_off", {"entity_id": entity})
        return f"Sent {'on' if on else 'off'} to {label(d)}."

    def set_brightness(self, device: str, percent: int) -> str:
        d = self.find(device)
        self._call("light", "turn_on", {"entity_id": d["id"], "brightness_pct": max(0, min(100, percent))})
        return f"{label(d)} brightness set to {percent}%."

    def set_temperature(self, device: str, temperature: float) -> str:
        d = self.find(device)
        self._call("climate", "set_temperature", {"entity_id": d["id"], "temperature": temperature})
        return f"{label(d)} target set to {temperature}°."

    def set_position(self, device: str, percent: int) -> str:
        d = self.find(device)
        self._call("cover", "set_cover_position", {"entity_id": d["id"], "position": max(0, min(100, percent))})
        return f"{label(d)} set to {percent}% open."

    def list_scenes(self) -> list[dict[str, Any]]:
        return [{"id": s["entity_id"], "name": s.get("attributes", {}).get("friendly_name", s["entity_id"])}
                for s in self._states() if s["entity_id"].startswith("scene.")]

    def trigger_scene(self, scene: str) -> str:
        found = self.find_scene(scene)
        self._call("scene", "turn_on", {"entity_id": found["id"]})
        return f"Activated scene {found['name']}."
