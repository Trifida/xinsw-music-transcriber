# -*- coding: utf-8 -*-
from datetime import datetime, timezone
from io import BytesIO
from uuid import uuid4
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from musicmaster.cloud.job_store import PostgresJobStore
from musicmaster.cloud.object_store import S3ObjectStore
from musicmaster.cloud import worker
from musicmaster.web import cloud_api


class FakeStore:
    def __init__(self):
        self.jobs = {}
        self.artifacts = []
        self.uploaded = None
        self.completed = False

    def create_job(self, job_id, **kwargs):
        self.uploaded = (str(job_id), kwargs)
        row = {
            "id": job_id, "status": "awaiting_upload",
            "source_filename": kwargs["source_filename"],
            "options": kwargs.get("options", {}),
        }
        self.jobs[str(job_id)] = row
        return row

    def mark_upload_complete(self, job_id, size_bytes):
        self.jobs[str(job_id)]["status"] = "queued"
        self.jobs[str(job_id)]["source_size_bytes"] = size_bytes
        return True

    def get_job(self, job_id):
        return self.jobs.get(str(job_id))

    def has_live_worker(self, heartbeat_seconds=120):
        return getattr(self, "live_worker", False)

    def request_job_start(self, job_id):
        self.jobs[str(job_id)]["options"] = {"manual_start_requested": True}
        return True

    def count_queued_jobs(self):
        return sum(1 for row in self.jobs.values() if row.get("status") == "queued")

    def list_artifacts(self, job_id):
        return list(self.artifacts)

    def claim_next(self, worker_id, lease_seconds=180):
        return None

    def register_worker(self, worker_id, instance_uuid=None):
        return {"worker_id": worker_id, "status": "idle"}

    def set_worker_status(self, worker_id, status):
        return True

    def heartbeat_worker(self, worker_id, status):
        self.last_worker_heartbeat = (worker_id, status)
        return getattr(self, "heartbeat_allowed", True)

    def heartbeat_job(self, *args, **kwargs):
        return True

    def add_artifact(self, job_id, worker_id, **kwargs):
        row = {"id": len(self.artifacts) + 1, **kwargs}
        self.artifacts.append(row)
        return row

    def complete_job(self, job_id, worker_id, result):
        self.completed = True
        return True

    def fail_job(self, job_id, worker_id, error, retryable=False):
        return "failed"

    def get_worker(self, worker_id):
        return getattr(self, "worker_record", None)

    def recover_worker_instance(self, worker_id, instance_uuid):
        self.recovered_worker_instance = (worker_id, instance_uuid)
        return getattr(self, "recovery_allowed", True)

    def run_with_dispatch_capacity(self, max_workers, operation, *, replay_if=None):
        if not 1 <= int(max_workers) <= 10:
            raise ValueError("max_workers must be between 1 and 10.")
        self.dispatch_max_workers = max_workers
        if replay_if is not None:
            replay = replay_if()
            if replay is not None:
                return replay
        if getattr(self, "capacity_full", False):
            from musicmaster.cloud.job_store import DispatchCapacityError
            raise DispatchCapacityError("Worker capacity is full.")
        return operation()


class FakeObjects:
    def __init__(self):
        self.uploaded = None

    def upload_fileobj(self, fileobj, key, content_type):
        self.uploaded = (fileobj.read(), key, content_type)

    def presigned_download(self, key, expires_seconds=900):
        return "https://storage.example.test/download?sig=ok"

    def presigned_upload(self, key, content_type, expires_seconds=900):
        return "https://storage.example.test/upload?sig=ok"

    def head(self, key):
        return {"size_bytes": 12, "content_type": "application/json"}

    def delete(self, key):
        return None


@pytest.fixture()
def api(monkeypatch):
    store, objects = FakeStore(), FakeObjects()
    monkeypatch.setattr(cloud_api, "_components", lambda: (store, objects))
    monkeypatch.setenv("MUSICMASTER_WORKER_TOKEN", "test-worker-secret")
    app = FastAPI()
    app.include_router(cloud_api.router)
    return TestClient(app), store, objects


def test_safe_filename_and_object_key_validation():
    assert cloud_api._safe_filename("../../你好 song.mp3") == "你好_song.mp3"
    assert S3ObjectStore._key("jobs/123/source/song.mp3") == "jobs/123/source/song.mp3"
    with pytest.raises(ValueError):
        S3ObjectStore._key("jobs/../secret")


def test_job_store_uuid_validation():
    job_id = uuid4()
    assert PostgresJobStore._uuid(str(job_id)) == job_id
    with pytest.raises(ValueError):
        PostgresJobStore._uuid("not-a-uuid")


def test_worker_config_requires_https_and_secret(monkeypatch):
    monkeypatch.setenv("MUSICMASTER_API_URL", "http://example.test")
    monkeypatch.setenv("MUSICMASTER_WORKER_TOKEN", "secret")
    with pytest.raises(ValueError, match="HTTPS"):
        worker._config()
    monkeypatch.setenv("MUSICMASTER_API_URL", "https://example.test")
    monkeypatch.delenv("MUSICMASTER_WORKER_TOKEN")
    with pytest.raises(ValueError, match="TOKEN"):
        worker._config()


def test_worker_auth_rejects_missing_token_and_accepts_valid_token(api):
    client, _, _ = api
    body = {"worker_id": "gpu-1", "lease_seconds": 300}
    assert client.post("/api/internal/jobs/claim", json=body).status_code == 401
    response = client.post(
        "/api/internal/jobs/claim", json=body,
        headers={"Authorization": "Bearer test-worker-secret"},
    )
    assert response.status_code == 200
    assert response.json() == {"job": None}


def test_cloud_upload_creates_private_object_and_queues_job(api, monkeypatch):
    client, store, objects = api
    monkeypatch.delenv("MUSICMASTER_AUTODL_AUTO_DISPATCH", raising=False)
    response = client.post(
        "/api/cloud/jobs",
        files={"audio": ("原曲.mp3", b"audio-bytes", "audio/mpeg")},
        data={
            "engine": "crepe", "stages": "1,2,3", "denoise": "dereverb",
            "lyrics": "春风又绿江南岸",
        },
    )
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "queued"
    assert result["dispatch"] == "manual"
    assert objects.uploaded[0] == b"audio-bytes"
    assert objects.uploaded[1].startswith(f"jobs/{result['job_id']}/source/")
    assert store.jobs[result["job_id"]]["status"] == "queued"
    assert store.jobs[result["job_id"]]["source_size_bytes"] == len(b"audio-bytes")
    assert store.jobs[result["job_id"]]["options"]["lyrics"] == "春风又绿江南岸"


def test_manual_start_requires_existing_live_gpu_and_never_provisions(api, monkeypatch):
    client, store, _ = api
    monkeypatch.delenv("MUSICMASTER_AUTODL_AUTO_DISPATCH", raising=False)
    created = client.post(
        "/api/cloud/jobs",
        files={"audio": ("原曲.mp3", b"audio-bytes", "audio/mpeg")},
    ).json()
    job_id = created["job_id"]

    waiting = client.post(f"/api/cloud/jobs/{job_id}/start")
    assert waiting.status_code == 409
    assert "不会创建新的 GPU" in waiting.json()["detail"]
    assert store.jobs[job_id]["status"] == "queued"
    assert store.jobs[job_id]["options"]["manual_start_requested"] is not True
    assert store.jobs[job_id]["options"]["auto_dispatch_requested"] is False

    store.live_worker = True
    started = client.post(f"/api/cloud/jobs/{job_id}/start")
    assert started.status_code == 200
    assert started.json()["worker_available"] is True
    assert store.jobs[job_id]["options"]["manual_start_requested"] is True


def test_manual_start_rejects_unknown_job(api):
    client, _, _ = api
    response = client.post(f"/api/cloud/jobs/{uuid4()}/start")
    assert response.status_code == 404


def test_cloud_upload_never_provisions_gpu_even_when_legacy_auto_flag_is_enabled(api, monkeypatch):
    client, store, _ = api
    monkeypatch.setenv("MUSICMASTER_AUTODL_AUTO_DISPATCH", "true")

    def forbidden_provision(**kwargs):
        raise AssertionError("full-song upload must never provision a GPU")

    monkeypatch.setattr(cloud_api, "provision_cloud_worker", forbidden_provision)
    response = client.post(
        "/api/cloud/jobs",
        files={"audio": ("原曲.mp3", b"audio-bytes", "audio/mpeg")},
    )

    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "queued"
    assert result["dispatch"] == "manual"
    assert store.jobs[result["job_id"]]["status"] == "queued"


def test_queued_job_dispatch_sweep_is_opt_in_and_uses_stable_minute_key(api, monkeypatch):
    client, store, _ = api
    monkeypatch.setenv("MUSICMASTER_DISPATCHER_TOKEN", "d" * 40)
    headers = {"Authorization": "Bearer " + "d" * 40}

    disabled = client.post(
        "/api/internal/dispatcher/dispatch-queued", headers=headers
    )
    assert disabled.status_code == 200
    assert disabled.json()["status"] == "disabled"

    monkeypatch.setenv("MUSICMASTER_AUTODL_AUTO_DISPATCH", "true")

    class FixedDateTime:
        @staticmethod
        def now(tz):
            return datetime(2026, 11, 25, 12, 30, tzinfo=tz)

    monkeypatch.setattr(cloud_api, "datetime", FixedDateTime)
    store.jobs["queued-job"] = {"id": "queued-job", "status": "queued"}
    calls = []
    monkeypatch.setattr(
        cloud_api, "provision_cloud_worker",
        lambda *, idempotency_key: calls.append(idempotency_key) or {
            "worker_id": "dispatch-test", "status": "starting",
        },
    )
    first = client.post(
        "/api/internal/dispatcher/dispatch-queued", headers=headers
    )
    second = client.post(
        "/api/internal/dispatcher/dispatch-queued", headers=headers
    )

    assert first.status_code == 200
    assert first.json()["status"] == "worker_dispatch_requested"
    assert first.json()["queued_jobs"] == 1
    assert second.status_code == 200
    assert calls[0] == calls[1]
    assert calls[0].startswith("queue-sweep-")


def test_cloud_upload_rejects_oversized_lyrics(api):
    client, _, objects = api
    response = client.post(
        "/api/cloud/jobs",
        files={"audio": ("song.mp3", b"audio", "audio/mpeg")},
        data={"lyrics": "字" * 100_001},
    )
    assert response.status_code == 413
    assert objects.uploaded is None


def test_cloud_upload_rejects_unsupported_extension(api):
    client, _, objects = api
    response = client.post(
        "/api/cloud/jobs",
        files={"audio": ("song.exe", b"not audio", "application/octet-stream")},
    )
    assert response.status_code == 415
    assert objects.uploaded is None


def test_claim_returns_short_lived_source_url(api, monkeypatch):
    client, store, objects = api
    job_id = uuid4()
    store.claim_next = lambda worker_id, lease_seconds=180: {
        "id": job_id,
        "source_object_key": f"jobs/{job_id}/source/song.mp3",
        "source_filename": "song.mp3",
        "source_content_type": "audio/mpeg",
        "options": {"engine": "crepe"},
        "attempt_count": 1,
    }
    response = client.post(
        "/api/internal/jobs/claim",
        json={"worker_id": "gpu-1"},
        headers={"Authorization": "Bearer test-worker-secret"},
    )
    assert response.status_code == 200
    assert response.json()["job"]["source_url"].startswith("https://storage.example.test/")
    assert response.json()["job"]["options"] == {"engine": "crepe"}


def test_worker_artifact_confirmation_and_completion(api):
    client, store, _ = api
    job_id = uuid4()
    store.jobs[str(job_id)] = {"id": job_id, "status": "running", "worker_id": "gpu-1"}
    prefix = f"jobs/{job_id}/artifacts/"
    confirmed = client.post(
        f"/api/internal/jobs/{job_id}/artifact-complete",
        json={
            "worker_id": "gpu-1",
            "object_key": prefix + "a1/notes.json",
            "file_name": "notes.json",
        },
        headers={"Authorization": "Bearer test-worker-secret"},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["size_bytes"] == 12

    store.artifacts.extend([
        {"id": 2, "file_name": "out.mid"},
        {"id": 3, "file_name": "out.musicxml"},
    ])
    completed = client.post(
        f"/api/internal/jobs/{job_id}/complete",
        json={"worker_id": "gpu-1", "result": {"status": "completed"}},
        headers={"Authorization": "Bearer test-worker-secret"},
    )
    assert completed.status_code == 200
    assert store.completed is True


def test_worker_cannot_confirm_artifact_for_another_job(api):
    client, store, _ = api
    job_id = uuid4()
    other_id = uuid4()
    store.jobs[str(job_id)] = {"id": job_id, "status": "running", "worker_id": "gpu-1"}
    response = client.post(
        f"/api/internal/jobs/{job_id}/artifact-complete",
        json={
            "worker_id": "gpu-1",
            "object_key": f"jobs/{other_id}/artifacts/a1/file.mid",
            "file_name": "file.mid",
        },
        headers={"Authorization": "Bearer test-worker-secret"},
    )
    assert response.status_code == 422


def test_worker_upload_role_classification(tmp_path):
    assert worker._artifact_role(tmp_path / "out.musicxml") == "score"
    assert worker._artifact_role(tmp_path / "final.wav") == "audio"
    assert worker._artifact_role(tmp_path / "notes.json") == "metadata"


def test_worker_downloads_source_once_and_keeps_lease_through_completion(
    monkeypatch, tmp_path
):
    import json
    import sys
    import types

    events = []
    job_id = str(uuid4())

    def fake_download(url, destination):
        events.append("download")
        destination.write_bytes(b"audio")

    def fake_transcribe(source, output, **kwargs):
        events.append("transcribe")
        output.mkdir(parents=True, exist_ok=True)
        (output / "notes.json").write_text("{}", encoding="utf-8")
        (output / "out.mid").write_bytes(b"MIDI")
        (output / "out.musicxml").write_text("<score-partwise/>", encoding="utf-8")
        manifest = {
            "separation": {},
            "transcription": {
                "files": {
                    "notes": "notes.json",
                    "midi": "out.mid",
                    "musicxml": "out.musicxml",
                }
            },
        }
        (output / "job_result.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        return manifest

    workflow_module = types.ModuleType("musicmaster.workflows.full_transcribe")
    workflow_module.run_full_transcription = fake_transcribe
    monkeypatch.setitem(sys.modules, "musicmaster.workflows.full_transcribe", workflow_module)
    monkeypatch.setattr(worker, "_download", fake_download)
    monkeypatch.setattr(worker, "_put_file", lambda *args: events.append("upload"))

    def fake_api(base, token, method, path, payload=None, **kwargs):
        if path.endswith("/heartbeat"):
            events.append("heartbeat")
            return {"ok": True}
        if path.endswith("/artifact-url"):
            events.append("artifact-url")
            return {
                "url": "https://storage.example.test/upload",
                "object_key": f"jobs/{job_id}/artifacts/test/{payload['file_name']}",
            }
        if path.endswith("/artifact-complete"):
            events.append("artifact-complete")
            return {"ok": True}
        if path.endswith("/complete"):
            events.append("complete")
            return {"ok": True}
        raise AssertionError(f"Unexpected worker API path: {path}")

    monkeypatch.setattr(worker, "_api", fake_api)
    monkeypatch.setenv("MUSICMASTER_WORKER_DATA", str(tmp_path))

    worker._process_job(
        "https://api.example.test",
        "worker-secret",
        "gpu-test",
        {
            "id": job_id,
            "source_filename": "song.mp3",
            "source_url": "https://storage.example.test/source",
            "options": {},
        },
    )

    assert events.count("download") == 1
    assert events.index("heartbeat") < events.index("download")
    assert events.index("complete") > events.index("artifact-complete")


def test_worker_bundle_endpoint_requires_auth_and_returns_pinned_digest(api, monkeypatch):
    client, _, objects = api
    commit = "a" * 40
    digest = "b" * 64
    object_key = f"worker-bundles/{commit}/{digest}.tar.gz"
    monkeypatch.setenv("MUSICMASTER_WORKER_BUNDLE_COMMIT", commit)
    monkeypatch.setenv("MUSICMASTER_WORKER_BUNDLE_SHA256", digest)
    monkeypatch.setenv("MUSICMASTER_WORKER_BUNDLE_KEY", object_key)

    assert client.get("/api/internal/worker/bundle").status_code == 401
    response = client.get(
        "/api/internal/worker/bundle",
        headers={"Authorization": "Bearer test-worker-secret"},
    )
    assert response.status_code == 200
    assert response.json()["repository_commit"] == commit
    assert response.json()["sha256"] == digest
    assert response.json()["object_key"] == object_key
    assert response.json()["url"].startswith("https://")



def test_dispatcher_endpoint_requires_separate_strong_credential(api, monkeypatch):
    client, _, _ = api
    monkeypatch.delenv("MUSICMASTER_DISPATCHER_TOKEN", raising=False)
    unavailable = client.post("/api/internal/dispatcher/workers")
    assert unavailable.status_code == 503

    monkeypatch.setenv("MUSICMASTER_DISPATCHER_TOKEN", "d" * 40)
    unauthorized = client.post(
        "/api/internal/dispatcher/workers",
        headers={"Authorization": "Bearer wrong", "Idempotency-Key": "request-key-000001"},
    )
    assert unauthorized.status_code == 401


def test_dispatcher_endpoint_uses_server_side_autodl_configuration(api, monkeypatch):
    client, store, objects = api
    monkeypatch.setenv("MUSICMASTER_DISPATCHER_TOKEN", "d" * 40)
    monkeypatch.setenv("MUSICMASTER_API_URL", "https://api.example.test")
    monkeypatch.setenv("MUSICMASTER_AUTODL_IMAGE_UUID", "configured-image")
    monkeypatch.setenv("MUSICMASTER_AUTODL_CUDA_V_FROM", "124")
    seen = {}

    class FakeAutoDLClient:
        def __init__(self):
            seen["client_created"] = True

    def fake_provision(**kwargs):
        seen.update(kwargs)
        return {
            "worker_id": "worker-test",
            "instance_uuid": "pro-test123",
            "status": "starting",
        }

    monkeypatch.setattr(cloud_api, "AutoDLProClient", FakeAutoDLClient)
    monkeypatch.setattr(cloud_api, "create_autodl_worker", fake_provision)
    response = client.post(
        "/api/internal/dispatcher/workers",
        headers={"Authorization": "Bearer " + "d" * 40, "Idempotency-Key": "request-key-000001"},
    )

    assert response.status_code == 200
    assert response.json()["instance_uuid"] == "pro-test123"
    assert seen["worker_id"].startswith("dispatch-")
    assert len(seen["worker_id"]) == 73
    assert seen["client_created"] is True
    assert seen["store"] is store
    assert seen["api_url"] == "https://api.example.test"
    assert seen["image_uuid"] == "configured-image"
    assert seen["cuda_v_from"] == 124
    assert "bootstrap_token" not in str(response.json()).lower()



def test_dispatcher_endpoint_enforces_configured_capacity(api, monkeypatch):
    client, store, _ = api
    monkeypatch.setenv("MUSICMASTER_DISPATCHER_TOKEN", "d" * 40)
    monkeypatch.setenv("MUSICMASTER_API_URL", "https://api.example.test")
    monkeypatch.setenv("MUSICMASTER_AUTODL_IMAGE_UUID", "configured-image")
    monkeypatch.setenv("MUSICMASTER_AUTODL_CUDA_V_FROM", "124")
    monkeypatch.setenv("MUSICMASTER_AUTODL_MAX_WORKERS", "2")
    monkeypatch.setattr(cloud_api, "AutoDLProClient", lambda: object())
    monkeypatch.setattr(
        cloud_api, "create_autodl_worker",
        lambda **kwargs: {"worker_id": "w", "instance_uuid": "pro-x", "status": "starting"},
    )

    headers = {"Authorization": "Bearer " + "d" * 40}
    headers["Idempotency-Key"] = "request-key-capacity-01"
    success = client.post("/api/internal/dispatcher/workers", headers=headers)
    assert success.status_code == 200
    assert store.dispatch_max_workers == 2

    store.capacity_full = True
    headers["Idempotency-Key"] = "request-key-capacity-02"
    full = client.post("/api/internal/dispatcher/workers", headers=headers)
    assert full.status_code == 409
    assert full.json()["detail"] == "Worker capacity is full."


def test_dispatcher_endpoint_rejects_invalid_capacity_setting(api, monkeypatch):
    client, _, _ = api
    monkeypatch.setenv("MUSICMASTER_DISPATCHER_TOKEN", "d" * 40)
    monkeypatch.setenv("MUSICMASTER_API_URL", "https://api.example.test")
    monkeypatch.setenv("MUSICMASTER_AUTODL_IMAGE_UUID", "configured-image")
    monkeypatch.setenv("MUSICMASTER_AUTODL_CUDA_V_FROM", "124")
    monkeypatch.setenv("MUSICMASTER_AUTODL_MAX_WORKERS", "0")
    monkeypatch.setattr(cloud_api, "AutoDLProClient", lambda: object())
    response = client.post(
        "/api/internal/dispatcher/workers",
        headers={"Authorization": "Bearer " + "d" * 40, "Idempotency-Key": "request-key-invalid-01"},
    )
    assert response.status_code == 503




def test_dispatcher_endpoint_requires_idempotency_key(api, monkeypatch):
    client, _, _ = api
    monkeypatch.setenv("MUSICMASTER_DISPATCHER_TOKEN", "d" * 40)
    response = client.post(
        "/api/internal/dispatcher/workers",
        headers={"Authorization": "Bearer " + "d" * 40},
    )
    assert response.status_code == 400
    assert "Idempotency-Key" in response.json()["detail"]


def test_dispatcher_endpoint_rechecks_idempotency_after_capacity_lock(api, monkeypatch):
    client, store, _ = api
    monkeypatch.setenv("MUSICMASTER_DISPATCHER_TOKEN", "d" * 40)
    key = "request-key-race-check-01"
    worker_id = cloud_api._idempotent_worker_id(key)
    original_get_worker = store.get_worker
    calls = {"count": 0}

    def racing_lookup(value):
        calls["count"] += 1
        if calls["count"] == 1:
            return None  # Both requests can observe the pre-insert state.
        store.worker_record = {
            "worker_id": worker_id,
            "instance_uuid": "pro-already-created",
            "status": "starting",
            "active_job_id": None,
        }
        return original_get_worker(value)

    store.get_worker = racing_lookup
    monkeypatch.setattr(
        cloud_api, "AutoDLProClient",
        lambda: (_ for _ in ()).throw(AssertionError("locked replay must not contact AutoDL")),
    )
    response = client.post(
        "/api/internal/dispatcher/workers",
        headers={"Authorization": "Bearer " + "d" * 40, "Idempotency-Key": key},
    )
    assert response.status_code == 200
    assert response.json()["idempotent_replay"] is True
    assert response.json()["instance_uuid"] == "pro-already-created"
    assert calls["count"] == 2


def test_dispatcher_endpoint_replay_returns_existing_worker_without_autodl(api, monkeypatch):
    client, store, _ = api
    monkeypatch.setenv("MUSICMASTER_DISPATCHER_TOKEN", "d" * 40)
    store.worker_record = {
        "worker_id": "dispatch-" + "a" * 64,
        "instance_uuid": None,
        "status": "error",
        "active_job_id": None,
    }
    monkeypatch.setattr(
        cloud_api, "AutoDLProClient",
        lambda: (_ for _ in ()).throw(AssertionError("replay must not contact AutoDL")),
    )
    monkeypatch.setattr(
        cloud_api, "create_autodl_worker",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("replay must not provision")),
    )
    key = "request-key-replay-0001"
    # Make the fake record use the deterministic ID for this exact key.
    store.worker_record["worker_id"] = cloud_api._idempotent_worker_id(key)
    response = client.post(
        "/api/internal/dispatcher/workers",
        headers={"Authorization": "Bearer " + "d" * 40, "Idempotency-Key": key},
    )
    assert response.status_code == 200
    assert response.json()["idempotent_replay"] is True
    assert response.json()["status"] == "error"
    assert response.json()["retry_safe"] is False

def test_worker_heartbeat_cannot_mark_stopping_or_stopped(api):
    client, store, _ = api
    headers = {"Authorization": "Bearer test-worker-secret"}
    invalid = client.post(
        "/api/internal/workers/heartbeat",
        json={"worker_id": "gpu-1", "status": "stopping"},
        headers=headers,
    )
    assert invalid.status_code == 422

    store.heartbeat_allowed = False
    stopping = client.post(
        "/api/internal/workers/heartbeat",
        json={"worker_id": "gpu-1", "status": "idle"},
        headers=headers,
    )
    assert stopping.status_code == 409
    assert store.last_worker_heartbeat == ("gpu-1", "idle")


def test_manual_lifecycle_endpoint_requires_dispatcher_auth_and_uses_reconciler(api, monkeypatch):
    client, _, _ = api
    monkeypatch.setenv("MUSICMASTER_DISPATCHER_TOKEN", "d" * 40)
    monkeypatch.setenv("MUSICMASTER_AUTODL_IDLE_SECONDS", "600")
    seen = {}

    class FakeAutoDLClient:
        pass

    def fake_reconcile(**kwargs):
        seen.update(kwargs)
        return {"worker_id": kwargs["worker_id"], "status": "stopping"}

    monkeypatch.setattr(cloud_api, "AutoDLProClient", FakeAutoDLClient)
    monkeypatch.setattr(cloud_api, "reconcile_idle_worker", fake_reconcile)
    denied = client.post("/api/internal/dispatcher/workers/worker-test/reconcile")
    assert denied.status_code == 401

    response = client.post(
        "/api/internal/dispatcher/workers/worker-test/reconcile",
        headers={"Authorization": "Bearer " + "d" * 40},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "stopping"
    assert seen["worker_id"] == "worker-test"
    assert seen["idle_seconds"] == 600



def test_idle_worker_batch_endpoint_defaults_to_read_only_dry_run(api, monkeypatch):
    client, store, _ = api
    monkeypatch.setenv("MUSICMASTER_DISPATCHER_TOKEN", "d" * 40)
    rows = [
        {"worker_id": "worker-old", "instance_uuid": "pro-old", "last_seen_at": "2026-11-25T00:00:00Z"}
    ]
    store.list_stale_idle_workers = lambda **kwargs: rows
    monkeypatch.setattr(
        cloud_api, "AutoDLProClient",
        lambda: (_ for _ in ()).throw(AssertionError("dry-run must not create provider client")),
    )

    denied = client.post("/api/internal/dispatcher/workers/reconcile-idle")
    assert denied.status_code == 401
    response = client.post(
        "/api/internal/dispatcher/workers/reconcile-idle",
        headers={"Authorization": "Bearer " + "d" * 40},
    )
    assert response.status_code == 200
    assert response.json()["dry_run"] is True
    assert response.json()["candidate_count"] == 1
    assert response.json()["workers"][0]["worker_id"] == "worker-old"


def test_idle_worker_batch_endpoint_executes_only_when_dry_run_false(api, monkeypatch):
    client, store, _ = api
    monkeypatch.setenv("MUSICMASTER_DISPATCHER_TOKEN", "d" * 40)
    monkeypatch.setenv("MUSICMASTER_AUTODL_IDLE_SECONDS", "600")
    rows = [
        {"worker_id": "worker-a", "instance_uuid": "pro-a"},
        {"worker_id": "worker-b", "instance_uuid": "pro-b"},
    ]
    store.list_stale_idle_workers = lambda **kwargs: rows
    monkeypatch.setattr(cloud_api, "AutoDLProClient", lambda: object())
    seen = []

    def fake_reconcile(**kwargs):
        seen.append(kwargs["worker_id"])
        if kwargs["worker_id"] == "worker-b":
            raise RuntimeError("provider detail must not leak")
        return {"worker_id": kwargs["worker_id"], "status": "stopping"}

    monkeypatch.setattr(cloud_api, "reconcile_idle_worker", fake_reconcile)
    response = client.post(
        "/api/internal/dispatcher/workers/reconcile-idle",
        json={"dry_run": False, "limit": 2},
        headers={"Authorization": "Bearer " + "d" * 40},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["dry_run"] is False
    assert seen == ["worker-a", "worker-b"]
    assert body["results"][0]["status"] == "stopping"
    assert body["results"][1] == {
        "worker_id": "worker-b", "status": "error", "error": "RuntimeError"
    }



def test_ambiguous_worker_recovery_links_one_exact_provider_match_only(api, monkeypatch):
    client, store, _ = api
    store.worker_record = {
        "worker_id": "worker-test", "status": "error",
        "instance_uuid": None, "active_job_id": None,
    }
    seen = {}

    class FakeAutoDL:
        def find_instances_by_name(self, name):
            seen["name"] = name
            return [{
                "uuid": "pro-recovered",
                "name": name,
                "status": "shutdown",
                "created_at": "2026-11-25T10:00:00+08:00",
            }]

    monkeypatch.setattr(cloud_api, "AutoDLProClient", FakeAutoDL)
    monkeypatch.setenv("MUSICMASTER_DISPATCHER_TOKEN", "d" * 40)
    response = client.post(
        "/api/internal/dispatcher/workers/worker-test/recover-instance",
        headers={"Authorization": "Bearer " + "d" * 40},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "linked"
    assert body["instance_uuid"] == "pro-recovered"
    assert body["provider_mutated"] is False
    assert store.recovered_worker_instance == ("worker-test", "pro-recovered")
    assert seen["name"].startswith("XW-")
    assert len(seen["name"]) == 27


def test_ambiguous_worker_recovery_does_not_link_when_no_listing_match(api, monkeypatch):
    client, store, _ = api
    store.worker_record = {
        "worker_id": "worker-test", "status": "error",
        "instance_uuid": None, "active_job_id": None,
    }

    class FakeAutoDL:
        def find_instances_by_name(self, name):
            return []

    monkeypatch.setattr(cloud_api, "AutoDLProClient", FakeAutoDL)
    monkeypatch.setenv("MUSICMASTER_DISPATCHER_TOKEN", "d" * 40)
    response = client.post(
        "/api/internal/dispatcher/workers/worker-test/recover-instance",
        headers={"Authorization": "Bearer " + "d" * 40},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "not_found"
    assert response.json()["retry_safe"] is False
    assert not hasattr(store, "recovered_worker_instance")


def test_ambiguous_worker_recovery_refuses_duplicate_provider_matches(api, monkeypatch):
    client, store, _ = api
    store.worker_record = {
        "worker_id": "worker-test", "status": "error",
        "instance_uuid": None, "active_job_id": None,
    }

    class FakeAutoDL:
        def find_instances_by_name(self, name):
            return [
                {"uuid": "pro-one", "name": name},
                {"uuid": "pro-two", "name": name},
            ]

    monkeypatch.setattr(cloud_api, "AutoDLProClient", FakeAutoDL)
    monkeypatch.setenv("MUSICMASTER_DISPATCHER_TOKEN", "d" * 40)
    response = client.post(
        "/api/internal/dispatcher/workers/worker-test/recover-instance",
        headers={"Authorization": "Bearer " + "d" * 40},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ambiguous"
    assert response.json()["linked"] is False
    assert not hasattr(store, "recovered_worker_instance")


def test_ambiguous_worker_recovery_rejects_non_error_worker(api, monkeypatch):
    client, store, _ = api
    store.worker_record = {
        "worker_id": "worker-test", "status": "idle",
        "instance_uuid": None, "active_job_id": None,
    }
    monkeypatch.setenv("MUSICMASTER_DISPATCHER_TOKEN", "d" * 40)
    response = client.post(
        "/api/internal/dispatcher/workers/worker-test/recover-instance",
        headers={"Authorization": "Bearer " + "d" * 40},
    )
    assert response.status_code == 409



def test_transcription_home_and_fourth_source_type_contract():
    root = Path(__file__).resolve().parents[1]
    html = (root / "musicmaster/web/static/index.html").read_text(encoding="utf-8")
    upload_js = (root / "musicmaster/web/static/js/full-song-upload.js").read_text(encoding="utf-8")

    assert html.index('id="tab-transcribe"') < html.index('id="tab-convert"')
    assert 'id="tab-transcribe" role="tab" aria-selected="true"' in html
    assert '<div class="panel active" id="p-transcribe"' in html
    assert '<div class="panel active" id="p-convert"' not in html

    assert 'name="tr" value="crepe"' in html
    assert 'name="tr" value="basic-pitch"' in html
    assert 'name="tr" value="bytedance"' in html
    assert 'name="tr" value="full-song"' in html
    assert 'data-source-mode=' not in html
    assert 'input[name="tr"]' in upload_js
    assert 'id="single-audio-input"' in html
    assert 'id="single-source-fields"' in html
    assert 'id="full-song-fields" hidden' in html
    assert 'id="full-song-file"' in html
    assert 'id="full-song-lyrics"' in html
    assert 'id="full-song-artifacts"' in html
    assert '/artifacts/' in upload_js
    assert "noopener noreferrer" in upload_js
