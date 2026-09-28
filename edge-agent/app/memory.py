"""Edge memory store: two Qdrant Edge shards per device.

  * mutable shard   -> local writes created on-device (origin=local)
  * immutable shard -> mirror of the server shard, restored via snapshot
                       (origin=synced)

Search MERGES results from both shards, so freshly created local data is
searchable immediately alongside synced cloud knowledge. That merge is what
makes this a real edge/cloud system rather than a local vector DB demo.

All Qdrant Edge calls here follow the documented Edge API surface:
EdgeShard.create/load, .update(UpdateOperation...), .query(QueryRequest...),
.retrieve, .scroll, .count, .close, .snapshot_manifest, .update_from_snapshot.
"""
from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from qdrant_edge import (
    CountRequest,
    Distance,
    EdgeConfig,
    EdgeShard,
    EdgeVectorParams,
    FieldCondition,
    Filter,
    MatchValue,
    PayloadSchemaType,
    Point,
    Query,
    QueryRequest,
    ScrollRequest,
    UpdateOperation,
)

from .activity import activity
from .config import settings
from .embedder import embedder
from .policy import decide_placement


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class EdgeMemory:
    """Owns both shards and serializes access to them with a lock."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.mutable: EdgeShard | None = None
        self.immutable: EdgeShard | None = None
        self._immutable_available = False

    # ---- lifecycle -------------------------------------------------------

    def _config(self) -> EdgeConfig:
        return EdgeConfig(
            vectors={
                settings.vector_name: EdgeVectorParams(
                    size=settings.vector_dim,
                    distance=Distance.Cosine,
                )
            }
        )

    def _open_or_create(self, directory: str) -> EdgeShard:
        path = Path(directory)
        marker = path / "wal"  # Edge writes a WAL dir once initialized
        if path.exists() and any(path.iterdir()):
            try:
                return EdgeShard.load(directory)
            except Exception:
                # Directory exists but isn't a valid shard yet -> create.
                pass
        path.mkdir(parents=True, exist_ok=True)
        # create() fails if the dir already holds data; guard with load above.
        try:
            shard = EdgeShard.create(directory, self._config())
        except Exception:
            shard = EdgeShard.load(directory)
        return shard

    def open(self) -> None:
        with self._lock:
            self.mutable = self._open_or_create(settings.mutable_shard_dir)
            # Index the payload fields we filter/facet on.
            for field, schema in (
                ("origin", PayloadSchemaType.Keyword),
                ("category", PayloadSchemaType.Keyword),
                ("sync_state", PayloadSchemaType.Keyword),
                ("device_id", PayloadSchemaType.Keyword),
            ):
                try:
                    self.mutable.update(
                        UpdateOperation.create_field_index(field, schema)
                    )
                except Exception:
                    pass  # index may already exist

            # The immutable shard only exists after the first snapshot pull.
            imm_dir = Path(settings.immutable_shard_dir)
            if imm_dir.exists() and any(imm_dir.iterdir()):
                try:
                    self.immutable = EdgeShard.load(settings.immutable_shard_dir)
                    self._immutable_available = True
                except Exception:
                    self.immutable = None
                    self._immutable_available = False
            activity.record("status", "Edge shards opened", device=settings.device_id)

    def close(self) -> None:
        with self._lock:
            for shard in (self.mutable, self.immutable):
                if shard is not None:
                    try:
                        shard.close()
                    except Exception:
                        pass

    @property
    def immutable_available(self) -> bool:
        return self._immutable_available

    # ---- writes ----------------------------------------------------------

    def ingest(
        self,
        content: str,
        category: str = "note",
        private: bool = False,
        point_id: Optional[str] = None,
        extra_payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Embed locally, apply the placement policy, store in mutable shard."""
        decision = decide_placement(category, private)
        vector = embedder.embed_one(content)
        pid = point_id or str(uuid.uuid4())
        now = _now_iso()

        # sync_state=pending only when the policy allows cloud sync; otherwise
        # local_only, which the push worker will skip.
        sync_state = "pending" if decision.sync_to_cloud else "local_only"

        payload: Dict[str, Any] = {
            "content": content,
            "device_id": settings.device_id,
            "origin": "local",
            "sync_state": sync_state,
            "category": category,
            "private": private,
            "created_at": now,
            "updated_at": now,
            "placement_reason": decision.reason,
        }
        if extra_payload:
            payload.update(extra_payload)

        point = Point(id=pid, vector={settings.vector_name: vector}, payload=payload)
        with self._lock:
            assert self.mutable is not None
            self.mutable.update(UpdateOperation.upsert_points([point]))

        activity.record(
            "ingest",
            f"Stored '{_snippet(content)}' locally",
            point_id=pid,
            category=category,
            sync=decision.sync_to_cloud,
            reason=decision.reason,
        )
        return {"id": pid, "payload": payload, "placement": decision.__dict__}

    def mark_synced(self, point_ids: List[str]) -> None:
        """Flip sync_state pending -> synced on the given points via set_payload."""
        if not point_ids:
            return
        with self._lock:
            assert self.mutable is not None
            self.mutable.update(
                UpdateOperation.set_payload(
                    point_ids,
                    {"sync_state": "synced", "updated_at": _now_iso()},
                )
            )

    def pending_points(self, limit: int = 256) -> List[Dict[str, Any]]:
        """Points in the mutable shard eligible + waiting for cloud push."""
        flt = Filter(
            must=[FieldCondition(key="sync_state", match=MatchValue(value="pending"))]
        )
        with self._lock:
            assert self.mutable is not None
            records, _ = self.mutable.scroll(
                ScrollRequest(
                    limit=limit, filter=flt, with_payload=True, with_vector=True
                )
            )
        out = []
        for rec in records:
            out.append(
                {
                    "id": _record_id(rec),
                    "vector": _record_vector(rec),
                    "payload": dict(_record_payload(rec)),
                }
            )
        return out

    # ---- reads -----------------------------------------------------------

    def search(
        self,
        query_text: str,
        limit: int = 10,
        origin: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Embed the query and MERGE nearest neighbors across both shards."""
        qvec = embedder.embed_one(query_text)
        start = time.perf_counter()
        flt = None
        if origin in ("local", "synced"):
            flt = Filter(
                must=[FieldCondition(key="origin", match=MatchValue(value=origin))]
            )

        merged: Dict[str, Dict[str, Any]] = {}
        shards_hit = []
        with self._lock:
            for name, shard in (("mutable", self.mutable), ("immutable", self.immutable)):
                if shard is None:
                    continue
                if origin == "synced" and name == "mutable":
                    continue
                if origin == "local" and name == "immutable":
                    continue
                shards_hit.append(name)
                res = shard.query(
                    QueryRequest(
                        query=Query.Nearest(qvec, using=settings.vector_name),
                        limit=limit,
                        filter=flt,
                        with_payload=True,
                        with_vector=False,
                    )
                )
                for scored in _query_points(res):
                    pid = str(_scored_id(scored))
                    score = float(_scored_score(scored))
                    # Keep the best score if the same id exists in both shards.
                    if pid not in merged or score > merged[pid]["score"]:
                        merged[pid] = {
                            "id": pid,
                            "score": score,
                            "shard": name,
                            "payload": dict(_scored_payload(scored)),
                        }

        results = sorted(merged.values(), key=lambda r: r["score"], reverse=True)[:limit]
        took_ms = round((time.perf_counter() - start) * 1000, 2)
        activity.record(
            "search",
            f"Search '{_snippet(query_text)}' -> {len(results)} hits",
            shards=shards_hit,
            took_ms=took_ms,
        )
        return {
            "query": query_text,
            "results": results,
            "shards_searched": shards_hit,
            "took_ms": took_ms,
        }

    def browse(
        self,
        limit: int = 100,
        origin: Optional[str] = None,
        category: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List stored points across both shards for the Memory Inspector."""
        must = []
        if origin in ("local", "synced"):
            must.append(FieldCondition(key="origin", match=MatchValue(value=origin)))
        if category:
            must.append(FieldCondition(key="category", match=MatchValue(value=category)))
        flt = Filter(must=must) if must else None

        rows: List[Dict[str, Any]] = []
        with self._lock:
            for name, shard in (("mutable", self.mutable), ("immutable", self.immutable)):
                if shard is None:
                    continue
                if origin == "synced" and name == "mutable":
                    continue
                if origin == "local" and name == "immutable":
                    continue
                records, _ = shard.scroll(
                    ScrollRequest(
                        limit=limit, filter=flt, with_payload=True, with_vector=False
                    )
                )
                for rec in records:
                    rows.append(
                        {
                            "id": _record_id(rec),
                            "shard": name,
                            "payload": dict(_record_payload(rec)),
                        }
                    )
        return rows[:limit]

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            local_total = _safe_count(self.mutable)
            synced_total = _safe_count(self.immutable)
            pending = len(self.pending_points(limit=10_000))
        return {
            "local_points": local_total,
            "synced_points": synced_total,
            "pending_points": pending,
            "immutable_available": self._immutable_available,
        }

    # ---- snapshot restore into the immutable shard -----------------------

    def snapshot_manifest(self) -> Any:
        """Manifest of the immutable shard, for requesting a partial snapshot.

        Returns None if there is no immutable shard yet (initial full pull).
        """
        with self._lock:
            if self.immutable is None:
                return None
            return self.immutable.snapshot_manifest()

    def apply_full_snapshot(self, snapshot_path: str) -> None:
        """Unpack a full server snapshot and (re)open it as the immutable shard."""
        import shutil

        imm_dir = Path(settings.immutable_shard_dir)
        with self._lock:
            if self.immutable is not None:
                try:
                    self.immutable.close()
                except Exception:
                    pass
                self.immutable = None
            if imm_dir.exists():
                shutil.rmtree(imm_dir)
            imm_dir.mkdir(parents=True, exist_ok=True)
            EdgeShard.unpack_snapshot(snapshot_path, str(imm_dir))
            self.immutable = EdgeShard.load(str(imm_dir))
            self._immutable_available = True
        activity.record("sync", "Immutable shard restored from full snapshot")

    def apply_partial_snapshot(self, snapshot_path: str) -> None:
        """Apply a partial snapshot in place onto the immutable shard."""
        with self._lock:
            if self.immutable is None:
                # No base shard -> caller should have used apply_full_snapshot.
                raise RuntimeError("no immutable shard to apply partial snapshot to")
            self.immutable.update_from_snapshot(snapshot_path)
        activity.record("sync", "Immutable shard updated from partial snapshot")


# ---- record/scored-point accessors (bindings return opaque objects) ------
# Qdrant Edge Python returns record/point objects; be tolerant about shape.

def _attr(obj: Any, *names: str, default: Any = None) -> Any:
    for n in names:
        if isinstance(obj, dict) and n in obj:
            return obj[n]
        if hasattr(obj, n):
            return getattr(obj, n)
    return default


def _record_id(rec: Any) -> Any:
    return _attr(rec, "id")


def _record_payload(rec: Any) -> Dict[str, Any]:
    return _attr(rec, "payload", default={}) or {}


def _record_vector(rec: Any) -> List[float]:
    vec = _attr(rec, "vector", "vectors", default={})
    if isinstance(vec, dict):
        return vec.get(settings.vector_name) or next(iter(vec.values()), [])
    return vec or []


def _query_points(res: Any) -> List[Any]:
    # QueryResponse commonly exposes .points
    points = _attr(res, "points", default=None)
    if points is not None:
        return list(points)
    if isinstance(res, (list, tuple)):
        return list(res)
    return []


def _scored_id(sp: Any) -> Any:
    return _attr(sp, "id")


def _scored_score(sp: Any) -> float:
    return _attr(sp, "score", default=0.0)


def _scored_payload(sp: Any) -> Dict[str, Any]:
    return _attr(sp, "payload", default={}) or {}


def _safe_count(shard: Any) -> int:
    if shard is None:
        return 0
    try:
        res = shard.count(CountRequest(exact=True))
        # Returns an int in the Python bindings.
        return int(_attr(res, "count", default=res) or 0)
    except Exception:
        try:
            records, _ = shard.scroll(
                ScrollRequest(limit=10_000, with_payload=False, with_vector=False)
            )
            return len(records)
        except Exception:
            return 0


def _snippet(text: str, n: int = 48) -> str:
    text = text.replace("\n", " ").strip()
    return text if len(text) <= n else text[: n - 1] + "…"


memory = EdgeMemory()
