"""
Background tenant workspace provisioning with resumable steps.

Tenant creation via the admin API creates a public-schema tenant record
immediately, then runs schema migration, domain setup, user assignment,
and default data initialization in a background thread. Progress is persisted
on the Tenant model so the admin UI can poll and retry from the last step.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable

from django.db import connection, transaction
from django_tenants.utils import schema_context, schema_exists

from core.models import Domain, Tenant

logger = logging.getLogger(__name__)

PROVISIONING_STEP_LABELS = {
    "create_schema": "Creating database schema",
    "create_domain": "Setting up domain",
    "assign_users": "Assigning users",
    "copy_media": "Copying media files",
    "provision_defaults": "Initializing default data",
    "finalize": "Finalizing workspace",
    "send_onboarding_email": "Sending onboarding email",
}

PROVISIONING_STEPS: list[tuple[str, int]] = [
    ("create_schema", 20),
    ("create_domain", 30),
    ("assign_users", 40),
    ("copy_media", 45),
    ("provision_defaults", 85),
    ("finalize", 95),
    ("send_onboarding_email", 100),
]

_running_jobs: set[str] = set()
_jobs_lock = threading.Lock()


def get_provisioning_step_label(step_key: str) -> str:
    return PROVISIONING_STEP_LABELS.get(step_key, step_key.replace("_", " ").title())


def enqueue_tenant_provisioning(schema_name: str) -> None:
    """Start provisioning in a daemon background thread."""
    with _jobs_lock:
        if schema_name in _running_jobs:
            return
        _running_jobs.add(schema_name)

    def _run() -> None:
        connection.close()
        try:
            run_tenant_provisioning(schema_name)
        finally:
            with _jobs_lock:
                _running_jobs.discard(schema_name)

    thread = threading.Thread(
        target=_run,
        name=f"tenant-provision-{schema_name}",
        daemon=True,
    )
    thread.start()


def run_tenant_provisioning(schema_name: str) -> None:
    """Run (or resume) provisioning for a tenant."""
    with transaction.atomic():
        tenant = Tenant.objects.select_for_update().get(schema_name=schema_name)
        if tenant.provisioning_status == "completed":
            return
        if tenant.provisioning_status == "running":
            return

        tenant.provisioning_status = "running"
        tenant.provisioning_error = ""
        tenant.save(
            update_fields=[
                "provisioning_status",
                "provisioning_error",
                "updated_at",
            ]
        )

    tenant = Tenant.objects.get(schema_name=schema_name)
    completed = list(tenant.provisioning_completed_steps or [])
    payload = dict(tenant.provisioning_payload or {})

    try:
        for step_key, progress in PROVISIONING_STEPS:
            if step_key in completed:
                continue

            _update_progress(tenant, step_key, progress)

            handler = _STEP_HANDLERS[step_key]
            handler(tenant, payload)

            completed.append(step_key)
            tenant.provisioning_completed_steps = completed
            tenant.save(
                update_fields=[
                    "provisioning_completed_steps",
                    "updated_at",
                ]
            )

        tenant.refresh_from_db()
        tenant.provisioning_status = "completed"
        tenant.provisioning_step = ""
        tenant.provisioning_progress = 100
        tenant.provisioning_error = ""
        tenant.save(
            update_fields=[
                "provisioning_status",
                "provisioning_step",
                "provisioning_progress",
                "provisioning_error",
                "updated_at",
            ]
        )
        logger.info("Tenant provisioning completed: %s", schema_name)

    except Exception as exc:
        logger.exception("Tenant provisioning failed for %s", schema_name)
        tenant.refresh_from_db()
        tenant.provisioning_status = "failed"
        tenant.provisioning_error = str(exc)
        tenant.save(
            update_fields=[
                "provisioning_status",
                "provisioning_error",
                "updated_at",
            ]
        )


def retry_tenant_provisioning(schema_name: str) -> Tenant:
    """Re-queue provisioning from the last incomplete step."""
    with transaction.atomic():
        tenant = Tenant.objects.select_for_update().get(schema_name=schema_name)
        if tenant.provisioning_status == "completed":
            raise ValueError("Tenant is already fully provisioned.")
        if tenant.provisioning_status in ("queued", "running"):
            raise ValueError("Provisioning is already in progress.")

        tenant.provisioning_status = "queued"
        tenant.provisioning_error = ""
        tenant.save(
            update_fields=[
                "provisioning_status",
                "provisioning_error",
                "updated_at",
            ]
        )

    enqueue_tenant_provisioning(schema_name)
    return Tenant.objects.get(schema_name=schema_name)


def _update_progress(tenant: Tenant, step_key: str, progress: int) -> None:
    tenant.provisioning_step = step_key
    tenant.provisioning_progress = progress
    tenant.save(
        update_fields=[
            "provisioning_step",
            "provisioning_progress",
            "updated_at",
        ]
    )


def _step_create_schema(tenant: Tenant, _payload: dict) -> None:
    if schema_exists(tenant.schema_name):
        logger.info("Schema already exists for %s, skipping create_schema", tenant.schema_name)
        return

    tenant.create_schema(check_if_exists=True, verbosity=0)


def _step_create_domain(tenant: Tenant, payload: dict) -> None:
    if tenant.domains.exists():
        return

    domain_name = payload.get("domain")
    if not domain_name:
        domain_name = f"{tenant.schema_name}.localhost"

    Domain.objects.create(
        domain=domain_name,
        tenant=tenant,
        is_primary=True,
    )


def _step_assign_users(tenant: Tenant, payload: dict) -> None:
    from users.models import User
    from common.status import Roles

    admin_user_id = payload.get("admin_user_id")
    admin_user = None
    if admin_user_id:
        admin_user = User.objects.filter(pk=admin_user_id).first()
    if admin_user is None and hasattr(tenant, "owner") and tenant.owner_id:
        admin_user = tenant.owner

    if admin_user is None:
        raise ValueError("No tenant admin user found for tenant provisioning.")

    with schema_context(tenant.schema_name):
        tenant.add_user(admin_user, is_superuser=True, is_staff=True)

        superadmin_users = User.objects.filter(role=Roles.SUPERADMIN)
        for superadmin in superadmin_users:
            if superadmin.id != admin_user.id:
                tenant.add_user(superadmin, is_superuser=True, is_staff=True)


def _step_copy_media(tenant: Tenant, _payload: dict) -> None:
    from defaults.utils import copy_default_media_files

    copy_default_media_files(tenant)


def _step_provision_defaults(tenant: Tenant, payload: dict) -> None:
    from users.models import User
    from defaults.utils import setup_tenant_defaults

    admin_user_id = payload.get("admin_user_id")
    admin_user = User.objects.filter(pk=admin_user_id).first() if admin_user_id else None
    if admin_user is None and hasattr(tenant, "owner") and tenant.owner_id:
        admin_user = tenant.owner
    if admin_user is None:
        raise ValueError("No tenant admin user found for default data setup.")

    with schema_context(tenant.schema_name):
        from academics.models import AcademicYear

        if AcademicYear.objects.exists():
            logger.info(
                "Default data already exists for %s, skipping provision_defaults",
                tenant.schema_name,
            )
            return

    setup_tenant_defaults(tenant, admin_user)


def _step_finalize(tenant: Tenant, payload: dict) -> None:
    desired_active = payload.get("desired_active", True)
    desired_status = payload.get("desired_status", "active")

    tenant.active = bool(desired_active)
    tenant.status = desired_status
    tenant.save(update_fields=["active", "status", "updated_at"])


def _step_send_onboarding_email(tenant: Tenant, payload: dict) -> None:
    from users.models import User
    from common.email_service import send_tenant_onboarding_email
    from users.utils import build_frontend_url

    admin_user_id = payload.get("admin_user_id")
    admin_password = payload.get("admin_password")
    admin_user_created = payload.get("admin_user_created", True)
    if not admin_user_id:
        logger.warning(
            "Skipping onboarding email for %s: missing admin user in payload",
            tenant.schema_name,
        )
        return

    admin_user = User.objects.filter(pk=admin_user_id).first()
    if admin_user is None:
        raise ValueError("Tenant admin user not found for onboarding email.")

    login_url = build_frontend_url(tenant.schema_name, "/login")
    domain = payload.get("domain")
    workspace_url = login_url if domain else ""

    if not admin_user_created:
        sent = send_tenant_onboarding_email(
            user=admin_user,
            tenant=tenant,
            login_url=login_url,
            workspace_url=workspace_url,
            existing_account=True,
        )
    else:
        if not admin_password:
            logger.warning(
                "Skipping onboarding email for %s: missing admin password in payload",
                tenant.schema_name,
            )
            return
        sent = send_tenant_onboarding_email(
            user=admin_user,
            tenant=tenant,
            temporary_password=str(admin_password),
            login_url=login_url,
            workspace_url=workspace_url,
        )
    if not sent:
        raise ValueError(
            f"Failed to send onboarding email to {admin_user.email}. "
            "You can retry workspace provisioning to attempt again."
        )

    payload.pop("admin_password", None)
    tenant.provisioning_payload = payload
    tenant.save(update_fields=["provisioning_payload", "updated_at"])


_STEP_HANDLERS: dict[str, Callable[[Tenant, dict], None]] = {
    "create_schema": _step_create_schema,
    "create_domain": _step_create_domain,
    "assign_users": _step_assign_users,
    "copy_media": _step_copy_media,
    "provision_defaults": _step_provision_defaults,
    "finalize": _step_finalize,
    "send_onboarding_email": _step_send_onboarding_email,
}
