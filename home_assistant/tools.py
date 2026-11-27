"""LangChain tools exposed to the model."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool, tool

from .devices import SmartHomeBackend


class DataStore:
    """Tiny JSON-file store for notes and the shopping list."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.data: dict[str, list[str]] = {"shopping_list": [], "notes": []}
        if path.exists():
            self.data.update(json.loads(path.read_text()))

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2))


def build_tools(backend: SmartHomeBackend, store: DataStore) -> list[BaseTool]:
    def safe(fn, *args: Any) -> str:
        try:
            return fn(*args)
        except Exception as e:  # report errors back to the model instead of crashing
            return f"Error: {e}"

    @tool
    def get_current_time() -> str:
        """Get the current local date and time."""
        return datetime.now().strftime("%A, %B %d %Y, %I:%M %p")

    @tool
    def list_devices() -> str:
        """List all smart-home devices with their ids, names, types and current state."""
        return safe(lambda: json.dumps(backend.list_devices(), indent=1))

    @tool
    def turn_on(device: str) -> str:
        """Turn on (or lock / open) a device. `device` is its name or id, e.g. 'kitchen light'."""
        return safe(backend.set_power, device, True)

    @tool
    def turn_off(device: str) -> str:
        """Turn off (or unlock / close) a device. `device` is its name or id."""
        return safe(backend.set_power, device, False)

    @tool
    def set_brightness(device: str, percent: int) -> str:
        """Set a light's brightness from 0 to 100 percent."""
        return safe(backend.set_brightness, device, percent)

    @tool
    def set_thermostat(device: str, temperature: float) -> str:
        """Set a thermostat's target temperature."""
        return safe(backend.set_temperature, device, temperature)

    @tool
    def add_to_shopping_list(items: list[str]) -> str:
        """Add one or more items to the shopping list."""
        store.data["shopping_list"].extend(i.strip() for i in items if i.strip())
        store.save()
        return f"Added {', '.join(items)}. List now has {len(store.data['shopping_list'])} items."

    @tool
    def remove_from_shopping_list(item: str) -> str:
        """Remove an item from the shopping list (case-insensitive)."""
        lst = store.data["shopping_list"]
        for existing in lst:
            if existing.lower() == item.strip().lower():
                lst.remove(existing)
                store.save()
                return f"Removed {existing}."
        return f"{item} is not on the list."

    @tool
    def get_shopping_list() -> str:
        """Read the current shopping list."""
        lst = store.data["shopping_list"]
        return ", ".join(lst) if lst else "The shopping list is empty."

    @tool
    def save_note(text: str) -> str:
        """Save a note or reminder for later."""
        store.data["notes"].append(f"[{datetime.now():%Y-%m-%d %H:%M}] {text}")
        store.save()
        return "Note saved."

    @tool
    def get_notes() -> str:
        """Read all saved notes."""
        return "\n".join(store.data["notes"]) or "No notes saved."

    return [
        get_current_time, list_devices, turn_on, turn_off, set_brightness, set_thermostat,
        add_to_shopping_list, remove_from_shopping_list, get_shopping_list, save_note, get_notes,
    ]
