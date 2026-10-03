# Demo Guide — Edge Memory & Intelligence Platform

A ~4 minute live demo that proves: on-device vector memory, real offline search,
dynamic local/cloud data placement, bidirectional sync, and conflict handling.

---

## 0. Start everything (do this ~5 min before presenting)

Open **three terminals**.

**Terminal 1 — cloud (Qdrant + Postgres).** Start Docker Desktop first, wait ~30s, then:

```powershell
cd c:\Users\ARIN\OneDrive\Desktop\gfg_qdrant\infra
docker compose up -d
docker ps          # confirm edge-qdrant + edge-postgres are Up
```

**Terminal 2 — edge agent (the "device").**

```powershell
cd c:\Users\ARIN\OneDrive\Desktop\gfg_qdrant\edge-agent
$env:QDRANT_URL="http://localhost:6333"
$env:DATABASE_URL="postgresql://edge:edgepass@localhost:5432/edgememory"
python -m app.main
```

Wait for `Application startup complete`. (First run downloads a ~90MB model once.)

**Terminal 3 — dashboard.**

```powershell
cd c:\Users\ARIN\OneDrive\Desktop\gfg_qdrant\dashboard
npm run dev
```

Open **http://localhost:3000**. Confirm the green **"agent connected"** dot.

---

## 1. Clean slate before judges

Keep a fourth terminal for the demo driver. Reset, then restart the agent so it
re-opens empty shards:

```powershell
cd c:\Users\ARIN\OneDrive\Desktop\gfg_qdrant\edge-agent
python demo.py reset
# then Ctrl+C the agent in Terminal 2 and start it again
```

---

## 2. The live narrative

### Step 1 — Set the scene
"This is an edge device: a drone, kiosk, or robot. Memory's empty. Four panels —
what it remembers, search, sync status, and a live activity feed."

### Step 2 — Add memories (local embedding)
In **Memory Inspector**, type *"The delivery drone landed near the north gate"* → Add.
Point at the **Activity Log**: `embed` then `ingest`. "Embedded on the device. No API call."

> Shortcut: `python demo.py seed` loads 5 rehearsed items at once.

### Step 3 — Search instantly
In **Search Console**, query *"where did the drone land"*. Call out the latency
(single-digit ms) and `shards searched: mutable`. "On-device vector search."

### Step 4 — Dynamic local/cloud policy
The seed set includes a `sensor` item and a `private` note — both tagged
**`local_only`** in the Inspector. "Raw and private data never leave the device.
That decision is made at write time — the dynamic placement the problem asks for."

### Step 5 — Go offline (the hook)
Click **Simulate offline**. The dot flips to **OFFLINE**. Now:
- Add another note → still works.
- Search again → still returns in ~1 ms. "Zero network. Real offline, not a cache."
- Watch **pending push** climb.

### Step 6 — Reconnect (the payoff)
Click **Restore connectivity**. Narrate the **Activity Log** live: `sync` push + pull
events, **pending → 0**, **synced points** rises.

### Step 7 — The differentiator (dual-shard merge)
Re-run the search. Now `shards searched: mutable + immutable`. "Fresh local data
and synced cloud knowledge, merged in one query. That's the dual-shard design —
not just a local vector DB."

### Step 8 — Conflict handling
Run the conflict scenario:

```powershell
python demo.py conflict
```

The **Activity Log** shows `conflict … resolved: local_wins`. "Conflicts resolve by
timestamp and are logged, never silently dropped."

### Step 9 — Prove it's real (for skeptics)

```powershell
python demo.py proof
```

Shows the live server-side Qdrant point count and the conflict rows audited in
Postgres.

---

## Reset between runs

```powershell
python demo.py reset
# restart the agent (Terminal 2)
```

---

## Notes & honest caveats

- The **Simulate offline** button sets a `FORCE_OFFLINE` flag — the clean,
  repeatable way to demo. For an even more literal proof, disconnect Wi‑Fi
  instead: the connectivity monitor pings Qdrant and flips to offline within ~5s.
  The offline search runs with no network either way.
- The edge agent runs **locally on purpose** — it *is* the edge device. The cloud
  (Qdrant + Postgres) is the sync target it talks to when online.

## Quick API reference (if a judge asks)

- `GET  http://localhost:8000/status` — device + sync + memory snapshot
- `GET  http://localhost:8000/search?q=...` — merge search across both shards
- `GET  http://localhost:6333/dashboard` — Qdrant's own UI (cloud side)
