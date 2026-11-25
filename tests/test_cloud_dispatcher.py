# -*- coding: utf-8 -*-
import hashlib

import pytest

from musicmaster.cloud import dispatcher


class FakeStore:
    def __init__(self, events, *, link_token=True, link_worker=True):
        self.events = events
        self.link_token = link_token
        self.link_worker = link_worker

    def prepare_worker(self, worker_id):
        self.events.append(("prepare_worker", worker_id))

    def issue_bootstrap_token(self, token_hash, worker_id, *, expires_seconds):
        self.events.append(("issue_token", token_hash, worker_id, expires_seconds))
        self.token_hash = token_hash

    def set_bootstrap_instance(self, token_hash, instance_uuid):
        self.events.append(("link_token_instance", token_hash, instance_uuid))
        return self.link_token

    def set_worker_instance(self, worker_id, instance_uuid):
        self.events.append(("link_worker_instance", worker_id, instance_uuid))
        return self.link_worker

    def set_worker_status(self, worker_id, status):
        self.events.append(("worker_status", worker_id, status))
        return True


class FakeAutoDL:
    def __init__(self, events):
        self.events = events

    def create_instance(self, **kwargs):
        self.events.append(("create_instance", kwargs))
        return "pro-test123"

    def power_on(self, instance_uuid, *, start_command=None):
        self.events.append(("power_on", instance_uuid, start_command))


def test_create_worker_persists_instance_before_power_on(monkeypatch):
    events = []
    store = FakeStore(events)
    autodl = FakeAutoDL(events)
    monkeypatch.setattr(
        dispatcher, "build_worker_start_command",
        lambda api_url, token: f"START {api_url} {token}",
    )

    result = dispatcher.create_autodl_worker(
        store=store,
        autodl_client=autodl,
        api_url="https://api.example.test",
        image_uuid="image-uuid",
        cuda_v_from=124,
        worker_id_factory=lambda: "worker-test",
    )

    assert result == {
        "worker_id": "worker-test",
        "instance_uuid": "pro-test123",
        "status": "starting",
    }
    names = [event[0] for event in events]
    assert names.index("link_token_instance") < names.index("power_on")
    assert names.index("link_worker_instance") < names.index("power_on")
    create_args = next(event[1] for event in events if event[0] == "create_instance")
    assert "start_command" not in create_args
    power_on = next(event for event in events if event[0] == "power_on")
    assert power_on[1] == "pro-test123"
    assert power_on[2].startswith("START https://api.example.test ")
    assert store.token_hash == next(event[1] for event in events if event[0] == "issue_token")
    assert len(store.token_hash) == 64
    assert store.token_hash == hashlib.sha256(
        power_on[2].split(" ", 2)[2].encode("utf-8")
    ).hexdigest()
    assert all("bootstrap_token" not in str(event).lower() for event in events)


def test_create_worker_marks_error_and_does_not_power_on_if_instance_link_fails(monkeypatch):
    events = []
    store = FakeStore(events, link_token=False)
    autodl = FakeAutoDL(events)
    monkeypatch.setattr(dispatcher, "build_worker_start_command", lambda *_: "secret-command")

    with pytest.raises(RuntimeError, match="could not be linked"):
        dispatcher.create_autodl_worker(
            store=store,
            autodl_client=autodl,
            api_url="https://api.example.test",
            image_uuid="image-uuid",
            cuda_v_from=124,
            worker_id_factory=lambda: "worker-test",
        )

    assert not any(event[0] == "power_on" for event in events)
    assert ("worker_status", "worker-test", "error") in events


def test_create_worker_validates_worker_id_before_touching_store():
    events = []
    with pytest.raises(ValueError, match="worker_id"):
        dispatcher.create_autodl_worker(
            store=FakeStore(events),
            autodl_client=FakeAutoDL(events),
            api_url="https://api.example.test",
            image_uuid="image-uuid",
            cuda_v_from=124,
            worker_id_factory=lambda: "",
        )
    assert events == []



class FakeCursor:
    def __init__(self, rows):
        self.rows = list(rows)
        self.queries = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, query, params=None):
        self.queries.append((query, params))

    def fetchone(self):
        return self.rows.pop(0)


class FakeConnection:
    def __init__(self, rows):
        self.fake_cursor = FakeCursor(rows)
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True
        return False

    def cursor(self):
        return self.fake_cursor


def test_postgres_capacity_gate_holds_advisory_lock_during_operation(monkeypatch):
    from musicmaster.cloud.job_store import PostgresJobStore

    store = PostgresJobStore("postgresql://unused")
    conn = FakeConnection([{"acquired": True}, {"total": 0}])
    monkeypatch.setattr(store, "_connect", lambda: conn)
    observed = []

    result = store.run_with_dispatch_capacity(
        2,
        lambda: observed.append(conn.closed) or "created",
    )

    assert result == "created"
    assert observed == [False]
    assert conn.closed is True
    assert "pg_try_advisory_xact_lock" in conn.fake_cursor.queries[0][0]
    assert "status IN ('starting', 'idle', 'busy', 'stopping')" in conn.fake_cursor.queries[1][0]


def test_postgres_capacity_gate_fails_fast_when_another_dispatcher_holds_lock(monkeypatch):
    from musicmaster.cloud.job_store import DispatchCapacityError, PostgresJobStore

    store = PostgresJobStore("postgresql://unused")
    conn = FakeConnection([{"acquired": False}])
    monkeypatch.setattr(store, "_connect", lambda: conn)
    called = []

    with pytest.raises(DispatchCapacityError, match="Another worker"):
        store.run_with_dispatch_capacity(1, lambda: called.append(True))

    assert called == []
    assert conn.closed is True


def test_postgres_capacity_gate_rejects_full_capacity(monkeypatch):
    from musicmaster.cloud.job_store import DispatchCapacityError, PostgresJobStore

    store = PostgresJobStore("postgresql://unused")
    conn = FakeConnection([{"acquired": True}, {"total": 1}])
    monkeypatch.setattr(store, "_connect", lambda: conn)
    called = []

    with pytest.raises(DispatchCapacityError, match="1/1"):
        store.run_with_dispatch_capacity(1, lambda: called.append(True))

    assert called == []
    assert conn.closed is True


@pytest.mark.parametrize("capacity", [0, -1, 11])
def test_postgres_capacity_gate_rejects_out_of_range_limits(capacity):
    from musicmaster.cloud.job_store import PostgresJobStore

    store = PostgresJobStore("postgresql://unused")
    with pytest.raises(ValueError, match="between 1 and 10"):
        store.run_with_dispatch_capacity(capacity, lambda: None)



def test_stopping_worker_cannot_claim_another_job(monkeypatch):
    from musicmaster.cloud.job_store import PostgresJobStore

    store = PostgresJobStore("postgresql://unused")
    conn = FakeConnection([{"status": "stopping"}])
    monkeypatch.setattr(store, "_connect", lambda: conn)

    assert store.claim_next("worker-test") is None
    assert len(conn.fake_cursor.queries) == 1
    assert "FOR UPDATE" in conn.fake_cursor.queries[0][0]


def test_worker_registration_upsert_cannot_revive_stopping_worker(monkeypatch):
    from musicmaster.cloud.job_store import JobStoreError, PostgresJobStore

    store = PostgresJobStore("postgresql://unused")
    conn = FakeConnection([None])
    monkeypatch.setattr(store, "_connect", lambda: conn)

    import pytest
    with pytest.raises(JobStoreError, match="record was not created"):
        store.register_worker("worker-test", "pro-test")

    query = conn.fake_cursor.queries[0][0]
    assert "WHERE music_workers.status IN ('starting', 'idle', 'busy')" in query



def test_worker_heartbeat_sql_rejects_shutdown_states_and_inconsistent_job_state(monkeypatch):
    from musicmaster.cloud.job_store import PostgresJobStore

    store = PostgresJobStore("postgresql://unused")
    conn = FakeConnection([{"worker_id": "worker-test"}])
    monkeypatch.setattr(store, "_connect", lambda: conn)

    assert store.heartbeat_worker("worker-test", "idle") is True
    query, params = conn.fake_cursor.queries[0]
    assert "status IN ('starting', 'idle', 'busy')" in query
    assert "active_job_id IS NULL" in query
    assert "active_job_id IS NOT NULL" in query
    assert params == ("idle", "worker-test", "idle", "idle")


def test_worker_heartbeat_rejects_non_operational_status():
    import pytest
    from musicmaster.cloud.job_store import PostgresJobStore

    store = PostgresJobStore("postgresql://unused")
    with pytest.raises(ValueError, match="idle or busy"):
        store.heartbeat_worker("worker-test", "stopping")
