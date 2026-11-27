"""Entry point:

    python -m home_assistant                    # terminal chat (default)
    python -m home_assistant web                # dashboard at http://localhost:8765
    python -m home_assistant web telegram       # several channels sharing one assistant
    python -m home_assistant --once "turn on the kitchen light"
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import threading

import ollama

from .agent import HomeAssistant
from .channels import CHANNELS, get_channel
from .config import load_config


def check_ollama(base_url: str, model: str) -> bool:
    try:
        installed = [m.model for m in ollama.Client(host=base_url).list().models]
    except Exception:
        print(f"Cannot reach Ollama at {base_url}. Start it with: ollama serve (or test with --fake)", file=sys.stderr)
        return False
    if not any(n == model or n == f"{model}:latest" for n in installed):
        print(f"Model '{model}' is not installed. Pull it with: ollama pull {model}", file=sys.stderr)
        print(f"Installed: {', '.join(installed) or '(none)'}", file=sys.stderr)
        return False
    return True


def main() -> None:
    p = argparse.ArgumentParser(description="Local LangChain + Ollama home assistant")
    p.add_argument("channels", nargs="*", default=["cli"], metavar="channel",
                   help=f"one or more of: {', '.join(CHANNELS)} (default: cli)")
    p.add_argument("--config", help="path to config.yaml")
    p.add_argument("--model", help="override the Ollama model")
    p.add_argument("--verbose", "-v", action="store_true", help="show tool calls (cli)")
    p.add_argument("--once", metavar="TEXT", help="send one message, print the reply, and exit")
    p.add_argument("--fake", action="store_true", help="use a keyword-matching fake model instead of Ollama (for testing)")
    args = p.parse_args()

    if unknown := [c for c in args.channels if c not in CHANNELS]:
        p.error(f"unknown channel(s): {', '.join(unknown)}. Choose from: {', '.join(CHANNELS)}")
    names = list(dict.fromkeys(args.channels))  # dedupe, keep order
    # Background-channel logs would garble the terminal chat, so keep it quiet there.
    logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        level=logging.WARNING if "cli" in names or args.once else logging.INFO)

    cfg = load_config(args.config)
    if args.model:
        cfg["model"]["name"] = args.model
    if args.fake or os.environ.get("HA_FAKE_LLM", "").lower() in ("1", "true", "yes"):
        cfg["model"]["fake"] = True
    elif not check_ollama(cfg["model"]["base_url"], cfg["model"]["name"]):
        sys.exit(1)

    assistant = HomeAssistant(cfg)
    if args.once:
        print(assistant.reply(args.once, "cli"))
        return

    try:
        channels = [get_channel(n, assistant, cfg, verbose=args.verbose) for n in names]
    except ValueError as e:
        sys.exit(f"Error: {e}")

    # All channels share one assistant (same devices, plugins and events). The
    # terminal needs the main thread for input(); the rest run in background threads.
    main_channel = next((c for n, c in zip(names, channels) if n == "cli"), channels[0])

    def run_background(name: str, channel) -> None:
        try:
            channel.run()
        except Exception as e:
            logging.getLogger(__name__).error("The %s channel stopped: %s (other channels keep running)", name, e)

    for name, channel in zip(names, channels):
        if channel is not main_channel:
            threading.Thread(target=run_background, args=(name, channel), name=name, daemon=True).start()
    try:
        main_channel.run()
    except KeyboardInterrupt:
        pass
    finally:
        assistant.shutdown()


if __name__ == "__main__":
    main()
