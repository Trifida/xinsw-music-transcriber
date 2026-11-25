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


def test_complete_job_accepts_retry_after_same_worker_already_completed(monkeypatch):
    store = PostgresJobStore(dsn="postgresql://unused")
    connection = _Connection([None, {"id": uuid4()}, {"worker_id": "gpu-worker"}])
    monkeypatch.setattr(store, "_connect", lambda: connection)

    assert store.complete_job(uuid4(), "gpu-worker", {"status": "completed"}) is True

    statements = [statement for statement, _ in connection.cur.statements]
    assert "status = 'completed'" in statements[1]
    assert "worker_id = %s" in statements[1]
    assert "SET status = 'idle'" in statements[2]
