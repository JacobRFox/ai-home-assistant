"""Per-plugin JSON key/value storage."""

from __future__ import annotations

import copy
import json
import os
import threading
from pathlib import Path
from typing import Any


class JsonStore:
    """A small persistent dict backed by one JSON file. Safe to use from several threads."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.RLock()
        self._data: dict[str, Any] = json.loads(path.read_text()) if path.exists() else {}

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            # Return a copy so callers can't mutate stored state without set().
            return copy.deepcopy(self._data.get(key, default))

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._data[key] = copy.deepcopy(value)
            self._save()

    def delete(self, key: str) -> None:
        with self._lock:
            if self._data.pop(key, None) is not None:
                self._save()

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, indent=2))
        os.replace(tmp, self.path)  # atomic: never leaves a half-written file
