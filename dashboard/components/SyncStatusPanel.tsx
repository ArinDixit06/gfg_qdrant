"use client";

import { useEffect, useRef, useState } from "react";
import type { StatusResponse } from "@/lib/api";
import { api } from "@/lib/api";

function ago(iso: string | null): string {
  if (!iso) return "never";
  const secs = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (secs < 60) return `${secs}s ago`;
  if (secs < 3600) return `${Math.round(secs / 60)}m ago`;
  return `${Math.round(secs / 3600)}h ago`;
}

const HISTORY_LEN = 40; // ~last few minutes at the 2s poll cadence

export default function SyncStatusPanel({
  status,
  connected,
  onAction,
}: {
  status: StatusResponse | null;
  connected: boolean;
  onAction: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [restoring, setRestoring] = useState(false);
  const [history, setHistory] = useState<boolean[]>([]);
  const lastPull = useRef<string | null>(null);
  const sync = status?.sync;
  const mem = status?.memory;
  const online = !!sync?.online;

  // Track connectivity over time for the sparkline.
  useEffect(() => {
    setHistory((h) => [...h, connected && online].slice(-HISTORY_LEN));
  }, [status, connected, online]);

  // Briefly show a snapshot-restore indicator when last_pull advances.
  useEffect(() => {
    if (sync?.last_pull && sync.last_pull !== lastPull.current) {
      if (lastPull.current !== null) {
        setRestoring(true);
        const t = window.setTimeout(() => setRestoring(false), 1800);
        return () => window.clearTimeout(t);
      }
      lastPull.current = sync.last_pull;
    }
  }, [sync?.last_pull]);

  const toggleOffline = async () => {
    if (!sync) return;
    setBusy(true);
    try {
      await api.setOffline(!sync.forced_offline);
      onAction();
    } finally {
      setBusy(false);
    }
  };

  const doPush = async () => {
    setBusy(true);
    try {
      await api.push();
      onAction();
    } finally {
      setBusy(false);
    }
  };

  const doPull = async () => {
    setBusy(true);
    setRestoring(true);
    try {
      await api.pull();
      onAction();
    } finally {
      setBusy(false);
      window.setTimeout(() => setRestoring(false), 1200);
    }
  };

  return (
    <section className="panel">
      <h2>Sync Status</h2>

      {!connected && (
        <div className="disconnected">
          Edge agent unreachable — process is down (this is the offline demo state).
        </div>
      )}

      <div className="row" style={{ marginTop: 4 }}>
        <span className="pill">
          <span className={`dot ${online ? "on" : "off"}`} />
          {online ? "ONLINE" : "OFFLINE"}
        </span>
        {sync?.forced_offline && <span className="pill pending">forced offline</span>}
        <span className="muted" style={{ marginLeft: "auto" }}>
          device: <span className="mono">{status?.device?.id ?? "—"}</span>
        </span>
      </div>

      <div className="sparkline" title="connectivity over the last few minutes">
        {history.map((up, i) => (
          <span key={i} className={`spark ${up ? "up" : "down"}`} />
        ))}
        {!history.length && <span className="muted">tracking connectivity…</span>}
      </div>

      {restoring && (
        <div className="restore-bar" title="Restoring immutable shard from server snapshot">
          <div className="restore-fill" />
          <span className="restore-label">restoring shard from snapshot…</span>
        </div>
      )}

      <div className="row" style={{ marginTop: 12, gap: 10 }}>
        <div className="stat">
          <span className="n">{mem?.local_points ?? "—"}</span>
          <span className="l">local points</span>
        </div>
        <div className="stat">
          <span className="n">{mem?.synced_points ?? "—"}</span>
          <span className="l">synced points</span>
        </div>
        <div className="stat">
          <span className="n">{mem?.pending_points ?? "—"}</span>
          <span className="l">pending push</span>
        </div>
        <div className="stat">
          <span className="n">{sync?.conflicts_total ?? "—"}</span>
          <span className="l">conflicts</span>
        </div>
      </div>

      <div className="item" style={{ marginTop: 12 }}>
        <div className="meta" style={{ marginTop: 0 }}>
          <span>last check: {ago(sync?.last_check ?? null)}</span>
          <span>last push: {ago(sync?.last_push ?? null)}</span>
          <span>last pull: {ago(sync?.last_pull ?? null)}</span>
        </div>
        <div className="meta">
          <span>pushed total: {sync?.pushed_total ?? 0}</span>
          <span>immutable shard: {mem?.immutable_available ? "restored" : "not yet"}</span>
          <span>metadata db: {status?.metadata_enabled ? "on" : "off"}</span>
        </div>
        {sync?.last_error && (
          <div className="meta" style={{ color: "var(--red)" }}>
            last error: {sync.last_error}
          </div>
        )}
      </div>

      <div className="row" style={{ marginTop: 12 }}>
        <button className={sync?.forced_offline ? "" : "danger"} onClick={toggleOffline} disabled={busy || !connected}>
          {sync?.forced_offline ? "Restore connectivity" : "Simulate offline"}
        </button>
        <button className="ghost" onClick={doPush} disabled={busy || !online}>
          Push now
        </button>
        <button className="ghost" onClick={doPull} disabled={busy || !online}>
          Pull now
        </button>
      </div>
    </section>
  );
}
