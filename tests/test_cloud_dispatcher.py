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
