-- Durable task queue for the independent XinsW production website.
-- Apply to a dedicated Neon branch first; do not run against legacy website databases.

CREATE TABLE IF NOT EXISTS music_jobs (
    id UUID PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'awaiting_upload'
        CHECK (status IN ('awaiting_upload', 'queued', 'running', 'completed', 'failed', 'cancelled')),
    stage TEXT NOT NULL DEFAULT '等待上传',
    progress DOUBLE PRECISION NOT NULL DEFAULT 0
        CHECK (progress >= 0 AND progress <= 1),
    source_object_key TEXT NOT NULL,
    source_filename TEXT NOT NULL,
    source_content_type TEXT NOT NULL DEFAULT 'application/octet-stream',
    source_size_bytes BIGINT
        CHECK (source_size_bytes IS NULL OR source_size_bytes >= 0),
    options JSONB NOT NULL DEFAULT '{}'::jsonb,
    result JSONB,
    error TEXT,
    worker_id TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    max_attempts INTEGER NOT NULL DEFAULT 1 CHECK (max_attempts >= 1),
    lease_expires_at TIMESTAMPTZ,
    heartbeat_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    CHECK (
        (status = 'running' AND worker_id IS NOT NULL AND lease_expires_at IS NOT NULL)
        OR status <> 'running'
    )
);

CREATE INDEX IF NOT EXISTS music_jobs_queue_idx
    ON music_jobs (created_at, id)
    WHERE status = 'queued';

CREATE INDEX IF NOT EXISTS music_jobs_lease_idx
    ON music_jobs (lease_expires_at)
    WHERE status = 'running';

CREATE INDEX IF NOT EXISTS music_jobs_worker_idx
    ON music_jobs (worker_id, status, updated_at);

CREATE TABLE IF NOT EXISTS music_job_artifacts (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    job_id UUID NOT NULL REFERENCES music_jobs(id) ON DELETE CASCADE,
    object_key TEXT NOT NULL UNIQUE,
    file_name TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'result',
    content_type TEXT NOT NULL DEFAULT 'application/octet-stream',
    size_bytes BIGINT CHECK (size_bytes IS NULL OR size_bytes >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS music_job_artifacts_job_idx
    ON music_job_artifacts (job_id, created_at, id);

CREATE TABLE IF NOT EXISTS music_workers (
    worker_id TEXT PRIMARY KEY,
    instance_uuid TEXT UNIQUE,
    status TEXT NOT NULL DEFAULT 'starting'
        CHECK (status IN ('starting', 'idle', 'busy', 'stopping', 'stopped', 'error')),
    active_job_id UUID REFERENCES music_jobs(id) ON DELETE SET NULL,
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS music_workers_heartbeat_idx
    ON music_workers (status, last_seen_at);
