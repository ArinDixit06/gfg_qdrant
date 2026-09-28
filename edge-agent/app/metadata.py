"""Postgres metadata access layer.

Stores operational state only (device registry, sync events, conflicts) — never
vector data. Uses psycopg3. If POSTGRES_ENABLED is false or the DB is
unreachable, every method degrades to a safe no-op so the edge agent still runs
fully offline.
"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .activity import activity
from .config import settings

try:
    import psycopg
    from psycopg.rows import dict_row
except Exception:  # pragma: no cover - psycopg optional at runtime
    psycopg = None
    dict_row = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


class MetadataStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._conn: Any = None
        self._enabled = settings.postgres_enabled and psycopg is not None
        self.device_uuid: Optional[str] = None

    @property
    def enabled(self) -> bool:
        return self._enabled and self._conn is not None

    def _connect(self) -> Any:
        if not self._enabled:
            return None
        if self._conn is not None and not self._conn.closed:
            return self._conn
        try:
            self._conn = psycopg.connect(
                settings.database_url, autocommit=True, row_factory=dict_row
            )
            return self._conn
        except Exception as exc:  # DB down -> degrade gracefully
            activity.record("error", "Postgres unavailable, metadata disabled", error=str(exc))
            self._conn = None
            self._enabled = False
            return None

    def init(self) -> None:
        """Register this device (idempotent by name)."""
        conn = self._connect()
        if conn is None:
            return
        with self._lock:
            try:
                row = conn.execute(
                    "SELECT id FROM devices WHERE name = %s", (settings.device_name,)
                ).fetchone()
                if row:
                    self.device_uuid = str(row["id"])
                else:
                    new_id = str(uuid.uuid4())
                    conn.execute(
                        "INSERT INTO devices (id, name, status, last_seen) "
                        "VALUES (%s, %s, %s, %s)",
                        (new_id, settings.device_name, "offline", _now()),
                    )
                    self.device_uuid = new_id
                activity.record("status", "Device registered in metadata store")
            except Exception as exc:
                activity.record("error", "Device registration failed", error=str(exc))

    def set_status(self, status: str) -> None:
        conn = self._connect()
        if conn is None or self.device_uuid is None:
            return
        with self._lock:
            try:
                conn.execute(
                    "UPDATE devices SET status = %s, last_seen = %s WHERE id = %s",
                    (status, _now(), self.device_uuid),
                )
            except Exception:
                pass

    def heartbeat(self) -> None:
        conn = self._connect()
        if conn is None or self.device_uuid is None:
            return
        with self._lock:
            try:
                conn.execute(
                    "UPDATE devices SET last_seen = %s WHERE id = %s",
                    (_now(), self.device_uuid),
                )
            except Exception:
                pass

    def start_sync_event(self) -> Optional[str]:
        conn = self._connect()
        if conn is None or self.device_uuid is None:
            return None
        event_id = str(uuid.uuid4())
        with self._lock:
            try:
                conn.execute(
                    "INSERT INTO sync_events (id, device_id, started_at, status) "
                    "VALUES (%s, %s, %s, 'running')",
                    (event_id, self.device_uuid, _now()),
                )
                return event_id
            except Exception:
                return None

    def finish_sync_event(
        self,
        event_id: Optional[str],
        pushed: int,
        pulled: int,
        duration_ms: int,
        status: str = "success",
    ) -> None:
        conn = self._connect()
        if conn is None or event_id is None:
            return
        with self._lock:
            try:
                conn.execute(
                    "UPDATE sync_events SET finished_at=%s, points_pushed=%s, "
                    "points_pulled=%s, duration_ms=%s, status=%s WHERE id=%s",
                    (_now(), pushed, pulled, duration_ms, status, event_id),
                )
            except Exception:
                pass

    def log_conflict(
        self,
        point_id: str,
        local_value: str,
        server_value: str,
        local_updated_at: Optional[str],
        server_updated_at: Optional[str],
        resolution: str,
    ) -> None:
        conn = self._connect()
        if conn is None or self.device_uuid is None:
            return
        with self._lock:
            try:
                conn.execute(
                    "INSERT INTO conflicts (id, point_id, device_id, local_value, "
                    "server_value, local_updated_at, server_updated_at, resolution) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        str(uuid.uuid4()),
                        point_id,
                        self.device_uuid,
                        local_value,
                        server_value,
                        local_updated_at,
                        server_updated_at,
                        resolution,
                    ),
                )
            except Exception:
                pass

    def recent_sync_events(self, limit: int = 20) -> List[Dict[str, Any]]:
        conn = self._connect()
        if conn is None or self.device_uuid is None:
            return []
        with self._lock:
            try:
                rows = conn.execute(
                    "SELECT * FROM sync_events WHERE device_id=%s "
                    "ORDER BY started_at DESC LIMIT %s",
                    (self.device_uuid, limit),
                ).fetchall()
                return [_jsonable(r) for r in rows]
            except Exception:
                return []

    def recent_conflicts(self, limit: int = 20) -> List[Dict[str, Any]]:
        conn = self._connect()
        if conn is None or self.device_uuid is None:
            return []
        with self._lock:
            try:
                rows = conn.execute(
                    "SELECT * FROM conflicts WHERE device_id=%s "
                    "ORDER BY resolved_at DESC LIMIT %s",
                    (self.device_uuid, limit),
                ).fetchall()
                return [_jsonable(r) for r in rows]
            except Exception:
                return []


def _jsonable(row: Dict[str, Any]) -> Dict[str, Any]:
    out = {}
    for k, v in row.items():
        if isinstance(v, (datetime,)):
            out[k] = v.isoformat()
        elif isinstance(v, uuid.UUID):
            out[k] = str(v)
        else:
            out[k] = v
    return out


metadata = MetadataStore()
