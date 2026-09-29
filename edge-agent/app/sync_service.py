"""Sync service: connectivity monitor + push + snapshot pull + conflict resolve.

Runs as background threads alongside the edge agent (shares the Python process
so both threads touch the same Edge shards without cross-language access).

Flow (see design doc section 7):
  * Connectivity monitor flips online/offline every N seconds.
  * Push worker: on online, batches mutable-shard points with
    sync_state=pending and dual-writes them to the server collection, then
    flips them to synced. Applies the conflict rule against any existing
    server point (more-recent updated_at wins; loser logged to Postgres).
  * Pull worker: restores the server shard into the immutable shard via
    (partial) snapshot so synced cloud knowledge is searchable locally.

FORCE_OFFLINE lets the demo simulate loss of connectivity without touching
real networking — the connectivity monitor reports offline and workers idle.
"""
from __future__ import annotations

import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from .activity import activity
from .config import settings
from .memory import memory
from .metadata import metadata

try:
    from qdrant_client import QdrantClient, models
except Exception:  # pragma: no cover
    QdrantClient = None
    models = None


class SyncState:
    def __init__(self) -> None:
        self.online = False
        self.forced_offline = settings.force_offline
        self.last_check: Optional[str] = None
        self.last_push: Optional[str] = None
        self.last_pull: Optional[str] = None
        self.last_error: Optional[str] = None
        self.pushed_total = 0
        self.pulled_total = 0
        self.conflicts_total = 0
        self.lock = threading.Lock()

    def snapshot(self) -> Dict[str, Any]:
        with self.lock:
            return {
                "online": self.online,
                "forced_offline": self.forced_offline,
                "last_check": self.last_check,
                "last_push": self.last_push,
                "last_pull": self.last_pull,
                "last_error": self.last_error,
                "pushed_total": self.pushed_total,
                "pulled_total": self.pulled_total,
                "conflicts_total": self.conflicts_total,
            }


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


class SyncService:
    def __init__(self) -> None:
        self.state = SyncState()
        self._client: Any = None
        self._stop = threading.Event()
        self._threads: List[threading.Thread] = []

    # ---- server client ---------------------------------------------------

    def _server(self) -> Any:
        if QdrantClient is None:
            return None
        if self._client is None:
            self._client = QdrantClient(
                url=settings.qdrant_url,
                api_key=settings.qdrant_api_key or None,
                timeout=5.0,
            )
        return self._client

    def _ensure_collection(self) -> None:
        client = self._server()
        if client is None:
            return
        try:
            if not client.collection_exists(settings.collection_name):
                client.create_collection(
                    collection_name=settings.collection_name,
                    vectors_config={
                        settings.vector_name: models.VectorParams(
                            size=settings.vector_dim,
                            distance=models.Distance.COSINE,
                        )
                    },
                )
                activity.record("sync", "Created server collection", name=settings.collection_name)
        except Exception as exc:
            activity.record("error", "ensure_collection failed", error=str(exc))

    # ---- connectivity ----------------------------------------------------

    def set_forced_offline(self, value: bool) -> None:
        with self.state.lock:
            self.state.forced_offline = value
        activity.record("status", f"Forced offline = {value}")

    def _check_connectivity(self) -> bool:
        with self.state.lock:
            if self.state.forced_offline:
                self.state.online = False
                self.state.last_check = _now_iso()
                return False
        url = f"{settings.qdrant_url.rstrip('/')}/healthz"
        headers = {"api-key": settings.qdrant_api_key} if settings.qdrant_api_key else {}
        online = False
        try:
            r = requests.get(url, headers=headers, timeout=3)
            online = r.status_code == 200
        except Exception:
            # Fallback to readyz / root if healthz not present.
            try:
                r = requests.get(settings.qdrant_url.rstrip("/") + "/readyz", headers=headers, timeout=3)
                online = r.status_code == 200
            except Exception:
                online = False
        with self.state.lock:
            was = self.state.online
            self.state.online = online
            self.state.last_check = _now_iso()
        if online != was:
            activity.record("status", f"Connectivity: {'online' if online else 'offline'}")
            metadata.set_status("online" if online else "offline")
        return online

    def _connectivity_loop(self) -> None:
        while not self._stop.is_set():
            self._check_connectivity()
            metadata.heartbeat()
            self._stop.wait(settings.connectivity_poll_seconds)

    # ---- push (dual-write with conflict resolution) ----------------------

    def _resolve_conflict(self, pending: Dict[str, Any], client: Any) -> bool:
        """Return True if the local point should win and be written to server.

        Compares updated_at of the local point vs the existing server point.
        More recent timestamp wins; the loser is logged to Postgres and the
        activity feed rather than silently dropped.
        """
        pid = str(pending["id"])
        local_payload = pending["payload"]
        local_ts = local_payload.get("updated_at", "")
        try:
            existing = client.retrieve(
                collection_name=settings.collection_name,
                ids=[pid],
                with_payload=True,
            )
        except Exception:
            return True  # can't read server -> assume new, let upsert proceed

        if not existing:
            return True  # brand new point on the server

        server_payload = getattr(existing[0], "payload", {}) or {}
        server_ts = server_payload.get("updated_at", "")
        if not server_ts or local_ts >= server_ts:
            resolution = "local_wins"
            winner = True
        else:
            resolution = "server_wins"
            winner = False

        with self.state.lock:
            self.state.conflicts_total += 1
        metadata.log_conflict(
            point_id=pid,
            local_value=str(local_payload.get("content", "")),
            server_value=str(server_payload.get("content", "")),
            local_updated_at=local_ts or None,
            server_updated_at=server_ts or None,
            resolution=resolution,
        )
        activity.record(
            "conflict",
            f"Conflict on {pid[:8]} resolved: {resolution}",
            point_id=pid,
            resolution=resolution,
        )
        return winner

    def push_once(self) -> int:
        client = self._server()
        if client is None:
            return 0
        pending = memory.pending_points(limit=256)
        if not pending:
            return 0

        # Only open a sync_event when there is actual work to log.
        event_id = metadata.start_sync_event()
        start = time.perf_counter()
        status = "success"
        to_write: List[Any] = []
        synced_ids: List[str] = []
        try:
            self._ensure_collection()
            for p in pending:
                if not self._resolve_conflict(p, client):
                    # Server wins: still mark local synced so we stop retrying,
                    # but do not overwrite the server.
                    synced_ids.append(str(p["id"]))
                    continue
                to_write.append(
                    models.PointStruct(
                        id=str(p["id"]),
                        vector={settings.vector_name: p["vector"]},
                        payload={**p["payload"], "origin": "synced", "sync_state": "synced"},
                    )
                )
                synced_ids.append(str(p["id"]))

            if to_write:
                client.upsert(collection_name=settings.collection_name, points=to_write)
            memory.mark_synced(synced_ids)

            with self.state.lock:
                self.state.pushed_total += len(to_write)
                self.state.last_push = _now_iso()
            activity.record("sync", f"Pushed {len(to_write)} point(s) to cloud")
        except Exception as exc:
            status = "failed"
            with self.state.lock:
                self.state.last_error = str(exc)
            activity.record("error", "Push failed", error=str(exc))
        finally:
            metadata.finish_sync_event(
                event_id, len(to_write), 0,
                int((time.perf_counter() - start) * 1000), status,
            )
        return len(to_write)

    def _push_loop(self) -> None:
        while not self._stop.is_set():
            if self.state.online:
                self.push_once()
            self._stop.wait(settings.push_interval_seconds)

    # ---- pull (snapshot restore into immutable shard) --------------------

    def pull_once(self) -> bool:
        base = settings.qdrant_url.rstrip("/")
        headers = {"api-key": settings.qdrant_api_key} if settings.qdrant_api_key else {}
        col = settings.collection_name
        shard_id = settings.server_shard_id
        data_dir = Path(settings.shard_root) / settings.device_id
        data_dir.mkdir(parents=True, exist_ok=True)

        # Nothing to pull until the collection exists on the server (created by
        # the first push). Skip quietly to avoid noisy 404s on a fresh start.
        client = self._server()
        try:
            if client is not None and not client.collection_exists(col):
                return False
        except Exception:
            pass

        event_id = metadata.start_sync_event()
        start = time.perf_counter()
        before = memory.stats().get("synced_points", 0)
        manifest = memory.snapshot_manifest()
        try:
            if manifest is None:
                # Full snapshot: build one, then download it.
                url = f"{base}/collections/{col}/shards/{shard_id}/snapshot"
                with tempfile.TemporaryDirectory(dir=str(data_dir)) as tmp:
                    snap_path = Path(tmp) / "shard.snapshot"
                    with requests.get(url, headers=headers, stream=True, timeout=30) as r:
                        r.raise_for_status()
                        with open(snap_path, "wb") as f:
                            for chunk in r.iter_content(chunk_size=8192):
                                f.write(chunk)
                    memory.apply_full_snapshot(str(snap_path))
            else:
                url = f"{base}/collections/{col}/shards/{shard_id}/snapshot/partial/create"
                with tempfile.TemporaryDirectory(dir=str(data_dir)) as tmp:
                    snap_path = Path(tmp) / "partial.snapshot"
                    r = requests.post(url, headers=headers, json=manifest, stream=True, timeout=30)
                    r.raise_for_status()
                    with open(snap_path, "wb") as f:
                        for chunk in r.iter_content(chunk_size=8192):
                            f.write(chunk)
                    memory.apply_partial_snapshot(str(snap_path))
        except Exception as exc:
            with self.state.lock:
                self.state.last_error = str(exc)
            activity.record("error", "Pull failed", error=str(exc))
            metadata.finish_sync_event(
                event_id, 0, 0,
                int((time.perf_counter() - start) * 1000), "failed",
            )
            return False

        after = memory.stats().get("synced_points", 0)
        with self.state.lock:
            self.state.last_pull = _now_iso()
            self.state.pulled_total = after
        metadata.finish_sync_event(
            event_id, 0, after,
            int((time.perf_counter() - start) * 1000), "success",
        )
        activity.record("sync", "Pulled snapshot into immutable shard")
        return True

    def _pull_loop(self) -> None:
        while not self._stop.is_set():
            if self.state.online:
                self.pull_once()
            self._stop.wait(settings.pull_interval_seconds)

    # ---- lifecycle -------------------------------------------------------

    def start(self) -> None:
        self._stop.clear()
        self._threads = [
            threading.Thread(target=self._connectivity_loop, name="connectivity", daemon=True),
            threading.Thread(target=self._push_loop, name="push", daemon=True),
            threading.Thread(target=self._pull_loop, name="pull", daemon=True),
        ]
        for t in self._threads:
            t.start()
        activity.record("status", "Sync service started")

    def stop(self) -> None:
        self._stop.set()
        for t in self._threads:
            t.join(timeout=2)
        activity.record("status", "Sync service stopped")


sync_service = SyncService()
