# -*- coding: utf-8 -*-
from datetime import datetime, timezone
from io import BytesIO
from uuid import uuid4

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
        }
        self.jobs[str(job_id)] = row
        return row

    def mark_upload_complete(self, job_id, size_bytes):
        self.jobs[str(job_id)]["status"] = "queued"
        self.jobs[str(job_id)]["source_size_bytes"] = size_bytes
        return True

    def get_job(self, job_id):
        return self.jobs.get(str(job_id))

    def list_artifacts(self, job_id):
        return list(self.artifacts)

    def claim_next(self, worker_id, lease_seconds=180):
        return None

    def register_worker(self, worker_id, instance_uuid=None):
        return {"worker_id": worker_id, "status": "idle"}

    def set_worker_status(self, worker_id, status):
        return True

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


def test_cloud_upload_creates_private_object_and_queues_job(api):
    client, store, objects = api
    response = client.post(
        "/api/cloud/jobs",
        files={"audio": ("原曲.mp3", b"audio-bytes", "audio/mpeg")},
        data={"engine": "crepe", "stages": "1,2,3", "denoise": "dereverb"},
    )
    assert response.status_code == 200
    result = response.json()
    assert result["status"] == "queued"
    assert objects.uploaded[0] == b"audio-bytes"
    assert objects.uploaded[1].startswith(f"jobs/{result['job_id']}/source/")
    assert store.jobs[result["job_id"]]["status"] == "queued"
    assert store.jobs[result["job_id"]]["source_size_bytes"] == len(b"audio-bytes")


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
        headers={"Authorization": "Bearer wrong"},
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
        headers={"Authorization": "Bearer " + "d" * 40},
    )

    assert response.status_code == 200
    assert response.json()["instance_uuid"] == "pro-test123"
    assert seen["client_created"] is True
    assert seen["store"] is store
    assert seen["api_url"] == "https://api.example.test"
    assert seen["image_uuid"] == "configured-image"
    assert seen["cuda_v_from"] == 124
    assert "bootstrap_token" not in str(response.json()).lower()
