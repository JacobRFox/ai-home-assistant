from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

import ollama

if TYPE_CHECKING:
    from ..agent import HomeAssistant

CORE_COMMANDS = {
    "/model": "/model <name> - switch Ollama model (e.g. /model llama3.1:8b)",
    "/models": "/models - list installed models",
    "/plugins": "/plugins - list loaded plugins",
    "/reset": "/reset - start a fresh conversation",
    "/help": "/help - show this message",
}


class Channel(ABC):
    """A way of talking to the assistant. Subclasses handle transport; the shared
    command handling below keeps slash commands identical across channels."""

    def __init__(self, assistant: "HomeAssistant", cfg: dict[str, Any], **_: Any) -> None:
        self.assistant = assistant
        self.cfg = cfg

    @abstractmethod
    def run(self) -> None:
        """Start the channel and block until it stops."""

    def help_text(self) -> str:
        lines = ["Commands:", *CORE_COMMANDS.values()]
        lines += [f"{name} - {cmd.help}" for name, cmd in self.assistant.plugins.commands().items()]
        return "\n".join(lines)

    def handle_command(self, text: str, conversation: str) -> str | None:
        """Handle a core or plugin slash command. Returns the response, or None if unknown."""
        cmd, _, arg = text.strip().partition(" ")
        cmd = cmd.split("@")[0].lower()  # Telegram appends @botname in groups
        arg = arg.strip()
        base_url = self.cfg["model"]["base_url"]
        if cmd in ("/help", "/start"):
            return self.help_text()
        if cmd == "/reset":
            self.assistant.reset(conversation)
            return "Conversation reset."
        if cmd == "/plugins":
            return "\n".join(f"{p.name} ({p.id}) - {p.description}" for p in self.assistant.plugins)
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
        if plugin_cmd := self.assistant.plugins.commands().get(cmd):
            return plugin_cmd.handler(arg)
        return None
