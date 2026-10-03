"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

type Conflict = {
  point_id: string;
  local_value?: string;
  server_value?: string;
  local_updated_at?: string;
  server_updated_at?: string;
  resolution?: string;
  resolved_at?: string;
};

export default function ConflictsPanel({ refreshKey }: { refreshKey: number }) {
  const [conflicts, setConflicts] = useState<Conflict[]>([]);
  const [err, setErr] = useState<string | null>(null);

  const load = async () => {
    try {
      const res = await api.conflicts();
      setConflicts(res.conflicts as unknown as Conflict[]);
      setErr(null);
    } catch (e) {
      setErr(String(e));
    }
  };

  useEffect(() => {
    load();
    const id = setInterval(load, 3000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshKey]);

  return (
    <section className="panel">
      <div className="panel-head">
        <h2>Conflicts</h2>
        <span className="muted">{conflicts.length} resolved</span>
      </div>

      {err && <div className="disconnected" style={{ marginTop: 8 }}>{err}</div>}

      <div className="list">
        {conflicts.map((c, i) => {
          const localWins = (c.resolution || "").startsWith("local");
          return (
            <div className="item" key={`${c.point_id}-${i}`}>
              <div className="row" style={{ justifyContent: "space-between" }}>
                <span className="mono">{String(c.point_id).slice(0, 8)}</span>
                <span className={`pill ${localWins ? "local" : "synced"}`}>
                  {c.resolution}
                </span>
              </div>
              <div className="diff">
                <div className={`diff-row ${localWins ? "win" : "lose"}`}>
                  <span className="diff-side">local</span>
                  <span className="diff-val">{c.local_value || "—"}</span>
                </div>
                <div className={`diff-row ${localWins ? "lose" : "win"}`}>
                  <span className="diff-side">server</span>
                  <span className="diff-val">{c.server_value || "—"}</span>
                </div>
              </div>
            </div>
          );
        })}
        {!conflicts.length && !err && (
          <div className="muted">
            No conflicts yet. Edit the same note while offline, then reconnect.
          </div>
        )}
      </div>
    </section>
  );
}
