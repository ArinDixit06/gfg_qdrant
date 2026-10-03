"""Demo driver for the Edge Memory Platform.

One command to seed rehearsed data, stage the conflict scenario, reset to a
clean slate, or print the current state. Drives the running edge agent over
its HTTP API, and talks to Qdrant / Postgres directly for reset + proof.

Usage (agent must be running on http://127.0.0.1:8000):
    python demo.py reset      # wipe local shards + server collection + metadata
    python demo.py seed       # load a clean set of notes (local + policy mix)
    python demo.py conflict   # push, edit same point, push again -> conflict
    python demo.py status     # print device / sync / memory state
    python demo.py proof      # show server point count + logged conflicts

Flags:
    --api   http://127.0.0.1:8000   edge agent base URL
    --qdrant http://localhost:6333  qdrant server URL
"""
from __future__ import annotations

import argparse
import sys
import time
from typing import Any, Dict, List, Optional

import requests

CONFLICT_ID = "aaaaaaaa-0000-0000-0000-000000000001"

# A rehearsed set that shows: normal notes (sync), a derived summary (sync),
# raw sensor data (local-only), and a private note (local-only).
SEED_ITEMS: List[Dict[str, Any]] = [
    {"content": "The delivery drone landed near the north gate at 14:05", "category": "note"},
    {"content": "Warehouse aisle 7 restocked with 40 units of SKU-2211", "category": "note"},
    {"content": "Daily summary: 312 packages scanned, 3 flagged for review", "category": "summary"},
    {"content": "raw lidar frame 0x4211 burst payload", "category": "sensor"},
    {"content": "Gate access code for operator shift B", "category": "note", "private": True},
]


class Demo:
    def __init__(self, api: str, qdrant: str) -> None:
        self.api = api.rstrip("/")
        self.qdrant = qdrant.rstrip("/")

    # ---- helpers ---------------------------------------------------------

    def _get(self, path: str) -> Dict[str, Any]:
        r = requests.get(f"{self.api}{path}", timeout=10)
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        r = requests.post(f"{self.api}{path}", json=body or {}, timeout=30)
        r.raise_for_status()
        return r.json()

    def _agent_up(self) -> bool:
        try:
            self._get("/health")
            return True
        except Exception:
            return False

    def _collection_name(self) -> str:
        # Mirror the agent's default; override via env if you changed it.
        import os

        return os.environ.get("COLLECTION_NAME", "edge-collection")

    # ---- commands --------------------------------------------------------

    def status(self) -> None:
        if not self._agent_up():
            print("Agent is DOWN at", self.api)
            return
        s = self._get("/status")
        sync = s["sync"]
        mem = s["memory"]
        print(f"device        : {s['device']['name']} ({s['device']['id']})")
        print(f"online        : {sync['online']}  (forced_offline={sync['forced_offline']})")
        print(f"local points  : {mem['local_points']}")
        print(f"synced points : {mem['synced_points']}")
        print(f"pending push  : {mem['pending_points']}")
        print(f"conflicts     : {sync['conflicts_total']}")
        print(f"immutable shard restored : {mem['immutable_available']}")
        print(f"metadata db   : {s['metadata_enabled']}")

    def reset(self) -> None:
        # 1) server collection
        col = self._collection_name()
        try:
            requests.delete(f"{self.qdrant}/collections/{col}", timeout=10)
            print(f"deleted server collection '{col}'")
        except Exception as exc:
            print(f"server collection delete skipped: {exc}")

        # 2) local shard data (requires agent stopped to fully clear; we clear
        #    what we can via filesystem relative to this script)
        import shutil
        from pathlib import Path

        shard_root = Path(__file__).parent / "data"
        # keep the model cache, drop device shard data
        for sub in shard_root.glob("*"):
            if sub.name == "models":
                continue
            shutil.rmtree(sub, ignore_errors=True)
            print(f"removed local shard dir: {sub.name}")

        # 3) postgres metadata (best-effort via docker)
        import subprocess

        try:
            subprocess.run(
                [
                    "docker", "exec", "edge-postgres", "psql", "-U", "edge",
                    "-d", "edgememory", "-c",
                    "TRUNCATE conflicts, sync_events RESTART IDENTITY;",
                ],
                check=False, capture_output=True, timeout=15,
            )
            print("truncated postgres conflicts + sync_events")
        except Exception as exc:
            print(f"postgres truncate skipped: {exc}")

        print("\nRESET done. Restart the edge agent to re-open clean shards.")

    def seed(self) -> None:
        if not self._agent_up():
            print("Agent is DOWN — start it first.")
            sys.exit(1)
        for item in SEED_ITEMS:
            res = self._post("/ingest", item)
            tag = "private" if item.get("private") else item["category"]
            print(f"  + [{tag:7}] {item['content'][:50]}  -> {res['placement']['reason']}")
        print(f"\nseeded {len(SEED_ITEMS)} items.")
        self.status()

    def conflict(self) -> None:
        if not self._agent_up():
            print("Agent is DOWN — start it first.")
            sys.exit(1)
        if not self._get("/status")["sync"]["online"]:
            print("Agent is OFFLINE — restore connectivity before the conflict demo.")
            sys.exit(1)

        print("1) create a note with a fixed id and push it to the cloud")
        self._post("/ingest", {
            "content": "Meeting notes: launch on Friday",
            "category": "note",
            "point_id": CONFLICT_ID,
        })
        print("   push:", self._post("/sync/push"))
        time.sleep(1)

        print("2) edit the SAME id locally (newer timestamp) and push again")
        self._post("/ingest", {
            "content": "Meeting notes: launch MOVED to Monday",
            "category": "note",
            "point_id": CONFLICT_ID,
        })
        print("   push:", self._post("/sync/push"))
        time.sleep(1)
        print("\nconflict staged. Check the Activity Log (conflict ... local_wins)")
        self.proof()

    def proof(self) -> None:
        col = self._collection_name()
        try:
            r = requests.post(
                f"{self.qdrant}/collections/{col}/points/count",
                json={"exact": True}, timeout=10,
            )
            count = r.json().get("result", {}).get("count", "?")
            print(f"server collection '{col}' point count: {count}")
        except Exception as exc:
            print(f"server count unavailable: {exc}")

        import subprocess

        try:
            out = subprocess.run(
                [
                    "docker", "exec", "edge-postgres", "psql", "-U", "edge",
                    "-d", "edgememory", "-c",
                    "SELECT point_id, resolution FROM conflicts ORDER BY resolved_at DESC LIMIT 5;",
                ],
                check=False, capture_output=True, text=True, timeout=15,
            )
            print(out.stdout.strip() or "(no conflicts logged yet)")
        except Exception as exc:
            print(f"postgres read skipped: {exc}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Edge Memory Platform demo driver")
    parser.add_argument("command", choices=["reset", "seed", "conflict", "status", "proof"])
    parser.add_argument("--api", default="http://127.0.0.1:8000")
    parser.add_argument("--qdrant", default="http://localhost:6333")
    args = parser.parse_args()

    demo = Demo(args.api, args.qdrant)
    getattr(demo, args.command)()


if __name__ == "__main__":
    main()
