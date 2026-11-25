-- Single-use, short-lived bootstrap credentials for newly started AutoDL workers.
-- The GPU startup command carries only this one-time token, never the long-lived worker API token.

CREATE TABLE IF NOT EXISTS music_worker_bootstrap_tokens (
    token_hash TEXT PRIMARY KEY CHECK (length(token_hash) = 64),
    worker_id TEXT NOT NULL REFERENCES music_workers(worker_id) ON DELETE CASCADE,
    instance_uuid TEXT,
    expires_at TIMESTAMPTZ NOT NULL,
    used_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS music_worker_bootstrap_expiry_idx
    ON music_worker_bootstrap_tokens (expires_at)
    WHERE used_at IS NULL;
