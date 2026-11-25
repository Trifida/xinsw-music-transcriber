# -*- coding: utf-8 -*-
"""PostgreSQL-backed durable queue for cloud transcription jobs.

The API owns this store. GPU workers never connect directly to Postgres; they
use authenticated internal HTTP endpoints and short-lived object URLs.
"""
from __future__ import annotations

import json
import os
from typing import Any, Callable, TypeVar
from uuid import UUID


class JobStoreError(RuntimeError):
    """A durable job-store operation failed."""


class DispatchCapacityError(RuntimeError):
    """The dispatcher is already running or the configured worker cap is full."""


_T = TypeVar("_T")


class PostgresJobStore:
    def __init__(self, dsn: str | None = None, *, connect_timeout: int = 8) -> None:
        self._dsn = (dsn or os.environ.get("DATABASE_URL", "")).strip()
        if not self._dsn:
            raise ValueError("DATABASE_URL is required for cloud job storage.")
        self._connect_timeout = max(1, int(connect_timeout))

    def _connect(self):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:  # pragma: no cover - depends on deployment extra
            raise JobStoreError("Cloud jobs require psycopg[binary].") from exc
        return psycopg.connect(
            self._dsn,
            connect_timeout=self._connect_timeout,
            row_factory=dict_row,
        )

    @staticmethod
    def _uuid(value: str | UUID) -> UUID:
        try:
            return value if isinstance(value, UUID) else UUID(str(value))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("Invalid job_id.") from exc

    def create_job(
        self,
        job_id: str | UUID,
        *,
        source_object_key: str,
        source_filename: str,
        source_content_type: str,
        options: dict[str, Any] | None = None,
        max_attempts: int = 2,
    ) -> dict:
        if not source_object_key or not source_filename:
            raise ValueError("A source object key and filename are required.")
        if not 1 <= int(max_attempts) <= 5:
            raise ValueError("max_attempts must be between 1 and 5.")
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO music_jobs
                    (id, source_object_key, source_filename, source_content_type,
                     options, max_attempts)
                VALUES (%s, %s, %s, %s, %s::jsonb, %s)
                RETURNING *
                """,
                (
                    self._uuid(job_id), source_object_key, source_filename,
                    source_content_type or "application/octet-stream",
                    json.dumps(options or {}, ensure_ascii=False), int(max_attempts),
                ),
            )
            row = cur.fetchone()
        if row is None:
            raise JobStoreError("The job record was not created.")
        return row

    def mark_upload_complete(self, job_id: str | UUID, size_bytes: int) -> bool:
        if int(size_bytes) < 0:
            raise ValueError("size_bytes cannot be negative.")
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE music_jobs
                SET status = 'queued', stage = '排队中', source_size_bytes = %s,
                    updated_at = now()
                WHERE id = %s AND status = 'awaiting_upload'
                RETURNING id
                """,
                (int(size_bytes), self._uuid(job_id)),
            )
            return cur.fetchone() is not None

    def get_job(self, job_id: str | UUID) -> dict | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM music_jobs WHERE id = %s", (self._uuid(job_id),))
            return cur.fetchone()

    def claim_next(self, worker_id: str, *, lease_seconds: int = 180) -> dict | None:
        worker = str(worker_id).strip()
        if not worker or len(worker) > 128:
            raise ValueError("worker_id must contain 1–128 characters.")
        lease = max(30, min(int(lease_seconds), 900))
        with self._connect() as conn, conn.cursor() as cur:
            # Serialize claim against idle-shutdown reservation. A worker already
            # marked stopping must never acquire another queued job.
            cur.execute(
                "SELECT status, active_job_id FROM music_workers WHERE worker_id = %s FOR UPDATE",
                (worker,),
            )
            worker_row = cur.fetchone()
            if worker_row and (
                worker_row["status"] not in {"starting", "idle"}
                or worker_row.get("active_job_id") is not None
            ):
                return None
            # Exhausted leases become terminal failures; retryable expired leases
            # are reclaimed by the same atomic SKIP LOCKED statement below.
            cur.execute(
                """
                WITH expired AS (
                    UPDATE music_jobs
                    SET status = 'failed', stage = '处理失败',
                        error = COALESCE(error, 'GPU worker lease expired; retry limit reached'),
                        completed_at = now(), updated_at = now(),
                        lease_expires_at = NULL
                    WHERE status = 'running' AND lease_expires_at < now()
                      AND attempt_count >= max_attempts
                    RETURNING id, worker_id
                )
                UPDATE music_workers AS w
                SET status = 'idle', active_job_id = NULL,
                    last_seen_at = now(), updated_at = now()
                FROM expired AS e
                WHERE w.worker_id = e.worker_id AND w.active_job_id = e.id
                """
            )
            cur.execute(
                """
                WITH candidate AS (
                    SELECT id, worker_id AS previous_worker_id
                    FROM music_jobs
                    WHERE status = 'queued'
                       OR (status = 'running' AND lease_expires_at < now()
                           AND attempt_count < max_attempts)
                    ORDER BY created_at, id
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                UPDATE music_jobs AS j
                SET status = 'running',
                    worker_id = %s,
                    attempt_count = j.attempt_count + 1,
                    stage = 'GPU 工作节点已领取任务',
                    lease_expires_at = now() + (%s * interval '1 second'),
                    heartbeat_at = now(),
                    started_at = COALESCE(j.started_at, now()),
                    updated_at = now()
                FROM candidate
                WHERE j.id = candidate.id
                RETURNING j.id, j.source_object_key, j.source_filename,
                          j.source_content_type, j.options, j.attempt_count,
                          j.lease_expires_at, candidate.previous_worker_id
                """,
                (worker, lease),
            )
            job = cur.fetchone()
            if job is not None:
                previous_worker = job.get("previous_worker_id")
                if previous_worker and previous_worker != worker:
                    cur.execute(
                        """
                        UPDATE music_workers
                        SET status = 'idle', active_job_id = NULL,
                            last_seen_at = now(), updated_at = now()
                        WHERE worker_id = %s AND active_job_id = %s
                        """,
                        (previous_worker, job["id"]),
                    )
                cur.execute(
                    """
                    INSERT INTO music_workers (worker_id, status, active_job_id)
                    VALUES (%s, 'busy', %s)
                    ON CONFLICT (worker_id) DO UPDATE
                    SET status = 'busy', active_job_id = EXCLUDED.active_job_id,
                        last_seen_at = now(), updated_at = now()
                    """,
                    (worker, job["id"]),
                )
            return job

    def heartbeat_job(
        self,
        job_id: str | UUID,
        worker_id: str,
        *,
        progress: float,
        stage: str,
        lease_seconds: int = 180,
    ) -> bool:
        value = max(0.0, min(1.0, float(progress)))
        lease = max(30, min(int(lease_seconds), 900))
        label = str(stage or "处理中")[:200]
        worker = str(worker_id).strip()
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE music_jobs
                SET progress = %s, stage = %s, heartbeat_at = now(),
                    lease_expires_at = now() + (%s * interval '1 second'),
                    updated_at = now()
                WHERE id = %s AND worker_id = %s AND status = 'running'
                RETURNING id
                """,
                (value, label, lease, self._uuid(job_id), worker),
            )
            updated = cur.fetchone() is not None
            if updated:
                cur.execute(
                    """
                    UPDATE music_workers
                    SET last_seen_at = now(), updated_at = now(), status = 'busy'
                    WHERE worker_id = %s
                    """,
                    (worker,),
                )
            return updated

    def register_worker(self, worker_id: str, instance_uuid: str | None = None) -> dict:
        worker = str(worker_id).strip()
        if not worker or len(worker) > 128:
            raise ValueError("worker_id must contain 1–128 characters.")
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO music_workers (worker_id, instance_uuid, status)
                VALUES (%s, %s, 'idle')
                ON CONFLICT (worker_id) DO UPDATE
                SET instance_uuid = COALESCE(EXCLUDED.instance_uuid, music_workers.instance_uuid),
                    status = 'idle', last_seen_at = now(), updated_at = now()
                WHERE music_workers.status IN ('starting', 'idle')
                RETURNING *
                """,
                (worker, instance_uuid),
            )
            row = cur.fetchone()
        if row is None:
            raise JobStoreError("The worker record was not created.")
        return row

    def heartbeat_worker(self, worker_id: str, status: str) -> bool:
        """Accept worker liveness only while it is not being stopped/released."""
        if status not in {"idle", "busy"}:
            raise ValueError("Worker heartbeat status must be idle or busy.")
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE music_workers
                SET status = %s, last_seen_at = now(), updated_at = now()
                WHERE worker_id = %s
                  AND status IN ('starting', 'idle', 'busy')
                  AND (
                      (%s = 'idle' AND active_job_id IS NULL)
                      OR (%s = 'busy' AND active_job_id IS NOT NULL)
                  )
                RETURNING worker_id
                """,
                (status, str(worker_id).strip(), status, status),
            )
            return cur.fetchone() is not None

    def set_worker_status(self, worker_id: str, status: str) -> bool:
        allowed = {"starting", "idle", "busy", "stopping", "stopped", "error"}
        if status not in allowed:
            raise ValueError("Invalid worker status.")
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE music_workers
                SET status = %s, last_seen_at = now(), updated_at = now(),
                    active_job_id = CASE WHEN %s IN ('idle','stopped','error')
                                         THEN NULL ELSE active_job_id END
                WHERE worker_id = %s
                RETURNING worker_id
                """,
                (status, status, str(worker_id).strip()),
            )
            return cur.fetchone() is not None

    def add_artifact(
        self,
        job_id: str | UUID,
        worker_id: str,
        *,
        object_key: str,
        file_name: str,
        role: str = "result",
        content_type: str = "application/octet-stream",
        size_bytes: int | None = None,
    ) -> dict:
        if not object_key or not file_name:
            raise ValueError("An artifact object key and filename are required.")
        if size_bytes is not None and int(size_bytes) < 0:
            raise ValueError("size_bytes cannot be negative.")
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO music_job_artifacts
                    (job_id, object_key, file_name, role, content_type, size_bytes)
                SELECT j.id, %s, %s, %s, %s, %s
                FROM music_jobs AS j
                WHERE j.id = %s AND j.worker_id = %s AND j.status = 'running'
                RETURNING *
                """,
                (
                    object_key, file_name, str(role)[:40],
                    content_type or "application/octet-stream",
                    int(size_bytes) if size_bytes is not None else None,
                    self._uuid(job_id), str(worker_id).strip(),
                ),
            )
            row = cur.fetchone()
        if row is None:
            raise JobStoreError("The worker does not own this running job.")
        return row

    def list_artifacts(self, job_id: str | UUID) -> list[dict]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, object_key, file_name, role, content_type, size_bytes, created_at
                FROM music_job_artifacts WHERE job_id = %s ORDER BY id
                """,
                (self._uuid(job_id),),
            )
            return list(cur.fetchall())

    def complete_job(
        self, job_id: str | UUID, worker_id: str, result: dict[str, Any] | None = None
    ) -> bool:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE music_jobs
                SET status = 'completed', progress = 1, stage = '处理完成',
                    result = %s::jsonb, error = NULL, completed_at = now(),
                    lease_expires_at = NULL, updated_at = now()
                WHERE id = %s AND worker_id = %s AND status = 'running'
                RETURNING id
                """,
                (
                    json.dumps(result or {}, ensure_ascii=False),
                    self._uuid(job_id), str(worker_id).strip(),
                ),
            )
            updated = cur.fetchone() is not None
            if updated:
                cur.execute(
                    """
                    UPDATE music_workers
                    SET status = 'idle', active_job_id = NULL,
                        last_seen_at = now(), updated_at = now()
                    WHERE worker_id = %s
                    """,
                    (str(worker_id).strip(),),
                )
            return updated

    def fail_job(
        self,
        job_id: str | UUID,
        worker_id: str,
        error: str,
        *,
        retryable: bool = False,
    ) -> str | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE music_jobs
                SET status = CASE
                        WHEN %s AND attempt_count < max_attempts THEN 'queued'
                        ELSE 'failed'
                    END,
                    stage = CASE
                        WHEN %s AND attempt_count < max_attempts THEN '重新排队'
                        ELSE '处理失败'
                    END,
                    error = %s, worker_id = NULL,
                    lease_expires_at = NULL, heartbeat_at = now(),
                    completed_at = CASE
                        WHEN %s AND attempt_count < max_attempts THEN NULL
                        ELSE now()
                    END,
                    updated_at = now()
                WHERE id = %s AND worker_id = %s AND status = 'running'
                RETURNING status
                """,
                (
                    bool(retryable), bool(retryable), str(error)[:1000],
                    bool(retryable), self._uuid(job_id), str(worker_id).strip(),
                ),
            )
            row = cur.fetchone()
            if row is not None:
                cur.execute(
                    """
                    UPDATE music_workers
                    SET status = 'idle', active_job_id = NULL,
                        last_seen_at = now(), updated_at = now()
                    WHERE worker_id = %s
                    """,
                    (str(worker_id).strip(),),
                )
                return row["status"]
            return None


    def count_queued_jobs(self) -> int:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) AS total FROM music_jobs WHERE status = 'queued'")
            row = cur.fetchone()
            return int(row["total"] if row else 0)

    def run_with_dispatch_capacity(
        self, max_workers: int, operation: Callable[[], _T]
    ) -> _T:
        """Serialize provisioning and enforce the active-worker cap in Postgres.

        A transaction-scoped advisory lock makes this safe across multiple API
        processes/instances. The lock is held while the provider operation runs,
        so a second request fails fast rather than creating another GPU.
        """
        cap = int(max_workers)
        if not 1 <= cap <= 10:
            raise ValueError("max_workers must be between 1 and 10.")
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT pg_try_advisory_xact_lock(20261125, 1) AS acquired"
            )
            lock = cur.fetchone()
            if not lock or not lock["acquired"]:
                raise DispatchCapacityError("Another worker provisioning request is active.")
            cur.execute(
                """
                SELECT count(*) AS total
                FROM music_workers
                WHERE status IN ('starting', 'idle', 'busy', 'stopping')
                """
            )
            row = cur.fetchone()
            active = int(row["total"] if row else 0)
            if active >= cap:
                raise DispatchCapacityError(
                    f"Worker capacity is full ({active}/{cap})."
                )
            # Keep the transaction/advisory lock open until provisioning finishes.
            return operation()

    def get_worker(self, worker_id: str) -> dict | None:
        worker = str(worker_id).strip()
        if not worker or len(worker) > 128:
            raise ValueError("worker_id must contain 1–128 characters.")
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT worker_id, instance_uuid, status, active_job_id,
                       last_seen_at, created_at, updated_at
                FROM music_workers WHERE worker_id = %s
                """,
                (worker,),
            )
            return cur.fetchone()

    def mark_stale_idle_worker_stopping(
        self, worker_id: str, *, idle_seconds: int
    ) -> bool:
        """Atomically reserve shutdown only for a stale, truly idle worker."""
        seconds = max(60, min(int(idle_seconds), 86400))
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE music_workers
                SET status = 'stopping', updated_at = now()
                WHERE worker_id = %s
                  AND status = 'idle'
                  AND active_job_id IS NULL
                  AND last_seen_at < now() - (%s * interval '1 second')
                  AND instance_uuid IS NOT NULL
                RETURNING worker_id
                """,
                (str(worker_id).strip(), seconds),
            )
            return cur.fetchone() is not None

    def mark_worker_stopped_after_release(self, worker_id: str) -> bool:
        """Persist stopped only after provider release returned success."""
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE music_workers
                SET status = 'stopped', active_job_id = NULL,
                    updated_at = now()
                WHERE worker_id = %s AND status = 'stopping'
                RETURNING worker_id
                """,
                (str(worker_id).strip(),),
            )
            return cur.fetchone() is not None

    def latest_worker(self) -> dict | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT worker_id, instance_uuid, status, active_job_id,
                       last_seen_at, created_at, updated_at
                FROM music_workers
                ORDER BY created_at DESC
                LIMIT 1
                """
            )
            return cur.fetchone()

    def prepare_worker(self, worker_id: str) -> dict:
        worker = str(worker_id).strip()
        if not worker or len(worker) > 128:
            raise ValueError("worker_id must contain 1–128 characters.")
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO music_workers (worker_id, status)
                VALUES (%s, 'starting')
                ON CONFLICT (worker_id) DO UPDATE
                SET status = 'starting', active_job_id = NULL,
                    last_seen_at = now(), updated_at = now()
                RETURNING *
                """,
                (worker,),
            )
            row = cur.fetchone()
        if row is None:
            raise JobStoreError("The worker record was not created.")
        return row

    def set_worker_instance(self, worker_id: str, instance_uuid: str) -> bool:
        value = str(instance_uuid).strip()
        if not value.startswith("pro-") or len(value) > 80:
            raise ValueError("Invalid AutoDL Pro instance ID.")
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE music_workers
                SET instance_uuid = %s, updated_at = now()
                WHERE worker_id = %s
                RETURNING worker_id
                """,
                (value, str(worker_id).strip()),
            )
            return cur.fetchone() is not None

    def issue_bootstrap_token(
        self, token_hash: str, worker_id: str, *, expires_seconds: int = 900
    ) -> None:
        digest = str(token_hash).strip().lower()
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise ValueError("token_hash must be a SHA-256 hex digest.")
        expiry = max(60, min(int(expires_seconds), 1800))
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO music_worker_bootstrap_tokens
                    (token_hash, worker_id, expires_at)
                VALUES (%s, %s, now() + (%s * interval '1 second'))
                """,
                (digest, str(worker_id).strip(), expiry),
            )

    def set_bootstrap_instance(self, token_hash: str, instance_uuid: str) -> bool:
        value = str(instance_uuid).strip()
        if not value.startswith("pro-") or len(value) > 80:
            raise ValueError("Invalid AutoDL Pro instance ID.")
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE music_worker_bootstrap_tokens
                SET instance_uuid = %s
                WHERE token_hash = %s AND used_at IS NULL AND expires_at > now()
                RETURNING token_hash
                """,
                (value, str(token_hash).strip().lower()),
            )
            return cur.fetchone() is not None

    def consume_bootstrap_token(self, token_hash: str) -> dict | None:
        digest = str(token_hash).strip().lower()
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE music_worker_bootstrap_tokens
                SET used_at = now()
                WHERE token_hash = %s AND used_at IS NULL AND expires_at > now()
                RETURNING worker_id, instance_uuid
                """,
                (digest,),
            )
            return cur.fetchone()
