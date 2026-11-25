# -*- coding: utf-8 -*-
"""Safe orchestration for creating one AutoDL worker from a queued workload.

This module does not run automatically at import time. Callers must explicitly
invoke create_autodl_worker after applying dispatcher capacity/lease policy.
"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from typing import Any, Callable

from musicmaster.cloud.autodl_pro import build_worker_start_command


def worker_instance_name(worker_id: str) -> str:
    """Build a compact, deterministic provider label that maps back to one worker."""
    value = str(worker_id).strip()
    if not value or len(value) > 128:
        raise ValueError("worker_id must contain 1–128 characters.")
    suffix = hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]
    return f"XW-{suffix}"


def create_autodl_worker(
    *,
    store: Any,
    autodl_client: Any,
    api_url: str,
    image_uuid: str,
    cuda_v_from: int,
    gpu_spec_uuid: str = "4090D",
    req_gpu_amount: int = 1,
    expand_system_disk_by_gb: int = 0,
    instance_name: str = "XinsW Music Transcriber",
    expires_seconds: int = 900,
    worker_id_factory: Callable[[], str] | None = None,
) -> dict[str, str]:
    """Create a worker, persist its one-time credential, then power it on.

    The instance is created without a startup command first. Its provider ID is
    written to both worker and bootstrap-token records before power_on receives
    the command. This avoids the race where a fast boot consumes the token
    before the API can associate the AutoDL instance ID with it.

    On failure, the worker is marked error. If an instance was already created,
    its ID remains persisted for operator-led recovery; this function
    intentionally does not power off or release paid resources automatically.
    """
    worker_id = (worker_id_factory or (lambda: "worker-" + uuid.uuid4().hex))()
    worker_id = str(worker_id).strip()
    if not worker_id or len(worker_id) > 128:
        raise ValueError("worker_id must contain 1–128 characters.")

    bootstrap_token = secrets.token_urlsafe(48)
    token_hash = hashlib.sha256(bootstrap_token.encode("utf-8")).hexdigest()
    instance_uuid: str | None = None

    store.prepare_worker(worker_id)
    try:
        store.issue_bootstrap_token(
            token_hash, worker_id, expires_seconds=expires_seconds
        )
        start_command = build_worker_start_command(api_url, bootstrap_token)

        # Create first without a command; persist the returned ID before boot.
        instance_uuid = autodl_client.create_instance(
            image_uuid=image_uuid,
            cuda_v_from=cuda_v_from,
            gpu_spec_uuid=gpu_spec_uuid,
            req_gpu_amount=req_gpu_amount,
            expand_system_disk_by_gb=expand_system_disk_by_gb,
            instance_name=worker_instance_name(worker_id),
        )
        if not store.set_bootstrap_instance(token_hash, instance_uuid):
            raise RuntimeError("Bootstrap token expired or could not be linked to the instance.")
        if not store.set_worker_instance(worker_id, instance_uuid):
            raise RuntimeError("Worker record could not be linked to the AutoDL instance.")

        # Only now can the instance receive the command containing the one-time token.
        autodl_client.power_on(instance_uuid, start_command=start_command)
        return {
            "worker_id": worker_id,
            "instance_uuid": instance_uuid,
            "status": "starting",
        }
    except Exception:
        try:
            store.set_worker_status(worker_id, "error")
        except Exception:
            pass
        # Never log or return the bootstrap token or generated start command.
        # A created instance is deliberately retained for explicit recovery.
        raise
