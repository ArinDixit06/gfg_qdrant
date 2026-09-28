"use client";

import { useState } from "react";
import type { StatusResponse } from "@/lib/api";
import { api } from "@/lib/api";

function ago(iso: string | null): string {
  if (!iso) return "never";
  const secs = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (secs < 60) return `${secs}s ago`;
  if (secs < 3600) return `${Math.round(secs / 60)}m ago`;
  return `${Math.round(secs / 3600)}h ago`;
}

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
  const sync = status?.sync;
  const mem = status?.memory;
  const online = !!sync?.online;

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
    try {
      await api.pull();
      onAction();
    } finally {
      setBusy(false);
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
        <span className="muted">device: {status?.device?.name ?? "—"}</span>
      </div>

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
