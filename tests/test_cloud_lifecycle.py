# -*- coding: utf-8 -*-
from musicmaster.cloud.autodl_pro import AutoDLProError
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
        if self.worker["status"] not in {"idle", "error"}:
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


class MissingStatusAutoDL(FakeAutoDL):
    def __init__(self, listed_instance):
        super().__init__("unused")
        self.listed_instance = listed_instance

    def get_status(self, instance_uuid):
        self.events.append(("status_error", instance_uuid))
        raise AutoDLProError("provider status lookup unavailable")

    def find_instance(self, instance_uuid):
        self.events.append(("find_instance", instance_uuid))
        return self.listed_instance


def test_recovery_finalizes_stopped_when_complete_provider_list_confirms_absence():
    store = FakeStore(status="stopping")
    provider = MissingStatusAutoDL(None)
    result = reconcile_idle_worker(
        store=store, autodl_client=provider, worker_id="worker-test"
    )
    assert result["status"] == "stopped"
    assert result["provider_status"] == "absent_from_complete_instance_list"
    assert provider.events == [
        ("status_error", "pro-test"),
        ("find_instance", "pro-test"),
    ]
    assert store.marked_stopped is True


def test_recovery_keeps_worker_stopping_when_provider_list_still_contains_instance():
    store = FakeStore(status="stopping")
    provider = MissingStatusAutoDL({"uuid": "pro-test", "status": "shutdown"})
    result = reconcile_idle_worker(
        store=store, autodl_client=provider, worker_id="worker-test"
    )
    assert result["status"] == "stopping"
    assert result["provider_status"] == "status_unavailable_instance_still_listed"
    assert store.marked_stopped is False
    assert provider.events == [
        ("status_error", "pro-test"),
        ("find_instance", "pro-test"),
    ]


def test_recovery_does_not_finalize_when_provider_list_lookup_fails():
    import pytest

    class BrokenListAutoDL(MissingStatusAutoDL):
        def find_instance(self, instance_uuid):
            raise RuntimeError("list endpoint unavailable")

    store = FakeStore(status="stopping")
    provider = BrokenListAutoDL(None)
    with pytest.raises(AutoDLProError, match="status lookup unavailable"):
        reconcile_idle_worker(
            store=store, autodl_client=provider, worker_id="worker-test"
        )
    assert store.marked_stopped is False



def test_stale_error_worker_is_marked_stopping_before_provider_shutdown():
    store = FakeStore(status="error")
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


def test_fresh_error_worker_is_not_reconciled_or_powered_off():
    store = FakeStore(status="error")
    store.mark_stale_idle_worker_stopping = lambda *args, **kwargs: False
    provider = FakeAutoDL("running")
    result = reconcile_idle_worker(
        store=store, autodl_client=provider, worker_id="worker-test", idle_seconds=600
    )
    assert result["status"] == "not_stale_or_not_reconcilable"
    assert provider.events == []
