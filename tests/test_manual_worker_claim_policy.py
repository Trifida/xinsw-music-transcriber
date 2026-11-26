from __future__ import annotations

from musicmaster.cloud.job_store import PostgresJobStore


class _Cursor:
    def __init__(self):
        self.statements = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement, _params=None):
        self.statements.append(statement)

    def fetchone(self):
        return None


class _Connection:
    def __init__(self):
        self.cur = _Cursor()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self):
        return self.cur


def test_claim_next_only_selects_manually_started_queued_jobs(monkeypatch):
    store = PostgresJobStore(dsn="postgresql://unused")
    connection = _Connection()
    monkeypatch.setattr(store, "_connect", lambda: connection)

    assert store.claim_next("colab-worker") is None

    claim_sql = connection.cur.statements[2]
    assert "manual_start_requested" in claim_sql
    assert "auto_dispatch_requested" not in claim_sql
