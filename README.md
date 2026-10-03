# Edge Memory & Intelligence Platform

An offline-first AI application built on **Qdrant Edge**. It keeps a searchable
semantic memory **on the device**, does low-latency vector search with **zero
network dependency**, and synchronizes with a central **Qdrant Server** when
connectivity returns.

> Built for the Qdrant Edge Hackathon (Problem Statement 03).

---

## What makes it real

- **On-device vector memory.** Qdrant Edge runs in-process (like SQLite for
  vectors). Embeddings are generated locally with FastEmbed — no API calls.
- **Genuine offline operation.** Writes and search work with the network fully
  down. Flip connectivity off and search still returns in ~1 ms.
- **Dual-shard merge search.** Each device runs a **mutable** shard (local
  writes) and an **immutable** shard (restored from a server snapshot). Queries
  merge both, so fresh local data and synced cloud knowledge appear together.
- **Dynamic local/cloud policy.** A write-time rule decides what stays local
  (raw sensor data, anything private) vs. what syncs to the cloud (notes,
  summaries).
- **Bidirectional sync + conflict handling.** Push dual-writes pending points to
  the server; pull restores server changes via snapshot. Conflicts resolve by
  timestamp and are logged to Postgres, never silently dropped.
- **Live dashboard.** Four panels: Memory Inspector, Search Console, Sync
  Status, Activity Log.

---

## Architecture

```
┌─────────────────────────── Edge Device (local process) ───────────────────────────┐
│  text in ─► Local Embedder (FastEmbed) ─► Mutable EdgeShard (origin=local)          │
│                                            Immutable EdgeShard (origin=synced)      │
│                                                   │                                 │
│                              Query Merge Layer ◄──┘   ──►  FastAPI (:8000)          │
│                                                                                     │
│  Sync service (threads): connectivity monitor · push (dual-write) · snapshot pull   │
│                          · conflict resolver                                        │
└───────────────────────────────────────────┬─────────────────────────────────────┘
                                             │ when online
                      ┌──────────────────────┴───────────────────────┐
                      │ Qdrant Server (:6333)   │  Postgres (:5432)   │
                      │ per-device shards        │  devices /         │
                      │ (canonical memory)       │  sync_events /     │
                      │                          │  conflicts         │
                      └──────────────────────────┴────────────────────┘

                        Dashboard (Next.js :3000)  ──►  edge agent API
```

---

## Repository layout

```
gfg_qdrant/
├─ edge-agent/            Python edge agent + sync service (FastAPI)
│  ├─ app/
│  │  ├─ main.py          FastAPI app + routes + lifespan
│  │  ├─ memory.py        dual EdgeShard, merge search, snapshot restore
│  │  ├─ embedder.py      local FastEmbed text embedder
│  │  ├─ policy.py        write-time local/cloud placement rules
│  │  ├─ sync_service.py  connectivity monitor, push, pull, conflict resolve
│  │  ├─ metadata.py      Postgres access (devices / sync_events / conflicts)
│  │  ├─ activity.py      in-memory activity feed
│  │  └─ config.py        env-driven settings
│  ├─ demo.py             demo driver: reset · seed · conflict · status · proof
│  └─ requirements.txt
├─ dashboard/             Next.js dashboard (4 panels)
├─ infra/                 docker-compose (Qdrant + Postgres) + schema
├─ DEMO.md                step-by-step live demo guide
└─ edge-memory-platform-design.md   full design doc
```

---

## Quick start

Prerequisites: Python 3.10+, Node 18+, Docker Desktop.

**1. Cloud services** (Qdrant + Postgres):

```powershell
cd infra
docker compose up -d
```

**2. Edge agent** (the device):

```powershell
cd edge-agent
pip install -r requirements.txt          # first time only
$env:QDRANT_URL="http://localhost:6333"
$env:DATABASE_URL="postgresql://edge:edgepass@localhost:5432/edgememory"
python -m app.main
```

Wait for `Application startup complete`. The first run downloads a ~90MB
embedding model once (cached in `edge-agent/data/models`).

**3. Dashboard:**

```powershell
cd dashboard
npm install                              # first time only
npm run dev
```

Open **http://localhost:3000**.

### Offline-only mode (no Docker)

Skip step 1 and run the agent with metadata disabled — everything on-device still
works, sync just reports offline:

```powershell
cd edge-agent
$env:POSTGRES_ENABLED="false"
python -m app.main
```

---

## Demo

See **[DEMO.md](DEMO.md)** for the full narrative. The short version:

```powershell
cd edge-agent
python demo.py reset      # clean slate (then restart the agent)
python demo.py seed       # load rehearsed notes (local + cloud mix)
python demo.py conflict   # stage a conflict (local edit wins, logged)
python demo.py proof      # show server count + conflict audit trail
```

In the dashboard: add notes → search → click **Simulate offline** → search still
works → **Restore connectivity** → watch push/pull in the Activity Log → re-search
and see `mutable + immutable` shards merged.

---

## Configuration

All settings are environment variables (see `.env.example`). Common ones:

| Variable | Default | Meaning |
|---|---|---|
| `QDRANT_URL` | `http://localhost:6333` | cloud Qdrant server |
| `DATABASE_URL` | `postgresql://edge:edgepass@localhost:5432/edgememory` | metadata Postgres |
| `POSTGRES_ENABLED` | `true` | set `false` to run with no metadata DB |
| `FORCE_OFFLINE` | `false` | start the agent in simulated-offline mode |
| `EMBED_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | FastEmbed model (384-dim) |
| `COLLECTION_NAME` | `edge-collection` | server collection name |
| `SERVER_SHARD_ID` | `0` | per-device server shard to sync against |

Copy `edge-agent/.env` from `.env.example` if you'd rather not set env vars per
terminal.

---

## Design note on deployment

The edge agent runs **locally on purpose** — it is the edge device. Qdrant Edge is
an in-process library that stores shards on local disk, so it cannot run on
serverless platforms like Vercel. The cloud side (Qdrant Server + Postgres) can
be hosted anywhere; the dashboard is a static Next.js app. For the hackathon demo,
everything runs on one machine with the agent as the "device."
