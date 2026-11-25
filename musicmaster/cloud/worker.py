# -*- coding: utf-8 -*-
"""Long-polling GPU worker for the authenticated cloud job API."""
from __future__ import annotations

import http.client
import json
import mimetypes
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


class RetryableWorkerError(RuntimeError):
    """A temporary network or object-storage failure safe to retry once."""


def _config() -> tuple[str, str, str, str | None]:
    base = os.environ.get("MUSICMASTER_API_URL", "").strip().rstrip("/")
    token = os.environ.get("MUSICMASTER_WORKER_TOKEN", "").strip()
    worker_id = os.environ.get("MUSICMASTER_WORKER_ID", "").strip()
    instance_id = os.environ.get("MUSICMASTER_INSTANCE_UUID", "").strip() or None
    if not base.startswith("https://"):
        raise ValueError("MUSICMASTER_API_URL must be an HTTPS URL.")

    # AutoDL start_command carries a short-lived, single-use bootstrap token,
    # never the long-lived worker credential.
    bootstrap = os.environ.get("MUSICMASTER_BOOTSTRAP_TOKEN", "").strip()
    if not token and bootstrap:
        body = json.dumps({"bootstrap_token": bootstrap}).encode("utf-8")
        request = urllib.request.Request(
            base + "/api/internal/bootstrap",
            data=body,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                result = json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Worker bootstrap failed: {type(exc).__name__}") from None
        token = str(result.get("worker_token") or "").strip()
        worker_id = worker_id or str(result.get("worker_id") or "").strip()
        instance_id = instance_id or result.get("instance_uuid")
        if token:
            os.environ["MUSICMASTER_WORKER_TOKEN"] = token
        if worker_id:
            os.environ["MUSICMASTER_WORKER_ID"] = worker_id
        if instance_id:
            os.environ["MUSICMASTER_INSTANCE_UUID"] = str(instance_id)

    worker_id = worker_id or socket.gethostname()
    if not token:
        raise ValueError("Set MUSICMASTER_WORKER_TOKEN or a valid MUSICMASTER_BOOTSTRAP_TOKEN.")
    return base, token, worker_id, instance_id


def _api(
    base: str,
    token: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout: int = 30,
) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        base + path,
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        message = f"Worker API HTTP {exc.code}: {detail}"
        if exc.code == 429 or exc.code >= 500:
            raise RetryableWorkerError(message) from None
        raise RuntimeError(message) from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RetryableWorkerError(
            f"Worker API connection failed: {type(exc).__name__}"
        ) from None
    try:
        result = json.loads(raw.decode("utf-8")) if raw else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise RuntimeError("Worker API returned invalid JSON.") from None
    if not isinstance(result, dict):
        raise RuntimeError("Worker API response must be a JSON object.")
    return result


def _download(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "XinsW-Music-Worker/1"})
    try:
        with urllib.request.urlopen(request, timeout=1800) as response, destination.open("wb") as out:
            shutil.copyfileobj(response, out, length=1024 * 1024)
    except urllib.error.HTTPError as exc:
        if exc.code == 429 or exc.code >= 500:
            raise RetryableWorkerError(f"Audio download HTTP {exc.code}.") from None
        raise RuntimeError(f"Audio download HTTP {exc.code}.") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RetryableWorkerError(
            f"Audio download failed: {type(exc).__name__}"
        ) from None


def _put_file(url: str, file_path: Path, content_type: str) -> None:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        raise ValueError("The artifact upload URL must be HTTPS.")
    path = urllib.parse.urlunsplit(("", "", parts.path, parts.query, ""))
    size = file_path.stat().st_size
    connection = http.client.HTTPSConnection(parts.hostname, parts.port or 443, timeout=1800)
    try:
        connection.putrequest("PUT", path)
        connection.putheader("Host", parts.netloc)
        connection.putheader("Content-Type", content_type)
        connection.putheader("Content-Length", str(size))
        connection.endheaders()
        with file_path.open("rb") as source:
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                connection.send(chunk)
        response = connection.getresponse()
        detail = response.read(500).decode("utf-8", errors="replace")
        if response.status not in (200, 201, 204):
            message = f"Artifact upload failed (HTTP {response.status}): {detail}"
            if response.status == 429 or response.status >= 500:
                raise RetryableWorkerError(message)
            raise RuntimeError(message)
    except (TimeoutError, OSError) as exc:
        raise RetryableWorkerError(
            f"Artifact upload connection failed: {type(exc).__name__}"
        ) from None
    finally:
        connection.close()


def _artifact_role(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".wav", ".mp3", ".flac", ".m4a", ".ogg"}:
        return "audio"
    if suffix in {".mid", ".midi", ".musicxml", ".xml", ".pdf", ".svg", ".ly"}:
        return "score"
    return "metadata"


def _process_job(
    base: str,
    token: str,
    worker_id: str,
    job: dict[str, Any],
) -> None:
    from musicmaster.workflows.full_transcribe import run_full_transcription

    job_id = str(job["id"])
    options = job.get("options") or {}
    source_name = Path(str(job.get("source_filename") or "source-audio")).name
    work_root = Path(os.environ.get("MUSICMASTER_WORKER_DATA", tempfile.gettempdir()))
    work_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"xinsw-{job_id[:8]}-", dir=work_root) as temp:
        root = Path(temp)
        source = root / source_name
        output = root / "output"

        # Renew the claim before any potentially long network/model operation.
        # Keep the lease alive until all artifacts are uploaded and completion
        # has been acknowledged by the API.
        state = {"progress": 0.01, "stage": "准备下载原始音频…", "last_sent": 0.0}
        state_lock = threading.Lock()
        stop_heartbeat = threading.Event()

        def send_heartbeat() -> None:
            with state_lock:
                progress_value = state["progress"]
                stage_label = state["stage"]
            _api(
                base, token, "POST", f"/api/internal/jobs/{job_id}/heartbeat",
                {
                    "worker_id": worker_id,
                    "progress": max(0.0, min(0.99, float(progress_value))),
                    "stage": stage_label,
                    "lease_seconds": 300,
                },
            )

        def heartbeat_loop() -> None:
            while not stop_heartbeat.wait(30):
                try:
                    send_heartbeat()
                except Exception as exc:  # noqa: BLE001
                    print(f"[cloud-worker] heartbeat warning: {type(exc).__name__}", flush=True)

        heartbeat_thread = threading.Thread(target=heartbeat_loop, daemon=True)
        heartbeat_thread.start()

        def progress(value: float, stage: str) -> None:
            now = time.monotonic()
            with state_lock:
                state["progress"] = max(0.0, min(0.99, float(value)))
                state["stage"] = str(stage)[:200]
                should_send = now - state["last_sent"] >= 4
                if should_send:
                    state["last_sent"] = now
            if should_send:
                send_heartbeat()

        try:
            send_heartbeat()
            _download(str(job["source_url"]), source)
            with state_lock:
                state["progress"] = 0.03
                state["stage"] = "音频已下载，开始分离与识别…"

            run_full_transcription(
                source,
                output,
                engine=str(options.get("engine") or "crepe"),
                key=str(options.get("key") or ""),
                stages=str(options.get("stages") or "1,2,3"),
                denoise=str(options.get("denoise") or "dereverb"),
                lyrics_text=str(options.get("lyrics") or ""),
                progress_callback=progress,
            )

            manifest_path = output / "job_result.json"
            if not manifest_path.is_file():
                raise RuntimeError("Full transcription completed without job_result.json.")

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            relative_paths = {
                manifest.get("separation", {}).get("final_vocal"),
                manifest.get("separation", {}).get("accompaniment"),
                *((manifest.get("transcription", {}).get("files") or {}).values()),
                "job_result.json",
            }
            files = []
            for relative in sorted(path for path in relative_paths if path):
                file_path = (output / relative).resolve()
                try:
                    file_path.relative_to(output.resolve())
                except ValueError:
                    raise RuntimeError("The workflow returned an unsafe artifact path.") from None
                if file_path.is_file():
                    files.append(file_path)

            required_names = {"notes.json", "out.mid", "out.musicxml"}
            if not required_names.issubset({path.name for path in files}):
                raise RuntimeError(
                    "The workflow did not produce notes.json, out.mid and out.musicxml."
                )

            for file_path in files:
                filename = file_path.name
                content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
                upload = _api(
                    base, token, "POST", f"/api/internal/jobs/{job_id}/artifact-url",
                    {
                        "worker_id": worker_id,
                        "file_name": filename,
                        "role": _artifact_role(file_path),
                        "content_type": content_type,
                    },
                )
                _put_file(str(upload["url"]), file_path, content_type)
                _api(
                    base, token, "POST", f"/api/internal/jobs/{job_id}/artifact-complete",
                    {
                        "worker_id": worker_id,
                        "object_key": upload["object_key"],
                        "file_name": filename,
                        "role": _artifact_role(file_path),
                        "content_type": content_type,
                    },
                )

            _api(
                base, token, "POST", f"/api/internal/jobs/{job_id}/complete",
                {"worker_id": worker_id, "result": manifest},
            )
        finally:
            stop_heartbeat.set()
            heartbeat_thread.join(timeout=5)

def run() -> int:
    base, token, worker_id, instance_id = _config()
    poll_seconds = max(2, min(30, int(os.environ.get("MUSICMASTER_WORKER_POLL_SECONDS", "5"))))
    _api(
        base, token, "POST", "/api/internal/workers/register",
        {"worker_id": worker_id, "instance_uuid": instance_id},
    )
    print(f"[cloud-worker] registered: {worker_id}", flush=True)

    while True:
        try:
            claimed = _api(
                base, token, "POST", "/api/internal/jobs/claim",
                {"worker_id": worker_id, "lease_seconds": 300},
            )
            job = claimed.get("job")
            if job is None:
                _api(
                    base, token, "POST", "/api/internal/workers/heartbeat",
                    {"worker_id": worker_id, "status": "idle"},
                )
                time.sleep(poll_seconds)
                continue

            job_id = str(job["id"])
            print(f"[cloud-worker] claimed job {job_id}", flush=True)
            try:
                _process_job(base, token, worker_id, job)
                print(f"[cloud-worker] completed job {job_id}", flush=True)
            except Exception as exc:  # noqa: BLE001
                detail = f"{type(exc).__name__}: {exc}"
                print(f"[cloud-worker] job {job_id} failed: {detail}", flush=True)
                print(traceback.format_exc()[-3000:], file=sys.stderr, flush=True)
                try:
                    _api(
                        base, token, "POST", f"/api/internal/jobs/{job_id}/fail",
                        {
                            "worker_id": worker_id,
                            "error": detail[:1000],
                            "retryable": isinstance(exc, RetryableWorkerError),
                        },
                    )
                except Exception as report_error:  # noqa: BLE001
                    print(f"[cloud-worker] could not report failure: {type(report_error).__name__}", flush=True)
        except KeyboardInterrupt:
            break
        except Exception as exc:  # noqa: BLE001
            print(f"[cloud-worker] loop error: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
            time.sleep(min(30, poll_seconds * 2))

    try:
        _api(
            base, token, "POST", "/api/internal/workers/heartbeat",
            {"worker_id": worker_id, "status": "stopped"},
        )
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
