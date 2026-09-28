"""FastAPI local API for the edge agent.

Thin wrapper over the in-process edge memory + sync service. This is the API
the dashboard talks to. Everything here works with zero network access; the
sync endpoints simply report offline when connectivity is down.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .activity import activity
from .config import settings
from .memory import memory
from .metadata import metadata
from .sync_service import sync_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: open shards, warm the model, register device, start sync.
    from .embedder import embedder

    memory.open()
    embedder.warm()
    metadata.init()
    sync_service.start()
    try:
        yield
    finally:
        sync_service.stop()
        memory.close()


app = FastAPI(title="Edge Memory Agent", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---- request models ------------------------------------------------------

class IngestRequest(BaseModel):
    content: str = Field(..., min_length=1)
    category: str = "note"
    private: bool = False
    extra_payload: Optional[Dict[str, Any]] = None


class OfflineRequest(BaseModel):
    forced_offline: bool


# ---- routes --------------------------------------------------------------

@app.get("/health")
def health() -> Dict[str, Any]:
    return {"status": "ok", "device_id": settings.device_id}


@app.post("/ingest")
def ingest(req: IngestRequest) -> Dict[str, Any]:
    result = memory.ingest(
        content=req.content,
        category=req.category,
        private=req.private,
        extra_payload=req.extra_payload,
    )
    return {"ok": True, **result}


@app.get("/search")
def search(
    q: str = Query(..., min_length=1),
    limit: int = 10,
    origin: Optional[str] = None,
) -> Dict[str, Any]:
    return memory.search(q, limit=limit, origin=origin)


@app.get("/memory")
def browse(
    limit: int = 100,
    origin: Optional[str] = None,
    category: Optional[str] = None,
) -> Dict[str, Any]:
    rows = memory.browse(limit=limit, origin=origin, category=category)
    return {"points": rows, "count": len(rows)}


@app.get("/stats")
def stats() -> Dict[str, Any]:
    return memory.stats()


@app.get("/status")
def status() -> Dict[str, Any]:
    return {
        "device": {"id": settings.device_id, "name": settings.device_name},
        "sync": sync_service.state.snapshot(),
        "memory": memory.stats(),
        "metadata_enabled": metadata.enabled,
    }


@app.get("/activity")
def get_activity(limit: int = 100, after_seq: Optional[int] = None) -> Dict[str, Any]:
    events = activity.recent(limit=limit, after_seq=after_seq)
    return {"events": events}


@app.get("/sync/events")
def sync_events(limit: int = 20) -> Dict[str, Any]:
    return {"events": metadata.recent_sync_events(limit=limit)}


@app.get("/conflicts")
def conflicts(limit: int = 20) -> Dict[str, Any]:
    return {"conflicts": metadata.recent_conflicts(limit=limit)}


@app.post("/sync/offline")
def set_offline(req: OfflineRequest) -> Dict[str, Any]:
    """Toggle forced-offline mode — the demo's 'pull the network' switch."""
    sync_service.set_forced_offline(req.forced_offline)
    return {"forced_offline": req.forced_offline}


@app.post("/sync/push")
def force_push() -> Dict[str, Any]:
    if not sync_service.state.online:
        return {"ok": False, "reason": "offline"}
    pushed = sync_service.push_once()
    return {"ok": True, "pushed": pushed}


@app.post("/sync/pull")
def force_pull() -> Dict[str, Any]:
    if not sync_service.state.online:
        return {"ok": False, "reason": "offline"}
    ok = sync_service.pull_once()
    return {"ok": ok}


def run() -> None:
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.edge_api_host,
        port=settings.edge_api_port,
        reload=False,
    )


if __name__ == "__main__":
    run()
