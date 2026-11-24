# -*- coding: utf-8 -*-
"""Cloud job API: durable Postgres queue + private object storage.

The existing local /api endpoints remain unchanged. These routes are used by
the independent production site and the authenticated GPU worker.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from pydantic import BaseModel, Field
from fastapi.encoders import jsonable_encoder

from musicmaster.cloud.job_store import JobStoreError, PostgresJobStore
from musicmaster.cloud.object_store import ObjectStoreError, S3ObjectStore


router = APIRouter()
MAX_UPLOAD_BYTES = 250 * 1024 * 1024
ALLOWED_EXTENSIONS = {".mp3", ".wav", ".flac", ".m4a", ".ogg"}
SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._()\-\u4e00-\u9fff]+")


@lru_cache(maxsize=1)
def _components() -> tuple[PostgresJobStore, S3ObjectStore]:
    try:
        return PostgresJobStore(), S3ObjectStore()
    except (ValueError, JobStoreError, ObjectStoreError) as exc:
        raise HTTPException(status_code=503, detail=f"云端任务服务尚未配置：{exc}") from None


def _worker_auth(authorization: str | None = Header(default=None)) -> None:
    expected = os.environ.get("MUSICMASTER_WORKER_TOKEN", "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="GPU worker API 尚未配置。")
    supplied = (authorization or "").strip()
    if not supplied.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Worker authentication required.")
    token = supplied[7:].strip()
    if not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="Invalid worker credential.")


def _safe_filename(value: str) -> str:
    name = Path(value or "audio-upload").name.strip().rstrip(" .")
    name = SAFE_FILENAME.sub("_", name)[:160]
    if not name or name in {".", ".."}:
        return "audio-upload"
    return name


def _public_job(job: dict[str, Any]) -> dict[str, Any]:
    allowed = (
        "id", "status", "stage", "progress", "source_filename",
        "source_size_bytes", "options", "result", "error",
        "attempt_count", "max_attempts", "created_at", "updated_at",
        "started_at", "completed_at",
    )
    return {key: job.get(key) for key in allowed}


class BootstrapRequest(BaseModel):
    bootstrap_token: str = Field(min_length=32, max_length=256)


class WorkerRegister(BaseModel):
    worker_id: str = Field(min_length=1, max_length=128)
    instance_uuid: str | None = Field(default=None, max_length=128)


class WorkerHeartbeat(BaseModel):
    worker_id: str = Field(min_length=1, max_length=128)
    status: str = Field(default="idle", pattern="^(starting|idle|busy|stopping|stopped|error)$")


class ClaimRequest(BaseModel):
    worker_id: str = Field(min_length=1, max_length=128)
    lease_seconds: int = Field(default=180, ge=30, le=900)


class ProgressRequest(BaseModel):
    worker_id: str = Field(min_length=1, max_length=128)
    progress: float = Field(ge=0, le=1)
    stage: str = Field(default="处理中", max_length=200)
    lease_seconds: int = Field(default=180, ge=30, le=900)


class ArtifactURLRequest(BaseModel):
    worker_id: str = Field(min_length=1, max_length=128)
    file_name: str = Field(min_length=1, max_length=200)
    role: str = Field(default="result", max_length=40)
    content_type: str = Field(default="application/octet-stream", max_length=120)


class ArtifactCompleteRequest(BaseModel):
    worker_id: str = Field(min_length=1, max_length=128)
    object_key: str = Field(min_length=1, max_length=1024)
    file_name: str = Field(min_length=1, max_length=200)
    role: str = Field(default="result", max_length=40)
    content_type: str = Field(default="application/octet-stream", max_length=120)


class CompleteRequest(BaseModel):
    worker_id: str = Field(min_length=1, max_length=128)
    result: dict[str, Any] = Field(default_factory=dict)


class FailRequest(BaseModel):
    worker_id: str = Field(min_length=1, max_length=128)
    error: str = Field(min_length=1, max_length=1000)
    retryable: bool = False


@router.get("/api/cloud/health")
def cloud_health() -> dict:
    _components()
    return {"ok": True, "service": "musicmaster-cloud-jobs"}


@router.post("/api/cloud/jobs")
def create_cloud_job(
    audio: UploadFile = File(...),
    engine: str = Form("crepe"),
    key: str = Form(""),
    stages: str = Form("1,2,3"),
    denoise: str = Form("dereverb"),
) -> dict:
    """Upload one full mix into private storage and enqueue a durable job."""
    if engine != "crepe":
        raise HTTPException(status_code=422, detail="V1 云端整曲流程目前仅开放 CREPE 主旋律引擎。")
    stage_list = [part.strip() for part in stages.split(",") if part.strip()]
    if (not stage_list or stage_list[0] != "1"
            or stage_list != sorted(stage_list)
            or len(stage_list) != len(set(stage_list))
            or any(part not in {"1", "2", "3"} for part in stage_list)):
        raise HTTPException(status_code=422, detail="处理段必须按顺序从 1 开始，例如 1,2,3。")
    if denoise not in {"dereverb", "deecho"}:
        raise HTTPException(status_code=422, detail="denoise 仅支持 dereverb / deecho。")
    filename = _safe_filename(audio.filename or "audio-upload")
    if Path(filename).suffix.lower() not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=415, detail="请上传 MP3、WAV、FLAC、M4A 或 OGG 音频。")
    audio.file.seek(0, os.SEEK_END)
    size_bytes = audio.file.tell()
    audio.file.seek(0)
    if size_bytes <= 0:
        raise HTTPException(status_code=400, detail="上传文件为空。")
    if size_bytes > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="单个音频文件暂时不能超过 250 MB。")

    store, objects = _components()
    job_id = uuid.uuid4()
    object_key = f"jobs/{job_id}/source/{filename}"
    content_type = audio.content_type or "application/octet-stream"
    try:
        objects.upload_fileobj(audio.file, object_key, content_type=content_type)
        store.create_job(
            job_id,
            source_object_key=object_key,
            source_filename=filename,
            source_content_type=content_type,
            options={
                "engine": engine,
                "key": key.strip(),
                "stages": ",".join(stage_list),
                "denoise": denoise,
            },
            max_attempts=2,
        )
        if not store.mark_upload_complete(job_id, size_bytes):
            raise JobStoreError("The uploaded job could not be queued.")
    except Exception as exc:  # noqa: BLE001
        try:
            objects.delete(object_key)
        except Exception:
            pass
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=503, detail=f"任务提交失败：{type(exc).__name__}") from None
    return {"job_id": str(job_id), "status": "queued"}


@router.get("/api/cloud/jobs/{job_id}")
def get_cloud_job(job_id: str) -> dict:
    store, _ = _components()
    try:
        job = store.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="未找到这个云端任务。")
        artifacts = store.list_artifacts(job_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="无效的任务编号。") from None
    return {
        "job": jsonable_encoder(_public_job(job)),
        "artifacts": jsonable_encoder(artifacts),
    }


@router.get("/api/cloud/jobs/{job_id}/artifacts/{artifact_id}/download")
def get_artifact_download_url(job_id: str, artifact_id: int) -> dict:
    store, objects = _components()
    try:
        job = store.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="未找到这个云端任务。")
        artifact = next(
            (item for item in store.list_artifacts(job_id) if int(item["id"]) == artifact_id),
            None,
        )
    except ValueError:
        raise HTTPException(status_code=404, detail="无效的任务编号。") from None
    if artifact is None:
        raise HTTPException(status_code=404, detail="未找到这个文件。")
    try:
        url = objects.presigned_download(artifact["object_key"], expires_seconds=900)
    except ObjectStoreError:
        raise HTTPException(status_code=503, detail="暂时无法生成文件下载链接。") from None
    return {"url": url, "expires_in": 900, "file_name": artifact["file_name"]}


@router.post("/api/internal/bootstrap")
def bootstrap_worker(body: BootstrapRequest) -> dict:
    """Exchange one short-lived bootstrap secret for the worker API token exactly once."""
    worker_token = os.environ.get("MUSICMASTER_WORKER_TOKEN", "").strip()
    if not worker_token:
        raise HTTPException(status_code=503, detail="Worker API is not configured.")
    store, _ = _components()
    digest = hashlib.sha256(body.bootstrap_token.encode("utf-8")).hexdigest()
    try:
        record = store.consume_bootstrap_token(digest)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"Bootstrap lookup failed: {type(exc).__name__}") from None
    if record is None:
        raise HTTPException(status_code=401, detail="Bootstrap token is invalid, expired or already used.")
    return {
        "worker_token": worker_token,
        "worker_id": record["worker_id"],
        "instance_uuid": record.get("instance_uuid"),
    }


@router.post("/api/internal/workers/register", dependencies=[Depends(_worker_auth)])
def register_worker(body: WorkerRegister) -> dict:
    store, _ = _components()
    row = store.register_worker(body.worker_id, body.instance_uuid)
    return {"ok": True, "worker_id": row["worker_id"], "status": row["status"]}


@router.post("/api/internal/workers/heartbeat", dependencies=[Depends(_worker_auth)])
def worker_heartbeat(body: WorkerHeartbeat) -> dict:
    store, _ = _components()
    if not store.set_worker_status(body.worker_id, body.status):
        raise HTTPException(status_code=404, detail="Unknown worker; register it first.")
    return {"ok": True}


@router.post("/api/internal/jobs/claim", dependencies=[Depends(_worker_auth)])
def claim_job(body: ClaimRequest) -> dict:
    store, objects = _components()
    job = store.claim_next(body.worker_id, lease_seconds=body.lease_seconds)
    if job is None:
        return {"job": None}
    try:
        source_url = objects.presigned_download(job["source_object_key"], expires_seconds=1800)
    except ObjectStoreError:
        raise HTTPException(status_code=503, detail="暂时无法为 GPU 节点签发音频下载链接。") from None
    return {
        "job": {
            "id": str(job["id"]),
            "source_filename": job["source_filename"],
            "source_content_type": job["source_content_type"],
            "source_url": source_url,
            "options": job["options"],
            "attempt_count": job["attempt_count"],
        }
    }


@router.post("/api/internal/jobs/{job_id}/heartbeat", dependencies=[Depends(_worker_auth)])
def job_heartbeat(job_id: str, body: ProgressRequest) -> dict:
    store, _ = _components()
    try:
        updated = store.heartbeat_job(
            job_id, body.worker_id, progress=body.progress, stage=body.stage,
            lease_seconds=body.lease_seconds,
        )
    except ValueError:
        raise HTTPException(status_code=404, detail="Invalid job_id.") from None
    if not updated:
        raise HTTPException(status_code=409, detail="This worker no longer owns the job.")
    return {"ok": True}


@router.post("/api/internal/jobs/{job_id}/artifact-url", dependencies=[Depends(_worker_auth)])
def create_artifact_upload_url(job_id: str, body: ArtifactURLRequest) -> dict:
    store, objects = _components()
    try:
        job = store.get_job(job_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Invalid job_id.") from None
    if not job or job["status"] != "running" or job["worker_id"] != body.worker_id:
        raise HTTPException(status_code=409, detail="This worker no longer owns the job.")
    filename = _safe_filename(body.file_name)
    object_key = f"jobs/{job['id']}/artifacts/{uuid.uuid4().hex}/{filename}"
    try:
        url = objects.presigned_upload(
            object_key, content_type=body.content_type, expires_seconds=900
        )
    except ObjectStoreError:
        raise HTTPException(status_code=503, detail="暂时无法生成文件上传链接。") from None
    return {
        "object_key": object_key,
        "url": url,
        "method": "PUT",
        "headers": {"Content-Type": body.content_type},
        "expires_in": 900,
    }


@router.post("/api/internal/jobs/{job_id}/artifact-complete", dependencies=[Depends(_worker_auth)])
def confirm_artifact_upload(job_id: str, body: ArtifactCompleteRequest) -> dict:
    store, objects = _components()
    try:
        job = store.get_job(job_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Invalid job_id.") from None
    if not job or job["status"] != "running" or job["worker_id"] != body.worker_id:
        raise HTTPException(status_code=409, detail="This worker no longer owns the job.")
    expected_prefix = f"jobs/{job['id']}/artifacts/"
    if not body.object_key.startswith(expected_prefix):
        raise HTTPException(status_code=422, detail="Artifact key does not belong to this job.")
    try:
        head = objects.head(body.object_key)
        artifact = store.add_artifact(
            job_id, body.worker_id, object_key=body.object_key,
            file_name=_safe_filename(body.file_name), role=body.role,
            content_type=head["content_type"], size_bytes=head["size_bytes"],
        )
    except (ObjectStoreError, JobStoreError):
        raise HTTPException(status_code=400, detail="文件尚未成功上传，或任务归属已变化。") from None
    return {"ok": True, "artifact_id": artifact["id"], "size_bytes": head["size_bytes"]}


@router.post("/api/internal/jobs/{job_id}/complete", dependencies=[Depends(_worker_auth)])
def complete_cloud_job(job_id: str, body: CompleteRequest) -> dict:
    store, _ = _components()
    try:
        job = store.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Unknown job.")
        artifacts = store.list_artifacts(job_id)
        names = {Path(item["file_name"]).name for item in artifacts}
        missing = {"notes.json", "out.mid", "out.musicxml"} - names
        if missing:
            raise HTTPException(
                status_code=409,
                detail="Required score artifacts missing: " + ", ".join(sorted(missing)),
            )
        if not store.complete_job(job_id, body.worker_id, body.result):
            raise HTTPException(status_code=409, detail="This worker no longer owns the job.")
    except ValueError:
        raise HTTPException(status_code=404, detail="Invalid job_id.") from None
    return {"ok": True, "status": "completed"}


@router.post("/api/internal/jobs/{job_id}/fail", dependencies=[Depends(_worker_auth)])
def fail_cloud_job(job_id: str, body: FailRequest) -> dict:
    store, _ = _components()
    try:
        status = store.fail_job(job_id, body.worker_id, body.error, retryable=body.retryable)
    except ValueError:
        raise HTTPException(status_code=404, detail="Invalid job_id.") from None
    if status is None:
        raise HTTPException(status_code=409, detail="This worker no longer owns the job.")
    return {"ok": True, "status": status}
