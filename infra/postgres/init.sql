-- Metadata store for the Edge Memory Platform.
-- This holds OPERATIONAL state only, never vector data.

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS devices (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL,
    last_seen   TIMESTAMPTZ,
    status      TEXT NOT NULL DEFAULT 'offline' CHECK (status IN ('online', 'offline')),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sync_events (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    device_id      UUID REFERENCES devices(id) ON DELETE CASCADE,
    started_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at    TIMESTAMPTZ,
    points_pushed  INT NOT NULL DEFAULT 0,
    points_pulled  INT NOT NULL DEFAULT 0,
    duration_ms    INT,
    status         TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'success', 'failed'))
);

CREATE TABLE IF NOT EXISTS conflicts (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    point_id           TEXT NOT NULL,
    device_id          UUID REFERENCES devices(id) ON DELETE CASCADE,
    local_value        TEXT,
    server_value       TEXT,
    local_updated_at   TIMESTAMPTZ,
    server_updated_at  TIMESTAMPTZ,
    resolution         TEXT NOT NULL CHECK (resolution IN ('local_wins', 'server_wins')),
    resolved_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sync_events_device ON sync_events(device_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_conflicts_device   ON conflicts(device_id, resolved_at DESC);
