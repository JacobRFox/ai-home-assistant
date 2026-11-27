"""Load config.yaml and apply environment-variable overrides."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = PROJECT_ROOT / "config.yaml"

# env var -> (section, key[, subkey])
ENV_OVERRIDES = {
    "HA_MODEL": ("model", "name"),
    "OLLAMA_HOST": ("model", "base_url"),
    "HA_BACKEND": ("plugins", "smart_home", "backend"),
    "HASS_URL": ("plugins", "smart_home", "homeassistant", "url"),
    "HASS_TOKEN": ("plugins", "smart_home", "homeassistant", "token"),
    "DIRIGERA_HOST": ("plugins", "smart_home", "dirigera", "host"),
    "DIRIGERA_TOKEN": ("plugins", "smart_home", "dirigera", "token"),
    "TELEGRAM_BOT_TOKEN": ("channels", "telegram", "bot_token"),
    "TELEGRAM_ALLOWED_USERS": ("channels", "telegram", "allowed_user_ids"),  # comma-separated
    "HA_PLUGINS": ("plugins", "enabled"),  # comma-separated
    "HA_WEB_HOST": ("channels", "web", "host"),
    "HA_WEB_PORT": ("channels", "web", "port"),
}
LIST_KEYS = {"TELEGRAM_ALLOWED_USERS", "HA_PLUGINS"}

# Secrets (tokens, user ids) can live here instead of the shell; it's git-ignored.
ENV_FILE = PROJECT_ROOT / ".env"


def load_env_file(path: Path = ENV_FILE) -> None:
    """Load KEY=value lines into os.environ. Variables already set in the shell win."""
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.removeprefix("export ").split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    load_env_file()
    path = Path(path) if path else DEFAULT_CONFIG
    with open(path) as f:
        cfg: dict[str, Any] = yaml.safe_load(f) or {}

    for env, keys in ENV_OVERRIDES.items():
        value = os.environ.get(env)
        if not value:
            continue
        node = cfg
        for key in keys[:-1]:
            if not isinstance(node.get(key), dict):  # missing, or empty YAML key (None)
                node[key] = {}
            node = node[key]
        node[keys[-1]] = [v.strip() for v in value.split(",") if v.strip()] if env in LIST_KEYS else value

    base_url = cfg["model"]["base_url"]
    if not base_url.startswith("http"):
        # OLLAMA_HOST is often set as "0.0.0.0:11434"
        cfg["model"]["base_url"] = f"http://{base_url}"

    data_dir = Path(cfg.get("data_dir", "data"))
    if not data_dir.is_absolute():
        data_dir = PROJECT_ROOT / data_dir
    cfg["data_dir"] = data_dir  # each plugin stores data/<plugin_id>.json here
    if not isinstance(cfg.get("plugins"), dict):
        cfg["plugins"] = {}
    return cfg
