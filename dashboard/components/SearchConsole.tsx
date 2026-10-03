"use client";

import { useState } from "react";
import type { SearchResult } from "@/lib/api";
import { api } from "@/lib/api";

// Representative cost of the SAME query against a remote Qdrant Server: a
// typical mobile/edge network round-trip (~250ms) plus the remote search
// itself. This is an estimate, labeled as such — the point is the order of
// magnitude difference, which is the whole reason edge search exists.
const NETWORK_RTT_MS = 250;
function cloudEstimateMs(localMs: number): number {
  return Math.round(NETWORK_RTT_MS + localMs * 1.2);
}

export default function SearchConsole() {
  const [q, setQ] = useState("");
  const [origin, setOrigin] = useState("");
  const [res, setRes] = useState<SearchResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const run = async () => {
    if (!q.trim()) return;
    setBusy(true);
    setErr(null);
    try {
      const r = await api.search(q.trim(), origin || undefined);
      setRes(r);
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="panel">
      <h2>Search Console</h2>

      <div className="row">
        <input
          style={{ flex: 1, minWidth: 180 }}
          placeholder="Semantic query (embedded locally, merged across shards)…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && run()}
        />
        <select value={origin} onChange={(e) => setOrigin(e.target.value)}>
          <option value="">both shards</option>
          <option value="local">local only</option>
          <option value="synced">synced only</option>
        </select>
        <button onClick={run} disabled={busy}>
          Search
        </button>
      </div>

      {res && (
        <>
          <div className="row" style={{ marginTop: 10 }}>
            <span className="muted">
              {res.results.length} hits across{" "}
              {res.shards_searched.join(" + ") || "no shards"}
            </span>
          </div>
          <div className="latency-compare">
            <div className="lat edge">
              <span className="lat-n">{res.took_ms}<small> ms</small></span>
              <span className="lat-l">on-device (Qdrant Edge)</span>
            </div>
            <span className="lat-vs">vs</span>
            <div className="lat cloud">
              <span className="lat-n">~{cloudEstimateMs(res.took_ms)}<small> ms</small></span>
              <span className="lat-l">cloud round-trip (est.)</span>
            </div>
            <span className="lat-speedup">
              {Math.round(cloudEstimateMs(res.took_ms) / Math.max(res.took_ms, 0.5))}× faster
            </span>
          </div>
        </>
      )}

      {err && <div className="disconnected" style={{ marginTop: 8 }}>{err}</div>}

      <div className="list">
        {res?.results.map((r) => (
          <div className="item" key={`${r.shard}-${r.id}`}>
            <div>{r.payload.content ?? <span className="muted">(no content)</span>}</div>
            <div className="meta">
              <span className="score">{r.score.toFixed(4)}</span>
              <span className={`pill ${r.shard === "immutable" ? "synced" : "local"}`}>
                {r.shard === "immutable" ? "synced shard" : "local shard"}
              </span>
              <span>{r.payload.category}</span>
              <span className="mono">{String(r.id).slice(0, 8)}</span>
            </div>
          </div>
        ))}
        {res && !res.results.length && <div className="muted">No matches.</div>}
        {!res && !err && <div className="muted">Run a query to search device memory.</div>}
      </div>
    </section>
  );
}
