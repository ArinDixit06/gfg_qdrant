// Client for the edge agent's FastAPI. Everything is best-effort: when the
// agent is unreachable (process killed for the offline demo) calls reject and
// the UI shows a disconnected state.

const BASE =
  process.env.NEXT_PUBLIC_EDGE_API?.replace(/\/$/, "") || "http://127.0.0.1:8000";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    cache: "no-store",
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json() as Promise<T>;
}

export type Placement = {
  keep_local: boolean;
  sync_to_cloud: boolean;
  reason: string;
};

export type MemoryPoint = {
  id: string;
  shard: "mutable" | "immutable";
  score?: number;
  payload: {
    content?: string;
    origin?: string;
    sync_state?: string;
    category?: string;
    private?: boolean;
    created_at?: string;
    updated_at?: string;
    placement_reason?: string;
    device_id?: string;
  };
};

export type SearchResult = {
  query: string;
  results: (MemoryPoint & { score: number })[];
  shards_searched: string[];
  took_ms: number;
};

export type SyncStatus = {
  online: boolean;
  forced_offline: boolean;
  last_check: string | null;
  last_push: string | null;
  last_pull: string | null;
  last_error: string | null;
  pushed_total: number;
  pulled_total: number;
  conflicts_total: number;
};

export type Stats = {
  local_points: number;
  synced_points: number;
  pending_points: number;
  immutable_available: boolean;
};

export type StatusResponse = {
  device: { id: string; name: string };
  sync: SyncStatus;
  memory: Stats;
  metadata_enabled: boolean;
};

export type ActivityEvent = {
  seq: number;
  ts: string;
  kind: string;
  message: string;
  detail: Record<string, unknown>;
};

export const api = {
  status: () => req<StatusResponse>("/status"),
  activity: (afterSeq?: number) =>
    req<{ events: ActivityEvent[] }>(
      `/activity?limit=200${afterSeq ? `&after_seq=${afterSeq}` : ""}`
    ),
  memory: (origin?: string, category?: string) => {
    const p = new URLSearchParams({ limit: "200" });
    if (origin) p.set("origin", origin);
    if (category) p.set("category", category);
    return req<{ points: MemoryPoint[]; count: number }>(`/memory?${p}`);
  },
  search: (q: string, origin?: string) => {
    const p = new URLSearchParams({ q, limit: "10" });
    if (origin) p.set("origin", origin);
    return req<SearchResult>(`/search?${p}`);
  },
  ingest: (content: string, category: string, priv: boolean) =>
    req<{ ok: boolean; id: string; placement: Placement }>("/ingest", {
      method: "POST",
      body: JSON.stringify({ content, category, private: priv }),
    }),
  setOffline: (forced: boolean) =>
    req<{ forced_offline: boolean }>("/sync/offline", {
      method: "POST",
      body: JSON.stringify({ forced_offline: forced }),
    }),
  push: () => req<{ ok: boolean; pushed?: number; reason?: string }>("/sync/push", { method: "POST" }),
  pull: () => req<{ ok: boolean; reason?: string }>("/sync/pull", { method: "POST" }),
  conflicts: () =>
    req<{ conflicts: Record<string, unknown>[] }>("/conflicts"),
};
