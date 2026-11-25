# -*- coding: utf-8 -*-
"""Cloud job API: durable Postgres queue + private object storage.

The existing local /api endpoints remain unchanged. These routes are used by
the independent production site and the authenticated GPU worker.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import re
import time
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from pydantic import BaseModel, Field
from fastapi.encoders import jsonable_encoder

from musicmaster.cloud.job_store import DispatchCapacityError, JobStoreError, PostgresJobStore
from musicmaster.cloud.object_store import ObjectStoreError, S3ObjectStore
from musicmaster.cloud.autodl_pro import AutoDLProClient
from musicmaster.cloud.dispatcher import create_autodl_worker, worker_instance_name
from musicmaster.cloud.lifecycle import reconcile_idle_worker


router = APIRouter()
logger = logging.getLogger(__name__)
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
        raise HTTPException(status_code=503, detail="Worker API 尚未配置。")
    supplied = (authorization or "").strip()
    if not supplied.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Worker authentication required.")
    token = supplied[7:].strip()
    if not hmac.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="Invalid worker credential.")


def _dispatcher_auth(authorization: str | None = Header(default=None)) -> None:
    expected = os.environ.get("MUSICMASTER_DISPATCHER_TOKEN", "").strip()
    if len(expected) < 32:
        raise HTTPException(status_code=503, detail="Dispatcher API is not configured.")
    supplied = (authorization or "").strip()
    if not supplied.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Dispatcher authentication required.")
    if not hmac.compare_digest(supplied[7:].strip(), expected):
        raise HTTPException(status_code=401, detail="Invalid dispatcher credential.")


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


class WorkerSweepRequest(BaseModel):
    dry_run: bool = True
    limit: int = Field(default=10, ge=1, le=25)


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


def _idempotent_worker_id(idempotency_key: str | None) -> str:
    """Derive a stable opaque worker ID from a caller-provided request key."""
    key = str(idempotency_key or "").strip()
    if not 16 <= len(key) <= 128 or any(ord(char) < 33 or ord(char) > 126 for char in key):
        raise HTTPException(
            status_code=400,
            detail="A 16–128 character printable Idempotency-Key header is required.",
        )
    return "dispatch-" + hashlib.sha256(key.encode("utf-8")).hexdigest()


@router.post("/api/internal/dispatcher/workers", dependencies=[Depends(_dispatcher_auth)])
def provision_cloud_worker(
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    """Provision one worker per idempotency key; retries never create a second GPU."""
    try:
        worker_id = _idempotent_worker_id(idempotency_key)
        store, _ = _components()

        # A replay returns the existing durable record and never calls AutoDL.
        existing = store.get_worker(worker_id)
        if existing is not None:
            return {
                "worker_id": worker_id,
                "instance_uuid": existing.get("instance_uuid"),
                "status": existing.get("status", "unknown"),
                "idempotent_replay": True,
                "retry_safe": False,
                "next_step": (
                    "Inspect and recover this worker; do not submit a new key to retry an ambiguous create."
                    if existing.get("status") == "error" and not existing.get("instance_uuid")
                    else "Use the existing worker record; this request will not provision another instance."
                ),
            }

        api_url = os.environ.get("MUSICMASTER_API_URL", "").strip()
        image_uuid = os.environ.get("MUSICMASTER_AUTODL_IMAGE_UUID", "").strip()
        cuda_value = os.environ.get("MUSICMASTER_AUTODL_CUDA_V_FROM", "").strip()
        if not api_url.startswith("https://") or not image_uuid or not cuda_value:
            raise HTTPException(status_code=503, detail="Dispatcher provisioning settings are incomplete.")
        cuda_v_from = int(cuda_value)
        max_workers = int(os.environ.get("MUSICMASTER_AUTODL_MAX_WORKERS", "1"))
        def replay_existing_worker() -> dict | None:
            # Recheck after acquiring the advisory lock. Two requests can both
            # miss the first lookup before either inserts its deterministic ID.
            existing = store.get_worker(worker_id)
            if existing is None:
                return None
            return {
                "worker_id": worker_id,
                "instance_uuid": existing.get("instance_uuid"),
                "status": existing.get("status", "unknown"),
                "idempotent_replay": True,
                "retry_safe": False,
                "next_step": (
                    "Inspect and recover this worker; do not submit a new key to retry an ambiguous create."
                    if existing.get("status") == "error" and not existing.get("instance_uuid")
                    else "Use the existing worker record; this request will not provision another instance."
                ),
            }

        result = store.run_with_dispatch_capacity(
            max_workers,
            lambda: create_autodl_worker(
                store=store,
                autodl_client=AutoDLProClient(),
                api_url=api_url,
                image_uuid=image_uuid,
                cuda_v_from=cuda_v_from,
                worker_id=worker_id,
            ),
            replay_if=replay_existing_worker,
        )
    except HTTPException:
        raise
    except DispatchCapacityError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except (TypeError, ValueError):
        raise HTTPException(status_code=503, detail="Dispatcher capacity configuration is invalid.") from None
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503,
            detail=f"Worker provisioning failed: {type(exc).__name__}",
        ) from None
    return result


@router.post(
    "/api/internal/dispatcher/dispatch-queued",
    dependencies=[Depends(_dispatcher_auth)],
)
def dispatch_queued_cloud_jobs() -> dict:
    """Automatic queue dispatch is intentionally disabled: only existing workers may be used."""
    return {"enabled": False, "status": "disabled", "queued_jobs": 0}


@router.post(
    "/api/internal/dispatcher/workers/{worker_id}/recover-instance",
    dependencies=[Depends(_dispatcher_auth)],
)
def recover_ambiguous_worker_instance(worker_id: str) -> dict:
    """Find and link a uniquely tagged instance after an ambiguous create timeout.

    The endpoint is intentionally read-only with respect to AutoDL. A missing
    listing match is not permission to retry creation because provider listing
    may lag; multiple matches are never auto-selected.
    """
    try:
        store, _ = _components()
        worker = store.get_worker(worker_id)
        if worker is None:
            raise HTTPException(status_code=404, detail="Worker not found.")
        if (worker.get("status") != "error" or worker.get("instance_uuid")
                or worker.get("active_job_id") is not None):
            raise HTTPException(
                status_code=409,
                detail="Worker is not an unresolved provisioning error.",
            )

        client = AutoDLProClient()
        name = worker_instance_name(worker_id)
        matches = client.find_instances_by_name(name)
        if not matches:
            return {
                "worker_id": worker_id,
                "status": "not_found",
                "instance_name": name,
                "retry_safe": False,
                "message": "No exact match in the complete current listing; wait and check again before retrying creation.",
            }
        if len(matches) != 1:
            return {
                "worker_id": worker_id,
                "status": "ambiguous",
                "match_count": len(matches),
                "instance_name": name,
                "linked": False,
            }

        match = matches[0]
        instance_uuid = match["uuid"]
        if not store.recover_worker_instance(worker_id, instance_uuid):
            raise HTTPException(
                status_code=409,
                detail="Worker changed during recovery; reload its current state.",
            )
        return {
            "worker_id": worker_id,
            "instance_uuid": instance_uuid,
            "provider_status": match.get("status"),
            "status": "linked",
            "linked": True,
            "provider_mutated": False,
            "next_step": "Review the instance in AutoDL before any manual power-on or cleanup.",
        }
    except HTTPException:
        raise
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid worker ID or recovery configuration.") from None
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503,
            detail=f"Ambiguous worker recovery failed: {type(exc).__name__}",
        ) from None


@router.post(
    "/api/internal/dispatcher/workers/{worker_id}/reconcile",
    dependencies=[Depends(_dispatcher_auth)],
)
def reconcile_cloud_worker(worker_id: str) -> dict:
    """Manually reconcile one stale idle worker; never release an unconfirmed instance."""
    idle_value = os.environ.get("MUSICMASTER_AUTODL_IDLE_SECONDS", "300")
    try:
        idle_seconds = int(idle_value)
        if not 60 <= idle_seconds <= 86400:
            raise ValueError
        store, _ = _components()
        client = AutoDLProClient()
        return reconcile_idle_worker(
            store=store,
            autodl_client=client,
            worker_id=worker_id,
            idle_seconds=idle_seconds,
        )
    except LookupError:
        raise HTTPException(status_code=404, detail="Worker not found.") from None
    except ValueError:
        raise HTTPException(status_code=503, detail="Worker lifecycle configuration or ID is invalid.") from None
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503,
            detail=f"Worker lifecycle reconciliation failed: {type(exc).__name__}",
        ) from None


@router.post(
    "/api/internal/dispatcher/workers/reconcile-idle",
    dependencies=[Depends(_dispatcher_auth)],
)
def reconcile_idle_cloud_workers(request: WorkerSweepRequest) -> dict:
    """Batch-reconcile stale idle workers; dry-run is the default and is read-only."""
    idle_value = os.environ.get("MUSICMASTER_AUTODL_IDLE_SECONDS", "300")
    try:
        idle_seconds = int(idle_value)
        if not 60 <= idle_seconds <= 86400:
            raise ValueError
        store, _ = _components()
        candidates = store.list_stale_idle_workers(
            idle_seconds=idle_seconds, limit=request.limit
        )
        if request.dry_run:
            return {
                "dry_run": True,
                "candidate_count": len(candidates),
                "workers": [
                    {
                        "worker_id": row["worker_id"],
                        "instance_uuid": row["instance_uuid"],
                        "last_seen_at": row.get("last_seen_at"),
                    }
                    for row in candidates
                ],
            }

        client = AutoDLProClient()
        results = []
        for row in candidates:
            worker_id = row["worker_id"]
            try:
                results.append(reconcile_idle_worker(
                    store=store,
                    autodl_client=client,
                    worker_id=worker_id,
                    idle_seconds=idle_seconds,
                ))
            except Exception as exc:  # noqa: BLE001
                # One provider/API failure must not hide the outcome for the rest
                # of this bounded batch. Do not expose provider messages/secrets.
                results.append({
                    "worker_id": worker_id,
                    "status": "error",
                    "error": type(exc).__name__,
                })
        return {
            "dry_run": False,
            "candidate_count": len(candidates),
            "results": results,
        }
    except ValueError:
        raise HTTPException(status_code=503, detail="Worker lifecycle configuration is invalid.") from None
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=503,
            detail=f"Worker batch reconciliation failed: {type(exc).__name__}",
        ) from None


@router.post("/api/cloud/jobs")
def create_cloud_job(
    audio: UploadFile = File(...),
    engine: str = Form("crepe"),
    key: str = Form(""),
    stages: str = Form("1,2,3"),
    denoise: str = Form("dereverb"),
    lyrics: str = Form(""),
) -> dict:
    """Upload one full mix and optional user-provided V1 lyrics into a durable job."""
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
    if len(lyrics) > 100_000:
        raise HTTPException(status_code=413, detail="歌词文本暂时不能超过 100,000 个字符。")
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

    request_started = time.monotonic()
    request_id = uuid.uuid4().hex[:12]
    content_type = audio.content_type or "application/octet-stream"
    logger.info(
        "cloud_upload accepted request_id=%s filename=%s size_bytes=%s content_type=%s",
        request_id, filename, size_bytes, content_type,
    )
    store, objects = _components()
    job_id = uuid.uuid4()
    object_key = f"jobs/{job_id}/source/{filename}"
    try:
        stage_started = time.monotonic()
        logger.info("cloud_upload object_store_start request_id=%s job_id=%s", request_id, job_id)
        objects.upload_fileobj(audio.file, object_key, content_type=content_type)
        logger.info(
            "cloud_upload object_store_complete request_id=%s job_id=%s elapsed_ms=%d",
            request_id, job_id, int((time.monotonic() - stage_started) * 1000),
        )
        stage_started = time.monotonic()
        logger.info("cloud_upload database_create_start request_id=%s job_id=%s", request_id, job_id)
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
                "lyrics": lyrics,
                "auto_dispatch_requested": False,
            },
            max_attempts=2,
        )
        if not store.mark_upload_complete(job_id, size_bytes):
            raise JobStoreError("The uploaded job could not be queued.")
        logger.info(
            "cloud_upload queued request_id=%s job_id=%s size_bytes=%s database_elapsed_ms=%d total_elapsed_ms=%d",
            request_id, job_id, size_bytes,
            int((time.monotonic() - stage_started) * 1000),
            int((time.monotonic() - request_started) * 1000),
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "cloud_upload failed request_id=%s job_id=%s error_type=%s total_elapsed_ms=%d",
            request_id, job_id, type(exc).__name__,
            int((time.monotonic() - request_started) * 1000),
        )
        try:
            objects.delete(object_key)
        except Exception:
            pass
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=503, detail=f"任务提交失败：{type(exc).__name__}") from None
    # Full-song uploads are always manual-start: this route never provisions
    # or powers on a GPU, even if a legacy auto-dispatch flag is present.
    return {"job_id": str(job_id), "status": "queued", "dispatch": "manual"}


@router.post("/api/cloud/jobs/{job_id}/start")
def start_cloud_job(job_id: str) -> dict:
    """Allow a queued job to be claimed by an already-running, recently-heartbeating worker.

    This endpoint never provisions, powers on, or otherwise changes GPU resources.
    """
    store, _ = _components()
    try:
        job = store.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="未找到这个云端任务。")
        state = str(job.get("status") or "").lower()
        if state in {"running", "completed"}:
            return {"job_id": str(job_id), "status": state, "already_started": True}
        if state != "queued":
            raise HTTPException(status_code=409, detail=f"当前任务状态为 {state or 'unknown'}，暂时不能开始记谱。")
        if not store.has_live_worker(heartbeat_seconds=120):
            raise HTTPException(
                status_code=409,
                detail="当前没有在线计算 Worker，请等待 Colab Worker 连接并上线后再点击「开始记谱」。任务已保留，不会自动创建或启动 GPU。",
            )
        store.request_job_start(job_id)
        latest = store.get_job(job_id) or job
        latest_state = str(latest.get("status") or "queued").lower()
        return {
            "job_id": str(job_id),
            "status": latest_state,
            "worker_available": True,
            "message": "已通知现有计算 Worker 领取任务；没有自动创建或启动 GPU。",
        }
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=404, detail="无效的任务编号。") from None
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"任务启动检查失败：{type(exc).__name__}") from None


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


@router.get("/api/internal/worker/bundle", dependencies=[Depends(_worker_auth)])
def get_worker_source_bundle() -> dict:
    """Return a short-lived URL for the immutable, pre-published worker source bundle."""
    commit = os.environ.get("MUSICMASTER_WORKER_BUNDLE_COMMIT", "").strip().lower()
    digest = os.environ.get("MUSICMASTER_WORKER_BUNDLE_SHA256", "").strip().lower()
    object_key = os.environ.get("MUSICMASTER_WORKER_BUNDLE_KEY", "").strip()
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise HTTPException(status_code=503, detail="Worker source bundle commit is not configured.")
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise HTTPException(status_code=503, detail="Worker source bundle checksum is not configured.")
    expected_prefix = f"worker-bundles/{commit}/"
    if not object_key.startswith(expected_prefix) or not object_key.endswith(f"/{digest}.tar.gz"):
        raise HTTPException(status_code=503, detail="Worker source bundle object key is invalid.")
    _, objects = _components()
    try:
        url = objects.presigned_download(object_key, expires_seconds=600)
    except ObjectStoreError:
        raise HTTPException(status_code=503, detail="Could not issue worker source bundle URL.") from None
    return {
        "repository_commit": commit,
        "object_key": object_key,
        "sha256": digest,
        "url": url,
        "expires_in": 600,
    }


@router.post("/api/internal/workers/register", dependencies=[Depends(_worker_auth)])
def register_worker(body: WorkerRegister) -> dict:
    store, _ = _components()
    row = store.register_worker(body.worker_id, body.instance_uuid)
    return {"ok": True, "worker_id": row["worker_id"], "status": row["status"]}


@router.post("/api/internal/workers/heartbeat", dependencies=[Depends(_worker_auth)])
def worker_heartbeat(body: WorkerHeartbeat) -> dict:
    store, _ = _components()
    if body.status not in {"idle", "busy"}:
        raise HTTPException(status_code=422, detail="Worker heartbeat status must be idle or busy.")
    if not store.heartbeat_worker(body.worker_id, body.status):
        raise HTTPException(
            status_code=409,
            detail="Worker is stopping, stopped, or its active-job state does not match the heartbeat.",
        )
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
        # The job has already been claimed. Release it back to the queue so a
        # temporary object-store signing outage cannot strand it until lease expiry.
        store.fail_job(
            job["id"], body.worker_id,
            "暂时无法签发原始音频下载链接，请稍后重试。",
            retryable=True,
        )
        raise HTTPException(status_code=503, detail="暂时无法为 GPU 节点签发音频下载链接，任务已重新排队。") from None
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
