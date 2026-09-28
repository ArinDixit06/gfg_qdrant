"""In-memory activity log — the live feed the dashboard shows.

Thread-safe ring buffer of recent events (embed / search / sync / conflict).
Kept in-process so it works with zero infrastructure while offline.
"""
from __future__ import annotations

import threading
from collections import deque
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ActivityLog:
    def __init__(self, maxlen: int = 500) -> None:
        self._events: Deque[Dict[str, Any]] = deque(maxlen=maxlen)
        self._lock = threading.Lock()
        self._seq = 0

    def record(self, kind: str, message: str, **detail: Any) -> Dict[str, Any]:
        """kind: embed | search | ingest | sync | conflict | status | error."""
        with self._lock:
            self._seq += 1
            event = {
                "seq": self._seq,
                "ts": _now_iso(),
                "kind": kind,
                "message": message,
                "detail": detail or {},
            }
            self._events.append(event)
            return event

    def recent(self, limit: int = 100, after_seq: int | None = None) -> List[Dict[str, Any]]:
        with self._lock:
            events = list(self._events)
        if after_seq is not None:
            events = [e for e in events if e["seq"] > after_seq]
        return events[-limit:]


activity = ActivityLog()
