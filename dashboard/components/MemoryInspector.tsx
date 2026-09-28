"use client";

import { useEffect, useState } from "react";
import type { MemoryPoint } from "@/lib/api";
import { api } from "@/lib/api";

const CATEGORIES = ["note", "summary", "sensor", "log"];

export default function MemoryInspector({
  refreshKey,
  onIngest,
}: {
  refreshKey: number;
  onIngest: () => void;
}) {
  const [points, setPoints] = useState<MemoryPoint[]>([]);
  const [originFilter, setOriginFilter] = useState<string>("");
  const [content, setContent] = useState("");
  const [category, setCategory] = useState("note");
  const [priv, setPriv] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const load = async () => {
    try {
      const res = await api.memory(originFilter || undefined);
      setPoints(res.points);
      setErr(null);
    } catch (e) {
      setErr(String(e));
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [originFilter, refreshKey]);

  const add = async () => {
    if (!content.trim()) return;
    setBusy(true);
    try {
      await api.ingest(content.trim(), category, priv);
      setContent("");
      setPriv(false);
      onIngest();
      await load();
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="panel">
      <h2>Memory Inspector</h2>

      <div className="row">
        <input
          style={{ flex: 1, minWidth: 180 }}
          placeholder="Add a memory (embedded locally)…"
          value={content}
          onChange={(e) => setContent(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && add()}
        />
        <select value={category} onChange={(e) => setCategory(e.target.value)}>
          {CATEGORIES.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
        <label className="row" style={{ gap: 4 }}>
          <input
            type="checkbox"
            checked={priv}
            onChange={(e) => setPriv(e.target.checked)}
            style={{ width: 16 }}
          />
          <span className="muted">private</span>
        </label>
        <button onClick={add} disabled={busy}>
          Add
        </button>
      </div>

      <div className="row" style={{ marginTop: 10 }}>
        <span className="muted">filter:</span>
        {["", "local", "synced"].map((o) => (
          <button
            key={o || "all"}
            className={originFilter === o ? "" : "ghost"}
            onClick={() => setOriginFilter(o)}
          >
            {o || "all"}
          </button>
        ))}
        <span className="muted" style={{ marginLeft: "auto" }}>
          {points.length} points
        </span>
      </div>

      {err && <div className="disconnected" style={{ marginTop: 8 }}>{err}</div>}

      <div className="list">
        {points.map((p) => (
          <div className="item" key={`${p.shard}-${p.id}`}>
            <div>{p.payload.content ?? <span className="muted">(no content)</span>}</div>
            <div className="meta">
              <span className={`pill ${p.payload.origin === "synced" ? "synced" : "local"}`}>
                {p.payload.origin ?? "?"}
              </span>
              <span className={`pill ${p.payload.sync_state ?? ""}`}>
                {p.payload.sync_state ?? "?"}
              </span>
              <span>{p.payload.category}</span>
              {p.payload.private && <span className="pill pending">private</span>}
              <span className="mono">{String(p.id).slice(0, 8)}</span>
            </div>
          </div>
        ))}
        {!points.length && !err && <div className="muted">No memories yet.</div>}
      </div>
    </section>
  );
}
