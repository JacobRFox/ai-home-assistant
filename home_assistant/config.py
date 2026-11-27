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
    "HA_BACKEND": ("smart_home", "backend"),
    "HASS_URL": ("smart_home", "homeassistant", "url"),
    "HASS_TOKEN": ("smart_home", "homeassistant", "token"),
    "TELEGRAM_BOT_TOKEN": ("channels", "telegram", "bot_token"),
    "TELEGRAM_ALLOWED_USERS": ("channels", "telegram", "allowed_user_ids"),  # comma-separated
}
LIST_KEYS = {"TELEGRAM_ALLOWED_USERS"}


def load_config(path: str | Path | None = None) -> dict[str, Any]:
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

    data_file = Path(cfg.get("data_file", "data/assistant_data.json"))
    if not data_file.is_absolute():
        data_file = PROJECT_ROOT / data_file
    cfg["data_file"] = data_file
    return cfg
