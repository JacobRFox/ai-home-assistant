"""Control lights, outlets, blinds, locks and thermostats, and run scenes.

Backends: simulated demo devices, Home Assistant, or an IKEA DIRIGERA hub.
"""

from __future__ import annotations

import threading
from typing import Any

from fastapi import APIRouter, HTTPException
from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel

from home_assistant.plugins import Command, Plugin, PluginError

from .backends import SmartHomeBackend, label, make_backend


READING_TEXT = {
    "temperature": lambda v: f"{v}°", "humidity": lambda v: f"{v}% humidity", "pm2_5": lambda v: f"PM2.5 {v}",
    "voc_index": lambda v: f"VOC {v}", "battery": lambda v: f"battery {v}%", "illuminance": lambda v: f"{v} lx",
    "open": lambda v: "open" if v else "closed", "leak": lambda v: "LEAK DETECTED" if v else "dry",
    "motion": lambda v: "motion" if v else "no motion",
}


def readings_text(readings: dict[str, Any]) -> str:
    return ", ".join(READING_TEXT.get(k, lambda v, k=k: f"{k} {v}")(v) for k, v in readings.items())


class PowerBody(BaseModel):
    on: bool


class BrightnessBody(BaseModel):
    percent: int


class TemperatureBody(BaseModel):
    temperature: float


class PositionBody(BaseModel):
    percent: int


class SmartHomePlugin(Plugin):
    id = "smart_home"
    name = "Smart Home"
    description = "Lights, outlets, blinds, locks, thermostats and scenes."

    def setup(self) -> None:
        self.backend: SmartHomeBackend = make_backend(self.ctx.config)
        self._refresh_timer: threading.Timer | None = None
        self._refresh_lock = threading.Lock()
        # Hubs that push updates (DIRIGERA) call this when something changes elsewhere,
        # e.g. from the IKEA app or a physical remote.
        self.backend.start(self._schedule_refresh)

    def shutdown(self) -> None:
        self.backend.stop()
        if self._refresh_timer:
            self._refresh_timer.cancel()

    # ---- change notifications ----------------------------------------------------
    def _emit_changed(self) -> None:
        try:
            self.ctx.emit("changed", {"devices": self.devices()})
        except PluginError as e:
            self.ctx.log.warning("Couldn't refresh devices: %s", e)

    def _schedule_refresh(self) -> None:
        """Debounced: a scene can fire dozens of hub events in a second."""
        with self._refresh_lock:
            if self._refresh_timer:
                self._refresh_timer.cancel()
            self._refresh_timer = threading.Timer(0.3, self._emit_changed)
            self._refresh_timer.daemon = True
            self._refresh_timer.start()

    def _changed(self, message: str) -> str:
        self._schedule_refresh()
        return message

    # ---- shared logic: tools, routes and commands all go through these ----------
    def devices(self) -> list[dict[str, Any]]:
        return self.backend.list_devices()

    def scenes(self) -> list[dict[str, Any]]:
        return self.backend.list_scenes()

    def set_power(self, device: str, on: bool) -> str:
        return self._changed(self.backend.set_power(device, on))

    def set_brightness(self, device: str, percent: int) -> str:
        return self._changed(self.backend.set_brightness(device, percent))

    def set_temperature(self, device: str, temperature: float) -> str:
        return self._changed(self.backend.set_temperature(device, temperature))

    def set_position(self, device: str, percent: int) -> str:
        return self._changed(self.backend.set_position(device, percent))

    def trigger_scene(self, scene: str) -> str:
        return self._changed(self.backend.trigger_scene(scene))

    # ---- AI tools ------------------------------------------------------------------------
    def tools(self) -> list[BaseTool]:
        @tool
        def list_devices() -> list[dict[str, Any]]:
            """List all smart-home devices with id, name, room, type, state and sensor readings."""
            return self.devices()

        @tool
        def turn_on(device: str) -> str:
            """Turn on a device (or lock a lock, open a blind). `device` is its name, 'room name', or id."""
            return self.set_power(device, True)

        @tool
        def turn_off(device: str) -> str:
            """Turn off a device (or unlock a lock, close a blind). `device` is its name, 'room name', or id."""
            return self.set_power(device, False)

        @tool
        def set_brightness(device: str, percent: int) -> str:
            """Set a light's brightness from 0 to 100 percent (0 turns it off)."""
            return self.set_brightness(device, percent)

        @tool
        def set_thermostat(device: str, temperature: float) -> str:
            """Set a thermostat's target temperature."""
            return self.set_temperature(device, temperature)

        @tool
        def set_blind_position(device: str, percent_open: int) -> str:
            """Move a blind: 0 = fully closed, 100 = fully open."""
            return self.set_position(device, percent_open)

        @tool
        def list_scenes() -> list[dict[str, Any]]:
            """List the scenes that can be activated."""
            return self.scenes()

        @tool
        def activate_scene(scene: str) -> str:
            """Activate a scene by name, e.g. 'Movie Night'."""
            return self.trigger_scene(scene)

        return [list_devices, turn_on, turn_off, set_brightness, set_thermostat,
                set_blind_position, list_scenes, activate_scene]

    def prompt(self) -> str:
        return ("Devices may share names across rooms; refer to them as '<room> <name>' or call "
                "list_devices first when unsure. If a request matches a scene (e.g. 'movie night'), "
                "prefer activate_scene. Locks: turn_on locks, turn_off unlocks. Confirm before unlocking doors. "
                "Answer questions about temperature, humidity or open windows from sensor readings in list_devices.")

    # ---- backend API (mounted at /api/plugins/smart_home) ---------------------------
    def router(self) -> APIRouter:
        r = APIRouter()

        def run(fn, *args):
            try:
                return {"message": fn(*args)}
            except PluginError as e:
                raise HTTPException(400, str(e))

        def read(fn):
            try:
                return fn()
            except PluginError as e:
                raise HTTPException(502, str(e))

        @r.get("/devices")
        def get_devices():
            return read(self.devices)

        @r.post("/devices/{device_id}/power")
        def power(device_id: str, body: PowerBody):
            return run(self.set_power, device_id, body.on)

        @r.post("/devices/{device_id}/brightness")
        def brightness(device_id: str, body: BrightnessBody):
            return run(self.set_brightness, device_id, body.percent)

        @r.post("/devices/{device_id}/temperature")
        def temperature(device_id: str, body: TemperatureBody):
            return run(self.set_temperature, device_id, body.temperature)

        @r.post("/devices/{device_id}/position")
        def position(device_id: str, body: PositionBody):
            return run(self.set_position, device_id, body.percent)

        @r.get("/scenes")
        def get_scenes():
            return read(self.scenes)

        @r.post("/scenes/{scene_id}/trigger")
        def trigger(scene_id: str):
            return run(self.trigger_scene, scene_id)

        return r

    # ---- chat commands -----------------------------------------------------------------
    def commands(self) -> dict[str, Command]:
        def describe(d: dict[str, Any]) -> str:
            if not d.get("reachable", True):
                return f"{label(d)}: offline"
            if d["type"] == "sensor":
                return f"{label(d)}: {readings_text(d.get('readings', {})) or 'no readings'}"
            words = {"lock": ("locked", "unlocked"), "cover": ("open", "closed")}.get(d["type"], ("on", "off"))
            state = words[0] if d["on"] else words[1]
            if d["type"] == "cover" and "position" in d:
                state = f"{d['position']}% open"
            extra = f", {d['brightness']}%" if d["type"] == "light" and d["on"] and "brightness" in d else ""
            extra += f", target {d['target_temp']}°" if "target_temp" in d else ""
            return f"{label(d)}: {state}{extra}"

        def show_devices(_: str) -> str:
            return "\n".join(describe(d) for d in self.devices()) or "No devices."

        def show_scenes(arg: str) -> str:
            if arg:
                return self.trigger_scene(arg)
            names = [s["name"] for s in self.scenes()]
            return ("Scenes: " + ", ".join(names) + "\nRun one with /scene <name>.") if names else "No scenes."

        return {
            "devices": Command("show smart-home devices", show_devices),
            "scene": Command("list scenes, or /scene <name> to activate one", show_scenes),
        }


plugin = SmartHomePlugin
