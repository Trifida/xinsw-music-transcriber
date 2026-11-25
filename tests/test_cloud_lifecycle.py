# -*- coding: utf-8 -*-
from musicmaster.cloud.lifecycle import reconcile_idle_worker


class FakeStore:
    def __init__(self, status="idle", instance_uuid="pro-test"):
        self.worker = {
            "worker_id": "worker-test",
            "instance_uuid": instance_uuid,
            "status": status,
        }
        self.marked_stopping = False
        self.marked_stopped = False

    def get_worker(self, worker_id):
        return dict(self.worker)

    def mark_stale_idle_worker_stopping(self, worker_id, *, idle_seconds):
        if self.worker["status"] != "idle":
            return False
        self.worker["status"] = "stopping"
        self.marked_stopping = True
        self.idle_seconds = idle_seconds
        return True

    def mark_worker_stopped_after_release(self, worker_id):
        if self.worker["status"] != "stopping":
            return False
        self.worker["status"] = "stopped"
        self.marked_stopped = True
        return True


class FakeAutoDL:
    def __init__(self, status):
        self.status = status
        self.events = []

    def get_status(self, instance_uuid):
        self.events.append(("status", instance_uuid))
        return self.status

    def power_off(self, instance_uuid):
        self.events.append(("power_off", instance_uuid))

    def release_instance(self, instance_uuid):
        self.events.append(("release", instance_uuid))


def test_idle_worker_is_marked_stopping_before_provider_shutdown():
    store = FakeStore()
    provider = FakeAutoDL("running")
    result = reconcile_idle_worker(
        store=store, autodl_client=provider, worker_id="worker-test", idle_seconds=600
    )
    assert result["status"] == "stopping"
    assert store.marked_stopping is True
    assert store.idle_seconds == 600
    assert provider.events == [
        ("status", "pro-test"),
        ("power_off", "pro-test"),
    ]
    assert store.marked_stopped is False


def test_shutdown_is_confirmed_before_release_and_db_finalization():
    store = FakeStore(status="stopping")
    provider = FakeAutoDL("shutdown")
    result = reconcile_idle_worker(
        store=store, autodl_client=provider, worker_id="worker-test"
    )
    assert result["status"] == "stopped"
    assert provider.events == [
        ("status", "pro-test"),
        ("release", "pro-test"),
    ]
    assert store.marked_stopped is True


def test_unknown_provider_state_never_powers_off_or_releases():
    store = FakeStore(status="stopping")
    provider = FakeAutoDL("creating")
    result = reconcile_idle_worker(
        store=store, autodl_client=provider, worker_id="worker-test"
    )
    assert result["status"] == "stopping"
    assert result["provider_status"] == "creating"
    assert provider.events == [("status", "pro-test")]
    assert store.marked_stopped is False


def test_busy_worker_is_never_marked_for_shutdown():
    store = FakeStore(status="busy")
    provider = FakeAutoDL("running")
    result = reconcile_idle_worker(
        store=store, autodl_client=provider, worker_id="worker-test"
    )
    assert result["status"] == "busy"
    assert provider.events == []


def test_idle_worker_without_stale_eligibility_is_not_touched():
    store = FakeStore()
    store.mark_stale_idle_worker_stopping = lambda *args, **kwargs: False
    provider = FakeAutoDL("running")
    result = reconcile_idle_worker(
        store=store, autodl_client=provider, worker_id="worker-test"
    )
    assert result["status"] == "not_stale_or_not_idle"
    assert provider.events == []


def test_worker_without_instance_link_is_not_reconciled():
    import pytest

    store = FakeStore(instance_uuid=None)
    provider = FakeAutoDL("shutdown")
    with pytest.raises(RuntimeError, match="no linked"):
        reconcile_idle_worker(
            store=store, autodl_client=provider, worker_id="worker-test"
        )
    assert provider.events == []
