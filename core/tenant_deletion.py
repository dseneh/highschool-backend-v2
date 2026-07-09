"""Background tenant deletion (soft and permanent)."""

from __future__ import annotations

import logging
import threading
from typing import Callable

from django.db import connection, transaction
from django_tenants.utils import get_public_schema_name, schema_context, schema_exists

from core.models import Tenant

logger = logging.getLogger(__name__)

DELETION_STEP_LABELS = {
    "revoke_access": "Revoking workspace access",
    "mark_deleted": "Finalizing soft delete",
    "drop_schema": "Dropping database schema",
    "remove_record": "Removing tenant record",
}

SOFT_DELETE_STEPS: list[tuple[str, int]] = [
    ("revoke_access", 40),
    ("mark_deleted", 100),
]

HARD_DELETE_STEPS: list[tuple[str, int]] = [
    ("revoke_access", 20),
    ("drop_schema", 75),
    ("remove_record", 100),
]

_running_jobs: set[str] = set()
_jobs_lock = threading.Lock()


def parse_hard_delete_flag(value) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def get_deletion_step_label(step_key: str) -> str:
    return DELETION_STEP_LABELS.get(step_key, step_key.replace("_", " ").title())


def is_deletion_in_progress(tenant: Tenant) -> bool:
    return tenant.deletion_status in ("queued", "running")


def queue_tenant_deletion(tenant: Tenant, *, hard_delete: bool) -> Tenant:
    """Mark tenant for background deletion and enqueue the worker."""
    if tenant.schema_name == get_public_schema_name():
        raise ValueError("Cannot delete public tenant.")
    if is_deletion_in_progress(tenant):
        raise ValueError("Deletion is already in progress for this tenant.")
    if tenant.provisioning_status in ("queued", "running"):
        raise ValueError("Cannot delete a tenant while workspace creation is in progress.")

    tenant.deletion_status = "queued"
    tenant.deletion_mode = "hard" if hard_delete else "soft"
    tenant.deletion_step = ""
    tenant.deletion_progress = 0
    tenant.deletion_error = ""
    tenant.deletion_completed_steps = []
    tenant.active = False
    tenant.save(
        update_fields=[
            "deletion_status",
            "deletion_mode",
            "deletion_step",
            "deletion_progress",
            "deletion_error",
            "deletion_completed_steps",
            "active",
            "updated_at",
        ]
    )

    enqueue_tenant_deletion(tenant.schema_name)
    return tenant


def enqueue_tenant_deletion(schema_name: str) -> None:
    with _jobs_lock:
        if schema_name in _running_jobs:
            return
        _running_jobs.add(schema_name)

    def _run() -> None:
        connection.close()
        try:
            run_tenant_deletion(schema_name)
        finally:
            with _jobs_lock:
                _running_jobs.discard(schema_name)

    thread = threading.Thread(
        target=_run,
        name=f"tenant-delete-{schema_name}",
        daemon=True,
    )
    thread.start()


def retry_tenant_deletion(schema_name: str) -> Tenant:
    with transaction.atomic():
        tenant = Tenant.objects.select_for_update().get(schema_name=schema_name)
        if tenant.deletion_status == "completed":
            raise ValueError("Deletion is already completed.")
        if tenant.deletion_status in ("queued", "running"):
            raise ValueError("Deletion is already in progress.")
        if tenant.deletion_status != "failed":
            raise ValueError("Tenant is not in a failed deletion state.")

        tenant.deletion_status = "queued"
        tenant.deletion_error = ""
        tenant.save(update_fields=["deletion_status", "deletion_error", "updated_at"])

    enqueue_tenant_deletion(schema_name)
    return Tenant.objects.get(schema_name=schema_name)


def run_tenant_deletion(schema_name: str) -> None:
    with transaction.atomic():
        tenant = Tenant.objects.select_for_update().get(schema_name=schema_name)
        if tenant.deletion_status == "completed":
            return
        if tenant.deletion_status == "running":
            return

        tenant.deletion_status = "running"
        tenant.deletion_error = ""
        tenant.save(update_fields=["deletion_status", "deletion_error", "updated_at"])

    tenant = Tenant.objects.get(schema_name=schema_name)
    steps = HARD_DELETE_STEPS if tenant.deletion_mode == "hard" else SOFT_DELETE_STEPS
    completed = list(tenant.deletion_completed_steps or [])

    try:
        for step_key, progress in steps:
            if step_key in completed:
                continue

            _update_deletion_progress(tenant, step_key, progress)

            handler = _STEP_HANDLERS[step_key]
            handler(tenant)

            if step_key == "remove_record":
                return

            tenant.refresh_from_db()
            completed.append(step_key)
            tenant.deletion_completed_steps = completed
            tenant.save(update_fields=["deletion_completed_steps", "updated_at"])

        tenant.refresh_from_db()
        tenant.deletion_status = "completed"
        tenant.deletion_step = ""
        tenant.deletion_progress = 100
        tenant.deletion_error = ""
        tenant.save(
            update_fields=[
                "deletion_status",
                "deletion_step",
                "deletion_progress",
                "deletion_error",
                "updated_at",
            ]
        )
        logger.info("Tenant deletion completed: %s (%s)", schema_name, tenant.deletion_mode)

    except Exception as exc:
        logger.exception("Tenant deletion failed for %s", schema_name)
        try:
            tenant.refresh_from_db()
            tenant.deletion_status = "failed"
            tenant.deletion_error = str(exc)
            tenant.save(
                update_fields=["deletion_status", "deletion_error", "updated_at"]
            )
        except Tenant.DoesNotExist:
            pass


def _update_deletion_progress(tenant: Tenant, step_key: str, progress: int) -> None:
    tenant.deletion_step = step_key
    tenant.deletion_progress = progress
    tenant.save(update_fields=["deletion_step", "deletion_progress", "updated_at"])


def _step_revoke_access(tenant: Tenant) -> None:
    tenant.active = False
    tenant.save(update_fields=["active", "updated_at"])


def _step_mark_deleted(tenant: Tenant) -> None:
    tenant.status = "deleted"
    tenant.active = False
    tenant.deletion_status = "completed"
    tenant.deletion_step = ""
    tenant.deletion_progress = 100
    tenant.deletion_error = ""
    tenant.save(
        update_fields=[
            "status",
            "active",
            "deletion_status",
            "deletion_step",
            "deletion_progress",
            "deletion_error",
            "updated_at",
        ]
    )


def _step_drop_schema(tenant: Tenant) -> None:
    with schema_context(get_public_schema_name()):
        if schema_exists(tenant.schema_name):
            tenant._drop_schema(force_drop=True)


def _step_remove_record(tenant: Tenant) -> None:
    schema_name = tenant.schema_name
    with schema_context(get_public_schema_name()):
        tenant.refresh_from_db()
        tenant.delete(force_drop=True)
    logger.info("Hard-deleted tenant %s", schema_name)


_STEP_HANDLERS: dict[str, Callable[[Tenant], None]] = {
    "revoke_access": _step_revoke_access,
    "mark_deleted": _step_mark_deleted,
    "drop_schema": _step_drop_schema,
    "remove_record": _step_remove_record,
}
