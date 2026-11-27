from __future__ import annotations

import sys
from typing import Any

from .base import Channel


class CLIChannel(Channel):
    """Interactive terminal chat."""

    conversation = "cli"

    def __init__(self, assistant, cfg, verbose: bool = False, **kw: Any) -> None:
        super().__init__(assistant, cfg, **kw)
        self.verbose = verbose
        self.name = cfg["assistant"].get("name", "Assistant")

    def respond(self, text: str) -> None:
        for kind, content in self.assistant.chat(text, self.conversation):
            if kind == "reply":
                print(f"{self.name}: {content}\n")
            elif self.verbose:
                print(f"  [{'→' if kind == 'tool' else '←'}] {content}")

    def run(self) -> None:
        plugins = ", ".join(p.id for p in self.assistant.plugins)
        print(f"{self.name} ready (model: {self.assistant.model_name}; plugins: {plugins}). /help for commands.\n")
        while True:
            try:
                text = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return
            if not text:
                continue
            if text.startswith("/"):
                if text in ("/quit", "/exit"):
                    return
                if text == "/verbose":
                    self.verbose = not self.verbose
                    print(f"Verbose {'on' if self.verbose else 'off'}.")
                    continue
                try:
                    out = self.handle_command(text, self.conversation)
                except Exception as e:
                    out = f"Error: {e}"
                print(out if out is not None else self.help_text() + "\n/verbose - toggle tool-call display\n/quit - exit")
                continue
            try:
                self.respond(text)
            except Exception as e:
                print(f"Error: {e}\n", file=sys.stderr)
