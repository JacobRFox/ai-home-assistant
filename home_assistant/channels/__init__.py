"""Communication channels. Each one adapts a transport (terminal, Telegram, web, ...)
to the shared HomeAssistant core.

To add a channel: subclass `Channel`, implement `run()`, and register it in CHANNELS.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .base import Channel

if TYPE_CHECKING:
    from ..agent import HomeAssistant


def _cli():
    from .cli import CLIChannel
    return CLIChannel


def _telegram():
    from .telegram import TelegramChannel
    return TelegramChannel


def _web():
    from .web import WebChannel
    return WebChannel


# Lazy so a channel's dependencies are only imported when it's used.
CHANNELS = {"cli": _cli, "telegram": _telegram, "web": _web}


def get_channel(name: str, assistant: "HomeAssistant", cfg: dict, **kwargs) -> Channel:
    if name not in CHANNELS:
        raise ValueError(f"Unknown channel {name!r}. Available: {', '.join(CHANNELS)}")
    return CHANNELS[name]()(assistant, cfg, **kwargs)


__all__ = ["Channel", "CHANNELS", "get_channel"]
