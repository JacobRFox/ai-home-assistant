"""A keyword-matching stand-in for the LLM, for testing without Ollama.

It makes the same kind of tool calls a real model would, so everything else
(channels, tools, devices, memory) runs for real. Enable with --fake or HA_FAKE_LLM=1.

Understands phrases like:
  turn on/off the kitchen light     set bedroom brightness to 30
  set thermostat to 22              add milk and eggs to the shopping list
  open / close the bedroom blinds   set bedroom blinds to 40% open
  activate movie night scene        list scenes
  remove milk from the list         what's on the shopping list
  note: call the plumber            show my notes
  what time is it                   list devices
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

FILLER = r"(?:the|my|a)\s+"


def _device(text: str) -> str:
    text = re.sub(rf"^{FILLER}", "", text.strip(" .!?"))
    return re.sub(r"\s+(?:please|now)$", "", text)


def _items(text: str) -> list[str]:
    parts = re.split(r",\s*|\s+and\s+", text.strip(" .!?"))
    return [re.sub(rf"^(?:some\s+|{FILLER})", "", p).strip() for p in parts if p.strip()]


RULES: list[tuple[str, Any]] = [
    (r"(?:activate|run|start|trigger)\s+(?:the\s+)?(.+?)\s+scene\b|\bscene\s+(.+)",
     lambda m: ("activate_scene", {"scene": (m.group(1) or m.group(2)).strip(" .!?")})),
    (r"\bscenes\b", lambda m: ("list_scenes", {})),
    (r"set\s+(.+?)\s+to\s+(\d+)\s*%?\s*open", lambda m: ("set_blind_position", {"device": _device(m.group(1)), "percent_open": int(m.group(2))})),
    (r"\bturn\s+on\s+(.+)|\bswitch\s+on\s+(.+)|\block\s+(.+)", lambda m: ("turn_on", {"device": _device(next(g for g in m.groups() if g))})),
    (r"\bturn\s+off\s+(.+)|\bswitch\s+off\s+(.+)|\bunlock\s+(.+)", lambda m: ("turn_off", {"device": _device(next(g for g in m.groups() if g))})),
    (r"^(?:please\s+)?open\s+(.+)", lambda m: ("turn_on", {"device": _device(m.group(1))})),
    (r"^(?:please\s+)?close\s+(.+)", lambda m: ("turn_off", {"device": _device(m.group(1))})),
    (r"set\s+(.+?)\s+brightness\s+to\s+(\d+)|(?:dim|brighten)\s+(.+?)\s+to\s+(\d+)",
     lambda m: ("set_brightness", {"device": _device(m.group(1) or m.group(3)), "percent": int(m.group(2) or m.group(4))})),
    (r"(?:set\s+)?(?:the\s+)?(thermostat|heat\w*|temperature)\s+to\s+(\d+(?:\.\d+)?)",
     lambda m: ("set_thermostat", {"device": "thermostat", "temperature": float(m.group(2))})),
    (r"add\s+(.+?)\s+to\s+(?:the\s+|my\s+)?(?:shopping\s+)?list", lambda m: ("add_to_shopping_list", {"items": _items(m.group(1))})),
    (r"remove\s+(.+?)\s+from\s+(?:the\s+|my\s+)?(?:shopping\s+)?list", lambda m: ("remove_from_shopping_list", {"item": _items(m.group(1))[0]})),
    (r"shopping\s+list|grocer", lambda m: ("get_shopping_list", {})),
    (r"^(?:note|remember|remind me)\b[:\s]+(?:that\s+|to\s+)?(.+)", lambda m: ("save_note", {"text": m.group(1)})),
    (r"\bnotes\b", lambda m: ("get_notes", {})),
    (r"\btime\b|\bdate\b|what day", lambda m: ("get_current_time", {})),
    (r"\bdevices?\b|what can you control", lambda m: ("list_devices", {})),
]


class FakeChatModel(BaseChatModel):
    """Rule-based chat model that speaks LangChain's tool-calling protocol."""

    @property
    def _llm_type(self) -> str:
        return "fake-home-assistant"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "FakeChatModel":
        return self  # tools are chosen by RULES; the agent still executes them for real

    def _generate(self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kw: Any) -> ChatResult:
        last = messages[-1]
        if isinstance(last, ToolMessage):
            # Summarize every tool result since the last user message.
            results = []
            for msg in reversed(messages):
                if isinstance(msg, HumanMessage):
                    break
                if isinstance(msg, ToolMessage):
                    results.append(str(msg.content))
            reply = AIMessage(content="[fake model] " + "\n".join(reversed(results)))
        else:
            reply = self._respond(str(last.content) if isinstance(last, HumanMessage) else "")
        return ChatResult(generations=[ChatGeneration(message=reply)])

    @staticmethod
    def _respond(text: str) -> AIMessage:
        calls = []
        # "turn on the kitchen light and add milk to the list" -> handle each clause
        for clause in re.split(r"\s+(?:and\s+then|then|also)\s+|[;.]\s+|,?\s+and\s+(?=turn|switch|set|add|remove|lock|unlock|dim|open|close|activate)", text.strip()):
            for pattern, build in RULES:
                m = re.search(pattern, clause.strip(), re.IGNORECASE)
                if m:
                    name, args = build(m)
                    calls.append({"name": name, "args": args, "id": uuid.uuid4().hex, "type": "tool_call"})
                    break
        if calls:
            return AIMessage(content="", tool_calls=calls)
        return AIMessage(content=f"[fake model] I heard: \"{text}\". I only understand simple commands in test "
                                 "mode, like 'turn on the kitchen light' or 'add milk to the shopping list'.")
