from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

import ollama

if TYPE_CHECKING:
    from ..agent import HomeAssistant

HELP = """Commands:
/model <name> - switch Ollama model (e.g. /model llama3.1:8b)
/models - list installed models
/devices - show smart-home devices
/reset - start a fresh conversation
/help - show this message"""


class Channel(ABC):
    """A way of talking to the assistant. Subclasses handle transport; the shared
    command handling below keeps slash commands identical across channels."""

    def __init__(self, assistant: "HomeAssistant", cfg: dict[str, Any], **_: Any) -> None:
        self.assistant = assistant
        self.cfg = cfg

    @abstractmethod
    def run(self) -> None:
        """Start the channel and block until it stops."""

    def handle_command(self, text: str, conversation: str) -> str | None:
        """Handle a shared slash command. Returns the response, or None if not a known command."""
        cmd, _, arg = text.strip().partition(" ")
        cmd = cmd.split("@")[0].lower()  # Telegram appends @botname in groups
        arg = arg.strip()
        base_url = self.cfg["model"]["base_url"]
        if cmd in ("/help", "/start"):
            return HELP
        if cmd == "/reset":
            self.assistant.reset(conversation)
            return "Conversation reset."
        if cmd == "/models":
            names = [m.model for m in ollama.Client(host=base_url).list().models]
            current = self.assistant.model_name
            return "\n".join(f"{'* ' if n == current else '  '}{n}" for n in names) or "No models installed."
        if cmd == "/model":
            if not arg:
                return f"Current model: {self.assistant.model_name}"
            names = [m.model for m in ollama.Client(host=base_url).list().models]
            if arg not in names and f"{arg}:latest" not in names:
                return f"'{arg}' isn't installed. Run: ollama pull {arg}"
            self.assistant.switch_model(arg)
            return f"Switched to {arg}."
        if cmd == "/devices":
            return "\n".join(f"{d['name']} ({d['id']})" for d in self.assistant.backend.list_devices())
        return None
