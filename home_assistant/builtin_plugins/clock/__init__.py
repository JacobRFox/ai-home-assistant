"""Current date and time. The smallest example plugin: one tool and a frontend widget."""

from __future__ import annotations

from datetime import datetime

from langchain_core.tools import BaseTool, tool

from home_assistant.plugins import Plugin


class ClockPlugin(Plugin):
    id = "clock"
    name = "Clock"
    description = "Current date and time."

    def tools(self) -> list[BaseTool]:
        @tool
        def get_current_time() -> str:
            """Get the current local date and time."""
            return datetime.now().strftime("%A, %B %d %Y, %I:%M %p")

        return [get_current_time]


plugin = ClockPlugin
