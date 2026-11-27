"""IKEA DIRIGERA hub, over its local API (https://<hub>:8443/v1).

Uses the community `dirigera` library (github.com/Leggin/dirigera) for the HTTP
session and event WebSocket. Devices are read as raw JSON rather than through the
library's strict pydantic models, so new device types or firmware fields don't
break the whole device list.

Get a token with:  python -m home_assistant.builtin_plugins.smart_home.pair_dirigera <hub-ip>
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any, Callable

import requests

from home_assistant.plugins import PluginError

from .base import SmartHomeBackend, label

log = logging.getLogger(__name__)

# DIRIGERA deviceType -> normalized type
CONTROLLABLE = {"light": "light", "outlet": "switch", "blinds": "cover", "airPurifier": "fan"}
SENSORS = {"environmentSensor", "openCloseSensor", "waterSensor", "motionSensor", "occupancySensor", "lightSensor"}
# Sensor attribute -> reading name
READINGS = {
    "currentTemperature": "temperature", "currentRH": "humidity", "currentPM25": "pm2_5", "vocIndex": "voc_index",
    "isOpen": "open", "waterLeakDetected": "leak", "isDetected": "motion", "illuminance": "illuminance",
    "batteryPercentage": "battery",
}
# Hub events that mean the device/scene list should be refreshed.
REFRESH_EVENTS = {"deviceStateChanged", "deviceAdded", "deviceRemoved", "deviceConfigurationChanged",
                  "sceneCreated", "sceneDeleted", "sceneUpdated"}


def normalize(raw: dict[str, Any], include_sensors: bool = True) -> dict[str, Any] | None:
    """Convert one raw DIRIGERA device to the shared shape (None = not shown)."""
    kind = raw.get("deviceType")
    if raw.get("isHidden") or (kind not in CONTROLLABLE and not (include_sensors and kind in SENSORS)):
        return None
    a = raw.get("attributes") or {}
    d: dict[str, Any] = {
        "id": raw["id"],
        "name": a.get("customName") or a.get("model") or kind,
        "room": (raw.get("room") or {}).get("name"),
        "reachable": raw.get("isReachable", True),
        "type": CONTROLLABLE.get(kind, "sensor"),
        "on": False,
    }
    if kind in ("light", "outlet"):
        d["on"] = bool(a.get("isOn"))
        if kind == "light" and a.get("lightLevel") is not None:
            d["brightness"] = a["lightLevel"]
        if kind == "outlet" and a.get("currentActivePower") is not None:
            d["power_w"] = a["currentActivePower"]
    elif kind == "blinds":
        # DIRIGERA's level is how far the blind is lowered (0 = up/open, 100 = down/closed).
        level = a.get("blindsCurrentLevel", a.get("blindsTargetLevel"))
        if level is not None:
            d["position"] = 100 - level
            d["on"] = d["position"] > 0
    elif kind == "airPurifier":
        d["fan_mode"] = a.get("fanMode")
        d["on"] = a.get("fanMode") not in (None, "off")
    else:
        d["readings"] = {name: a[attr] for attr, name in READINGS.items() if a.get(attr) is not None}
    return d


class DirigeraBackend(SmartHomeBackend):
    def __init__(self, host: str, token: str, include_sensors: bool = True) -> None:
        if not host or not token:
            raise PluginError(
                "The DIRIGERA backend needs the hub's IP and a token. Pair once with:\n"
                "  python -m home_assistant.builtin_plugins.smart_home.pair_dirigera <hub-ip>\n"
                "then set DIRIGERA_HOST and DIRIGERA_TOKEN."
            )
        try:
            from dirigera import Hub
        except ImportError as e:
            raise PluginError("The DIRIGERA backend needs the `dirigera` package: pip install dirigera") from e
        self.host = host
        self.include_sensors = include_sensors
        self.hub = Hub(token=token, ip_address=host)
        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None

    # ---- HTTP with friendly errors -------------------------------------------
    def _call(self, fn: Callable[..., Any], route: str, *args: Any) -> Any:
        try:
            return fn(route, *args)
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            if status == 401:
                raise PluginError("The DIRIGERA hub rejected the token. Pair again to get a new one.") from e
            raise PluginError(f"The DIRIGERA hub returned an error ({status}).") from e
        except requests.RequestException as e:
            raise PluginError(f"Couldn't reach the DIRIGERA hub at {self.host}. Is it on and on this network?") from e

    def _get(self, route: str) -> Any:
        return self._call(self.hub.get, route)

    def _patch(self, device_id: str, attributes: dict[str, Any]) -> None:
        self._call(self.hub.patch, f"/devices/{device_id}", [{"attributes": attributes}])

    # ---- devices -----------------------------------------------------------------
    def list_devices(self) -> list[dict[str, Any]]:
        devices = [d for raw in self._get("/devices") if (d := normalize(raw, self.include_sensors))]
        return sorted(devices, key=lambda d: ((d["room"] or "~").lower(), d["name"].lower()))

    def _controllable(self, device: str, capability: str, action: str) -> tuple[dict[str, Any], dict[str, Any]]:
        """Resolve a device and check it's online and accepts `capability`."""
        d = self.find(device)
        raw = self._get(f"/devices/{d['id']}")
        if not raw.get("isReachable", True):
            raise PluginError(f"{label(d)} is offline (the hub can't reach it).")
        if capability not in (raw.get("capabilities") or {}).get("canReceive", []):
            raise PluginError(f"{label(d)} can't {action}.")
        return d, raw

    def set_power(self, device: str, on: bool) -> str:
        d = self.find(device)
        if d["type"] == "cover":
            return self.set_position(device, 100 if on else 0)
        if d["type"] == "fan":
            d, _ = self._controllable(device, "fanMode", "be switched")
            self._patch(d["id"], {"fanMode": "auto" if on else "off"})
            return f"{label(d)} is now {'on (auto)' if on else 'off'}."
        if d["type"] == "sensor":
            raise PluginError(f"{label(d)} is a sensor and can't be switched.")
        d, _ = self._controllable(device, "isOn", "be switched on or off")
        self._patch(d["id"], {"isOn": on})
        return f"{label(d)} is now {'on' if on else 'off'}."

    def set_brightness(self, device: str, percent: int) -> str:
        d, _ = self._controllable(device, "lightLevel", "be dimmed")
        if percent <= 0:
            self._patch(d["id"], {"isOn": False})
            return f"{label(d)} is now off."
        level = min(100, percent)  # the hub accepts 1-100
        self._patch(d["id"], {"isOn": True})
        self._patch(d["id"], {"lightLevel": level})
        return f"{label(d)} brightness set to {level}%."

    def set_position(self, device: str, percent: int) -> str:
        d, _ = self._controllable(device, "blindsTargetLevel", "be raised or lowered")
        percent = max(0, min(100, percent))
        self._patch(d["id"], {"blindsTargetLevel": 100 - percent})
        state = "opening" if percent == 100 else "closing" if percent == 0 else f"moving to {percent}% open"
        return f"{label(d)} is {state}."

    # ---- scenes -------------------------------------------------------------------
    def list_scenes(self) -> list[dict[str, Any]]:
        scenes = [{"id": s["id"], "name": (s.get("info") or {}).get("name") or s["id"]} for s in self._get("/scenes")]
        return sorted(scenes, key=lambda s: s["name"].lower())

    def trigger_scene(self, scene: str) -> str:
        found = self.find_scene(scene)
        self._call(self.hub.post, f"/scenes/{found['id']}/trigger")
        return f"Activated scene {found['name']}."

    # ---- live updates from the hub ----------------------------------------------
    def start(self, on_change: Callable[[], None]) -> None:
        """Listen to the hub's WebSocket so changes from the IKEA app or remotes show up live."""
        failures = {"count": 0}

        def on_open(_ws: Any) -> None:
            if failures["count"]:
                log.info("Reconnected to DIRIGERA event stream")
            failures["count"] = 0

        def on_message(_ws: Any, message: str) -> None:
            try:
                event = json.loads(message)
            except ValueError:
                return
            if event.get("type") in REFRESH_EVENTS:
                on_change()

        def on_error(_ws: Any, error: Exception) -> None:
            failures["count"] += 1
            # Log the first failure loudly, then quietly while it keeps retrying.
            (log.warning if failures["count"] == 1 else log.debug)("DIRIGERA event stream error: %s", error)

        def run() -> None:
            while not self._stopping.is_set():
                try:
                    self.hub.create_event_listener(on_open=on_open, on_message=on_message, on_error=on_error, reconnect=5)
                except Exception as e:
                    on_error(None, e)
                self._stopping.wait(10)  # run_forever returned: back off, then reconnect

        self._thread = threading.Thread(target=run, name="dirigera-events", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stopping.set()
        try:
            self.hub.stop_event_listener()
        except Exception:
            pass
