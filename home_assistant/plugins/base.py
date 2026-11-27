"""The plugin contract.

A plugin is a Python package whose module exposes `plugin = <Plugin subclass>`.
Each part is optional:

    tools()     -> LangChain tools, so the AI can operate the plugin
    router()    -> FastAPI router (backend), mounted at /api/plugins/<id>/
    frontend/   -> folder with index.js defining the <plugin-<id>> web component
    commands()  -> slash commands for chat channels (CLI, Telegram, ...)
    prompt()    -> extra instructions appended to the AI's system prompt

Put shared logic in plain methods on the plugin and call them from the tools,
the routes and the commands alike, so every interface behaves the same.
"""

from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, ClassVar

if TYPE_CHECKING:
    from fastapi import APIRouter
    from langchain_core.tools import BaseTool

    from ..events import EventBus
    from ..storage import JsonStore


class PluginError(Exception):
    """A user-facing error. Its message is shown to the AI, the API caller, or the chat user."""


@dataclass
class Command:
    help: str
    handler: Callable[[str], str]  # receives the text after the command, returns the reply


@dataclass
class PluginContext:
    """Everything the app gives a plugin."""

    plugin_id: str
    config: dict[str, Any]        # this plugin's section of config.yaml (plugins.<id>)
    store: "JsonStore"            # persistent storage private to this plugin
    events: "EventBus"
    log: logging.Logger
    app_config: dict[str, Any] = field(default_factory=dict)
    # The HomeAssistant core, set once all plugins are loaded. Lets input plugins
    # (e.g. voice) talk to the AI: self.ctx.assistant.chat(text, conversation)
    assistant: Any = None

    def emit(self, name: str, data: Any = None) -> None:
        """Publish `<plugin_id>.<name>`; the dashboard and other plugins can react to it."""
        self.events.publish(f"{self.plugin_id}.{name}", data)


class Plugin:
    id: ClassVar[str]                 # unique, snake_case, e.g. "smart_home"
    name: ClassVar[str]               # display name
    description: ClassVar[str] = ""
    version: ClassVar[str] = "0.1.0"
    frontend: ClassVar[str | None] = "frontend"  # folder (next to the module) holding index.js

    def __init__(self, ctx: PluginContext) -> None:
        self.ctx = ctx
        self.setup()

    # ---- lifecycle -------------------------------------------------------
    def setup(self) -> None:
        """Initialize state. `self.ctx` is available."""

    def shutdown(self) -> None:
        """Release resources when the app stops."""

    # ---- extension points ------------------------------------------------
    def tools(self) -> list["BaseTool"]:
        return []

    def router(self) -> "APIRouter | None":
        return None

    def commands(self) -> dict[str, Command]:
        return {}

    def prompt(self) -> str:
        return ""

    # ---- helpers ---------------------------------------------------------
    @classmethod
    def element_tag(cls) -> str:
        """Custom-element name the frontend must define: plugin-<id with dashes>."""
        return "plugin-" + cls.id.replace("_", "-")

    @classmethod
    def frontend_dir(cls) -> Path | None:
        if not cls.frontend:
            return None
        path = Path(inspect.getfile(cls)).parent / cls.frontend
        return path if (path / "index.js").is_file() else None
