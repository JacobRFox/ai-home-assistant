"""Entry point:

    python -m home_assistant                 # terminal chat (default)
    python -m home_assistant telegram        # Telegram bot
    python -m home_assistant --once "turn on the kitchen light"
"""

from __future__ import annotations

import argparse
import sys

import ollama

from .agent import HomeAssistant
from .channels import CHANNELS, get_channel
from .config import load_config


def check_ollama(base_url: str, model: str) -> bool:
    try:
        installed = [m.model for m in ollama.Client(host=base_url).list().models]
    except Exception:
        print(f"Cannot reach Ollama at {base_url}. Start it with: ollama serve", file=sys.stderr)
        return False
    if not any(n == model or n == f"{model}:latest" for n in installed):
        print(f"Model '{model}' is not installed. Pull it with: ollama pull {model}", file=sys.stderr)
        print(f"Installed: {', '.join(installed) or '(none)'}", file=sys.stderr)
        return False
    return True


def main() -> None:
    p = argparse.ArgumentParser(description="Local LangChain + Ollama home assistant")
    p.add_argument("channel", nargs="?", default="cli", choices=list(CHANNELS), help="how to talk to it (default: cli)")
    p.add_argument("--config", help="path to config.yaml")
    p.add_argument("--model", help="override the Ollama model")
    p.add_argument("--verbose", "-v", action="store_true", help="show tool calls (cli)")
    p.add_argument("--once", metavar="TEXT", help="send one message, print the reply, and exit")
    args = p.parse_args()

    cfg = load_config(args.config)
    if args.model:
        cfg["model"]["name"] = args.model
    if not check_ollama(cfg["model"]["base_url"], cfg["model"]["name"]):
        sys.exit(1)

    assistant = HomeAssistant(cfg)
    if args.once:
        print(assistant.reply(args.once, "cli"))
        return
    try:
        channel = get_channel(args.channel, assistant, cfg, verbose=args.verbose)
    except ValueError as e:
        sys.exit(f"Error: {e}")
    channel.run()


if __name__ == "__main__":
    main()
