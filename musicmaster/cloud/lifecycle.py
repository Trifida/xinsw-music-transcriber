# -*- coding: utf-8 -*-
"""Conservative AutoDL worker shutdown/release reconciliation."""
from __future__ import annotations

from typing import Any

from musicmaster.cloud.autodl_pro import AutoDLProError


STOPPED_PROVIDER_STATES = frozenset({"shutdown", "stopped"})
RUNNING_PROVIDER_STATES = frozenset({"running"})
TRANSITION_PROVIDER_STATES = frozenset({"stopping", "powering_off", "shutting_down"})


def reconcile_idle_worker(
    *,
    store: Any,
    autodl_client: Any,
    worker_id: str,
    idle_seconds: int = 300,
) -> dict[str, str]:
    """Power off a stale idle worker, then release only after confirmed shutdown.

    This function is deliberately invoked only by an authenticated manual
    dispatcher endpoint for now. It never releases on an unknown provider state.
    """
    worker = store.get_worker(worker_id)
    if worker is None:
        raise LookupError("Worker not found.")
    instance_uuid = worker.get("instance_uuid")
    if not instance_uuid:
        raise RuntimeError("Worker has no linked AutoDL instance.")

    status = worker.get("status")
    if status == "idle":
        if not store.mark_stale_idle_worker_stopping(
            worker_id, idle_seconds=idle_seconds
        ):
            return {"worker_id": worker_id, "status": "not_stale_or_not_idle"}
        worker = store.get_worker(worker_id)
        status = worker.get("status") if worker else None

    if status != "stopping":
        return {"worker_id": worker_id, "status": str(status or "unknown")}

    try:
        provider_status = str(autodl_client.get_status(instance_uuid)).strip().lower()
    except AutoDLProError as status_error:
        # A release may have succeeded at AutoDL while the API process died
        # before the Postgres row was finalized. A failed status lookup alone
        # is not proof: require a complete, paginated instance-list scan.
        find_instance = getattr(autodl_client, "find_instance", None)
        if not callable(find_instance):
            raise
        try:
            listed_instance = find_instance(instance_uuid)
        except Exception:
            # Keep the original provider status error visible; neither failure
            # permits destructive follow-up or a false stopped transition.
            raise status_error
        if listed_instance is not None:
            return {
                "worker_id": worker_id,
                "status": "stopping",
                "provider_status": "status_unavailable_instance_still_listed",
            }
        if not store.mark_worker_stopped_after_release(worker_id):
            raise RuntimeError("AutoDL no longer lists the instance, but worker state could not be finalized.")
        return {
            "worker_id": worker_id,
            "status": "stopped",
            "provider_status": "absent_from_complete_instance_list",
        }
    if provider_status in RUNNING_PROVIDER_STATES:
        autodl_client.power_off(instance_uuid)
        return {
            "worker_id": worker_id,
            "status": "stopping",
            "provider_status": provider_status,
        }

    if provider_status in STOPPED_PROVIDER_STATES:
        # Provider docs require power-off before release. This branch is entered
        # only after the provider status endpoint confirms shutdown/stopped.
        autodl_client.release_instance(instance_uuid)
        if not store.mark_worker_stopped_after_release(worker_id):
            raise RuntimeError("Provider released the instance but worker state could not be finalized.")
        return {
            "worker_id": worker_id,
            "status": "stopped",
            "provider_status": provider_status,
        }

    # Unknown/transitional states are intentionally non-destructive.
    if provider_status in TRANSITION_PROVIDER_STATES or provider_status:
        return {
            "worker_id": worker_id,
            "status": "stopping",
            "provider_status": provider_status,
        }
    raise RuntimeError("AutoDL returned an empty instance status.")
