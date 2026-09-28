"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { ActivityEvent, StatusResponse } from "@/lib/api";
import { api } from "@/lib/api";
import SyncStatusPanel from "@/components/SyncStatusPanel";
import MemoryInspector from "@/components/MemoryInspector";
import SearchConsole from "@/components/SearchConsole";
import ActivityLog from "@/components/ActivityLog";

export default function Home() {
  const [status, setStatus] = useState<StatusResponse | null>(null);
  const [connected, setConnected] = useState(false);
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [refreshKey, setRefreshKey] = useState(0);
  const lastSeq = useRef(0);

  const poll = useCallback(async () => {
    try {
      const s = await api.status();
      setStatus(s);
      setConnected(true);
    } catch {
      setConnected(false);
    }
    try {
      const a = await api.activity(lastSeq.current || undefined);
      if (a.events.length) {
        setEvents((prev) => {
          const merged = [...prev, ...a.events];
          const maxSeq = Math.max(...merged.map((e) => e.seq));
          lastSeq.current = maxSeq;
          // keep last 300 events
          return merged.slice(-300);
        });
      }
    } catch {
      /* agent down: keep last known events */
    }
  }, []);

  useEffect(() => {
    poll();
    const id = setInterval(poll, 2000);
    return () => clearInterval(id);
  }, [poll]);

  const bump = () => {
    setRefreshKey((k) => k + 1);
    poll();
  };

  return (
    <>
      <header className="header">
        <div>
          <h1>Edge Memory & Intelligence Platform</h1>
          <div className="sub">
            Offline-first vector memory on Qdrant Edge · dual-shard merge search · cloud sync
          </div>
        </div>
        <span className="pill">
          <span className={`dot ${connected ? "on" : "off"}`} />
          {connected ? "agent connected" : "agent down"}
        </span>
      </header>

      <div className="grid">
        <MemoryInspector refreshKey={refreshKey} onIngest={bump} />
        <SearchConsole />
        <SyncStatusPanel status={status} connected={connected} onAction={bump} />
        <ActivityLog events={events} />
      </div>
    </>
  );
}
