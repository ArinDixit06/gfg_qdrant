"use client";

import type { ActivityEvent } from "@/lib/api";

function time(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString();
  } catch {
    return iso;
  }
}

export default function ActivityLog({ events }: { events: ActivityEvent[] }) {
  const ordered = [...events].sort((a, b) => b.seq - a.seq);
  return (
    <section className="panel">
      <h2>Activity Log</h2>
      <div className="list" style={{ marginTop: 0 }}>
        {ordered.map((e) => (
          <div className="log-line" key={e.seq}>
            <span className="muted">{time(e.ts)}</span>
            <span className={`kind ${e.kind}`}>{e.kind}</span>
            <span>{e.message}</span>
          </div>
        ))}
        {!events.length && <div className="muted">Waiting for activity…</div>}
      </div>
    </section>
  );
}
