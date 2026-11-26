from __future__ import annotations

from uuid import uuid4

import pytest

from musicmaster.cloud.job_store import JobStoreError, PostgresJobStore


class _Cursor:
    def __init__(self, rows):
        self.rows = list(rows)
        self.statements = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement, params=None):
        self.statements.append((statement, params))

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None


class _Connection:
    def __init__(self, rows):
        self.cur = _Cursor(rows)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self):
        return self.cur


def test_add_artifact_uses_object_key_conflict_as_idempotency_key(monkeypatch):
    store = PostgresJobStore(dsn="postgresql://unused")
    artifact = {"id": 41, "object_key": "jobs/example/artifacts/a/notes.json"}
    connection = _Connection([artifact])
    monkeypatch.setattr(store, "_connect", lambda: connection)

    result = store.add_artifact(
        uuid4(), "gpu-worker",
        object_key=artifact["object_key"],
        file_name="notes.json",
        content_type="application/json",
        size_bytes=128,
    )

    sql = connection.cur.statements[0][0]
    assert result == artifact
    assert "ON CONFLICT (object_key) DO UPDATE" in sql
    assert "music_job_artifacts.job_id = EXCLUDED.job_id" in sql
    assert "j.attempt_count" in sql
    assert "attempt_count = EXCLUDED.attempt_count" in sql


def test_add_artifact_rejects_conflict_owned_by_another_job(monkeypatch):
    store = PostgresJobStore(dsn="postgresql://unused")
    connection = _Connection([None])
    monkeypatch.setattr(store, "_connect", lambda: connection)

    with pytest.raises(JobStoreError):
        store.add_artifact(
            uuid4(), "gpu-worker",
            object_key="jobs/other/artifacts/a/notes.json",
            file_name="notes.json",
        )


def test_list_artifacts_only_returns_current_attempt(monkeypatch):
    store = PostgresJobStore(dsn="postgresql://unused")
    connection = _Connection([[]])
    monkeypatch.setattr(store, "_connect", lambda: connection)

    assert store.list_artifacts(uuid4()) == []

    sql = connection.cur.statements[0][0]
    assert "JOIN music_jobs AS j ON j.id = a.job_id" in sql
    assert "a.attempt_count = j.attempt_count" in sql
    assert "j.status IN ('running', 'completed')" in sql


def test_complete_job_accepts_retry_after_same_worker_already_completed(monkeypatch):
    store = PostgresJobStore(dsn="postgresql://unused")
    connection = _Connection([None, {"id": uuid4()}])
    monkeypatch.setattr(store, "_connect", lambda: connection)

    assert store.complete_job(uuid4(), "gpu-worker", {"status": "completed"}) is True

    statements = [statement for statement, _ in connection.cur.statements]
    assert "status = 'completed'" in statements[1]
    assert "worker_id = %s" in statements[1]
    assert len(statements) == 2



def test_artifact_attempt_migration_backfills_only_unassigned_rows():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    migration = (root / "migrations/0003_track_artifact_attempts.sql").read_text(
        encoding="utf-8"
    )

    assert "ADD COLUMN IF NOT EXISTS attempt_count INTEGER" in migration
    assert "AND a.attempt_count IS NULL" in migration
    assert "ALTER COLUMN attempt_count SET NOT NULL" in migration
    assert "ON music_job_artifacts (job_id, attempt_count, id)" in migration
