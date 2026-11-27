"""The assistant core: plugins + a LangChain agent around an Ollama chat model."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Iterator

from langchain.agents import create_agent
from langchain.agents.middleware import ToolErrorMiddleware
from langchain_core.messages import AIMessage, ToolMessage
from langchain_ollama import ChatOllama
from langgraph.checkpoint.memory import InMemorySaver

from .events import EventBus
from .plugins import PluginError
from .plugins.manager import PluginManager

log = logging.getLogger(__name__)


def _tool_error(exc: Exception, request: Any) -> str:
    """Report tool failures to the model so it can recover, instead of crashing the turn."""
    if isinstance(exc, PluginError):
        return f"Error: {exc}"
    log.exception("Tool %s crashed", request.tool_call.get("name"), exc_info=exc)
    return f"Error: the tool failed unexpectedly ({type(exc).__name__})."


class HomeAssistant:
    def __init__(self, cfg: dict[str, Any]) -> None:
        self.cfg = cfg
        self.events = EventBus()
        self.plugins = PluginManager(cfg, self.events)
        self.plugins.load()
        for plugin in self.plugins:
            plugin.ctx.assistant = self
        self.tools = self.plugins.tools()
        self.memory = InMemorySaver()  # keeps conversation history per thread
        # conversation key (e.g. "cli", "telegram:123") -> current LangGraph thread id
        self._threads: dict[str, str] = {}
        self._build()

    @property
    def model_name(self) -> str:
        return "fake (no Ollama)" if self.cfg["model"].get("fake") else self.cfg["model"]["name"]

    def system_prompt(self) -> str:
        a = self.cfg["assistant"]
        prompt = a["system_prompt"].format(name=a.get("name", "Assistant"))
        if extra := self.plugins.prompts():
            prompt += "\n\n# Plugin notes\n" + extra
        return prompt

    def _build(self) -> None:
        m = self.cfg["model"]
        if m.get("fake"):
            from .fake_llm import FakeChatModel
            llm = FakeChatModel()
        else:
            llm = ChatOllama(
                model=m["name"],
                base_url=m["base_url"],
                temperature=m.get("temperature", 0.3),
                num_ctx=m.get("num_ctx", 8192),
                reasoning=m.get("reasoning", False),
            )
        self.agent = create_agent(
            llm,
            tools=self.tools,
            system_prompt=self.system_prompt(),
            middleware=[ToolErrorMiddleware(on_error=_tool_error)],
            checkpointer=self.memory,
        )

    def switch_model(self, name: str) -> None:
        """Swap the underlying Ollama model at runtime (conversation history is kept).
        Also leaves fake mode, so `/model qwen3:8b` works once the download finishes."""
        self.cfg["model"]["name"] = name
        self.cfg["model"]["fake"] = False
        self._build()
        self.events.publish("assistant.model_changed", {"model": self.model_name})

    def reset(self, conversation: str = "default") -> None:
        """Start a fresh conversation for this user/channel."""
        self._threads[conversation] = uuid.uuid4().hex

    def chat(self, text: str, conversation: str = "default") -> Iterator[tuple[str, str]]:
        """Run one user turn in the given conversation (each channel/user gets its own history).

        Yields ("tool", call), ("result", output) and ("reply", text) events.
        """
        thread_id = self._threads.setdefault(conversation, uuid.uuid4().hex)
        config = {"configurable": {"thread_id": thread_id}}
        for update in self.agent.stream({"messages": [{"role": "user", "content": text}]}, config, stream_mode="updates"):
            for node in update.values():
                for msg in (node or {}).get("messages", []):
                    if isinstance(msg, AIMessage) and msg.tool_calls:
                        for tc in msg.tool_calls:
                            args = ", ".join(f"{k}={v!r}" for k, v in tc["args"].items())
                            yield "tool", f"{tc['name']}({args})"
                    elif isinstance(msg, ToolMessage):
                        yield "result", str(msg.content)
                    elif isinstance(msg, AIMessage) and msg.content:
                        yield "reply", msg.content if isinstance(msg.content, str) else str(msg.content)

    def reply(self, text: str, conversation: str = "default") -> str:
        """Convenience wrapper: run a turn and return only the final reply text."""
        replies = [c for kind, c in self.chat(text, conversation) if kind == "reply"]
        return replies[-1] if replies else "(no response)"

    def shutdown(self) -> None:
        self.plugins.shutdown()
