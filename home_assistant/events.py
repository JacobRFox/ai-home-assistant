"""A tiny thread-safe publish/subscribe bus.

Plugins publish state changes ("smart_home.changed", ...) and anything can listen:
the web dashboard forwards events to browsers so the UI updates live, even when
the change was made by the AI from another channel.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

log = logging.getLogger(__name__)

Event = dict[str, Any]  # {"type": str, "data": Any, "ts": float}
Subscriber = Callable[[Event], None]


class EventBus:
    def __init__(self) -> None:
        self._subscribers: list[Subscriber] = []
        self._lock = threading.Lock()

    def subscribe(self, callback: Subscriber) -> Callable[[], None]:
        """Call `callback(event)` for every event. Returns an unsubscribe function."""
        with self._lock:
            self._subscribers.append(callback)

        def unsubscribe() -> None:
            with self._lock:
                if callback in self._subscribers:
                    self._subscribers.remove(callback)

        return unsubscribe

    def publish(self, type: str, data: Any = None) -> None:
        event = {"type": type, "data": data, "ts": time.time()}
        with self._lock:
            subscribers = list(self._subscribers)
        for callback in subscribers:
            try:
                callback(event)
            except Exception:
                log.exception("Event subscriber failed for %s", type)
