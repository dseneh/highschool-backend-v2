import hashlib
import os
import re
import subprocess
import tempfile
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.files.storage import storages
from django.db import connection, transaction
from django.utils import timezone

from backups.models import TenantBackup, TenantRestoreRequest
from backups.services import BackupError, request_backup


class RestoreError(RuntimeError):
    pass


ACTIVE_RESTORE_STATUSES = {
    TenantRestoreRequest.Status.REQUESTED,
    TenantRestoreRequest.Status.SAFETY_BACKUP_PENDING,
    TenantRestoreRequest.Status.READY_FOR_APPROVAL,
    TenantRestoreRequest.Status.APPROVED,
    TenantRestoreRequest.Status.EXECUTION_PENDING,
    TenantRestoreRequest.Status.RESTORING,
}

_SAFE_SCHEMA_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _tenant_lock_key(schema_name):
    digest = hashlib.blake2b(str(schema_name).encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, byteorder="big", signed=True)


def _acquire_restore_lock(schema_name):
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_lock(%s)", [_tenant_lock_key(schema_name)])


def _release_restore_lock(schema_name):
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_unlock(%s)", [_tenant_lock_key(schema_name)])

# Forbidden catalog types that must not appear in tenant-scoped restores.
# Format in pg_restore --list: "; <oid>; <catalog-type> <rest>"
# Some types are single-word (DATABASE, EXTENSION) and some are multi-word (EVENT TRIGGER).
_FORBIDDEN_TOC_TYPES = {
    "DATABASE",
    "EXTENSION",
    "EVENT TRIGGER",
    "PUBLICATION",
    "SUBSCRIPTION",
}


def request_restore(*, tenant, backup, requested_by=None, reason=""):
    with transaction.atomic():
        tenant = tenant.__class__.objects.select_for_update().get(pk=tenant.pk)
        backup = TenantBackup.objects.select_for_update().get(pk=backup.pk)
        _validate_tenant_and_backup(tenant=tenant, backup=backup)
        if TenantRestoreRequest.objects.filter(tenant=tenant, status__in=ACTIVE_RESTORE_STATUSES).exists():
            raise RestoreError("A restore request is already active for this tenant.")

        restore_request = TenantRestoreRequest.objects.create(
            tenant=tenant,
            backup=backup,
            schema_name=tenant.schema_name,
            requested_by=requested_by,
            reason=(reason or "").strip(),
            status=TenantRestoreRequest.Status.SAFETY_BACKUP_PENDING,
        )
        try:
            safety_backup = request_backup(
                tenant=tenant,
                requested_by=requested_by,
                backup_type=TenantBackup.BackupType.PRE_RESTORE,
            )
        except BackupError as exc:
            raise RestoreError(f"Could not queue the pre-restore safety backup: {exc}") from exc
        restore_request.safety_backup = safety_backup
        restore_request.save(update_fields=["safety_backup", "updated_at"])
        return restore_request


def refresh_restore_readiness(restore_request):
    restore_request = TenantRestoreRequest.objects.select_related("safety_backup").get(pk=restore_request.pk)
    if restore_request.status != TenantRestoreRequest.Status.SAFETY_BACKUP_PENDING:
        return restore_request
    safety_backup = restore_request.safety_backup
    if safety_backup and safety_backup.status == TenantBackup.Status.AVAILABLE:
        restore_request.status = TenantRestoreRequest.Status.READY_FOR_APPROVAL
        restore_request.error_message = ""
        restore_request.save(update_fields=["status", "error_message", "updated_at"])
    elif safety_backup and safety_backup.status == TenantBackup.Status.FAILED:
        restore_request.status = TenantRestoreRequest.Status.FAILED
        restore_request.error_message = "The required pre-restore safety backup failed."
        restore_request.save(update_fields=["status", "error_message", "updated_at"])
    return restore_request


def approve_restore(*, restore_request, approved_by, decision_note=""):
    """Approve a restore request.
    
    Moves status from READY_FOR_APPROVAL to APPROVED.
    Does NOT transition to EXECUTION_PENDING or RESTORING.
    The tenant must explicitly call execute_restore() to queue execution.
    """
    with transaction.atomic():
        restore_request = TenantRestoreRequest.objects.select_for_update(of=("self",)).select_related(
            "tenant", "backup", "safety_backup"
        ).get(pk=restore_request.pk)
        restore_request = refresh_restore_readiness(restore_request)
        if restore_request.status != TenantRestoreRequest.Status.READY_FOR_APPROVAL:
            raise RestoreError("Restore request is not ready for approval.")
        _validate_execution_prerequisites(restore_request)
        restore_request.status = TenantRestoreRequest.Status.APPROVED
        restore_request.approved_by = approved_by
        restore_request.approved_at = timezone.now()
        restore_request.decision_note = (decision_note or "").strip()
        restore_request.error_message = ""
        restore_request.save(
            update_fields=[
                "status", "approved_by", "approved_at", "decision_note", "error_message", "updated_at"
            ]
        )
        return restore_request


def execute_restore(*, restore_request, executed_by=None):
    """Execute an approved restore request.
    
    Transitions from APPROVED to EXECUTION_PENDING.
    The worker process will pick it up and move it to RESTORING, then handle execution.
    Validates that backup and safety backup are still available.
    """
    with transaction.atomic():
        restore_request = TenantRestoreRequest.objects.select_for_update(of=("self",)).select_related(
            "tenant", "backup", "safety_backup"
        ).get(pk=restore_request.pk)
        
        if restore_request.status != TenantRestoreRequest.Status.APPROVED:
            raise RestoreError(
                f"Restore request is not approved (current status: {restore_request.status})."
            )
        
        _validate_execution_prerequisites(restore_request)
        restore_request.status = TenantRestoreRequest.Status.EXECUTION_PENDING
        restore_request.error_message = ""
        restore_request.save(update_fields=["status", "error_message", "updated_at"])
        _lock_tenant_runtime(restore_request)
        return restore_request


def retry_restore(*, restore_request, retried_by=None):
    """Retry a failed restore that was previously approved.
    
    Only applies to FAILED requests where approved_at is set.
    Transitions directly to EXECUTION_PENDING without requiring second approval.
    Validates that backup and safety backup are still available.
    """
    with transaction.atomic():
        restore_request = TenantRestoreRequest.objects.select_for_update(of=("self",)).select_related(
            "tenant", "backup", "safety_backup"
        ).get(pk=restore_request.pk)
        
        if restore_request.status != TenantRestoreRequest.Status.FAILED:
            raise RestoreError(
                f"Only a failed restore request can be retried (current status: {restore_request.status})."
            )
        
        if not restore_request.approved_at:
            raise RestoreError("Cannot retry a restore request that was not previously approved.")
        
        _validate_execution_prerequisites(restore_request)
        restore_request.status = TenantRestoreRequest.Status.EXECUTION_PENDING
        restore_request.error_message = ""
        restore_request.save(update_fields=["status", "error_message", "updated_at"])
        _lock_tenant_runtime(restore_request)
        return restore_request


def delete_restore(*, restore_request):
    """Delete a restore request (platform superadmin only).
    
    Only allows hard delete for terminal statuses: FAILED, REJECTED, CANCELLED.
    Refuses to delete if in active/approved/restoring/execution_pending.
    """
    terminal_statuses = {
        TenantRestoreRequest.Status.FAILED,
        TenantRestoreRequest.Status.REJECTED,
        TenantRestoreRequest.Status.CANCELLED,
    }
    
    if restore_request.status not in terminal_statuses:
        raise RestoreError(
            f"Cannot delete restore request in status '{restore_request.status}'. "
            f"Only terminal statuses ({', '.join(terminal_statuses)}) may be deleted."
        )
    
    restore_request_id = restore_request.id
    restore_request.delete()
    return restore_request_id


def reject_restore(*, restore_request, rejected_by, decision_note=""):
    with transaction.atomic():
        restore_request = TenantRestoreRequest.objects.select_for_update().get(pk=restore_request.pk)
        if restore_request.status not in {
            TenantRestoreRequest.Status.READY_FOR_APPROVAL,
            TenantRestoreRequest.Status.APPROVED,
        }:
            raise RestoreError("Only an approval-ready or approved restore request can be rejected.")
        restore_request.status = TenantRestoreRequest.Status.REJECTED
        restore_request.rejected_by = rejected_by
        restore_request.rejected_at = timezone.now()
        restore_request.decision_note = (decision_note or "").strip()
        restore_request.save(
            update_fields=["status", "rejected_by", "rejected_at", "decision_note", "updated_at"]
        )
        return restore_request


def run_restore(restore_request_id):
    """Execute the actual restore.
    
    Transitions from EXECUTION_PENDING to RESTORING, performs the restore,
    then moves to COMPLETED or FAILED.
    """
    claimed_at = timezone.now()
    claimed = TenantRestoreRequest.objects.filter(
        pk=restore_request_id,
        status=TenantRestoreRequest.Status.EXECUTION_PENDING,
    ).update(
        status=TenantRestoreRequest.Status.RESTORING,
        started_at=claimed_at,
        error_message="",
        updated_at=claimed_at,
    )
    if claimed != 1:
        try:
            current = TenantRestoreRequest.objects.only("status").get(pk=restore_request_id)
        except TenantRestoreRequest.DoesNotExist as exc:
            raise RestoreError(f"Restore request {restore_request_id} does not exist.") from exc
        raise RestoreError(f"Restore request {restore_request_id} is not execution pending (status={current.status}).")

    restore_request = TenantRestoreRequest.objects.select_related("tenant", "backup", "safety_backup").get(
        pk=restore_request_id
    )
    temp_path = None
    rollback_schema = None
    tenant_locked = False
    restore_lock_acquired = False
    runtime_safe_to_unlock = True

    try:
        _validate_execution_prerequisites(restore_request)
        tenant = restore_request.tenant
        schema_name = tenant.schema_name
        restore_already_locked = (
            tenant.restoration_in_progress
            and str(tenant.restoration_request_id) == str(restore_request.id)
            and bool(restore_request.tenant_runtime_snapshot)
        )
        if (tenant.maintenance_mode or not tenant.active) and not restore_already_locked:
            raise RestoreError("Tenant is already disabled or in maintenance mode; restore execution was not started.")

        storage = storages["backups"]
        temp_path = _download_and_verify_backup(storage=storage, backup=restore_request.backup)
        _validate_archive(temp_path=temp_path, schema_name=schema_name)

        if not restore_already_locked:
            _lock_tenant_runtime(restore_request)
        tenant_locked = True
        _acquire_restore_lock(schema_name)
        restore_lock_acquired = True

        rollback_schema = _rollback_schema_name(schema_name, restore_request.id)
        _rename_schema(schema_name, rollback_schema)
        try:
            _pg_restore(temp_path)
            _validate_restored_schema(schema_name)
        except Exception:
            _drop_schema_if_exists(schema_name)
            _rename_schema(rollback_schema, schema_name)
            rollback_schema = None
            raise

        _drop_schema_if_exists(rollback_schema)
        rollback_schema = None
        _restore_tenant_runtime(restore_request)
        tenant_locked = False

        restore_request.status = TenantRestoreRequest.Status.COMPLETED
        restore_request.completed_at = timezone.now()
        restore_request.error_message = ""
        restore_request.save(update_fields=["status", "completed_at", "error_message", "updated_at"])
        return restore_request
    except Exception as exc:
        if rollback_schema:
            try:
                schema_name = restore_request.tenant.schema_name
                _drop_schema_if_exists(schema_name)
                _rename_schema(rollback_schema, schema_name)
            except Exception as rollback_exc:
                runtime_safe_to_unlock = False
                exc = RestoreError(f"{exc}; automatic schema rollback also failed: {rollback_exc}")
        if tenant_locked and runtime_safe_to_unlock:
            try:
                _restore_tenant_runtime(restore_request)
            except Exception:
                pass
        _fail_restore(restore_request, str(exc))
        raise
    finally:
        if restore_lock_acquired:
            try:
                _release_restore_lock(restore_request.tenant.schema_name)
            except Exception:
                pass
        if temp_path:
            Path(temp_path).unlink(missing_ok=True)


def recover_stale_restores(*, now=None):
    """Recover restore workers that stopped updating while RESTORING.

    A rollback schema wins over any partially restored live schema. If no
    rollback schema exists, a structurally valid live schema is retained and
    the prior tenant runtime state is restored for operator review.
    """
    now = now or timezone.now()
    cutoff = now - timedelta(minutes=max(1, getattr(settings, "TENANT_RESTORE_STALE_MINUTES", 60)))
    stale = list(
        TenantRestoreRequest.objects.filter(
            status__in=(
                TenantRestoreRequest.Status.EXECUTION_PENDING,
                TenantRestoreRequest.Status.RESTORING,
            ),
            updated_at__lt=cutoff,
        ).select_related("tenant")
    )
    recovered = []
    for restore_request in stale:
        schema_name = restore_request.tenant.schema_name
        rollback_schema = _rollback_schema_name(schema_name, restore_request.id)
        try:
            rollback_exists = _schema_exists(rollback_schema)
            live_exists = _schema_exists(schema_name)
            if rollback_exists:
                if live_exists:
                    _drop_schema_if_exists(schema_name)
                _rename_schema(rollback_schema, schema_name)
                _validate_restored_schema(schema_name)
                _restore_tenant_runtime(restore_request)
                _fail_restore(restore_request, "Stale restore recovered by reinstating the rollback schema.")
                recovered.append(restore_request)
            elif live_exists:
                _validate_restored_schema(schema_name)
                _restore_tenant_runtime(restore_request)
                _fail_restore(
                    restore_request,
                    "Stale restore stopped without a rollback schema; live schema is structurally valid and requires operator review.",
                )
                recovered.append(restore_request)
            else:
                _fail_restore(
                    restore_request,
                    "Stale restore requires manual intervention: neither live nor rollback schema exists. Tenant remains locked.",
                )
        except Exception as exc:
            _fail_restore(restore_request, f"Stale restore recovery failed: {exc}")
    return recovered


def _lock_tenant_runtime(restore_request):
    tenant = restore_request.tenant
    snapshot = {
        "active": bool(tenant.active),
        "maintenance_mode": bool(tenant.maintenance_mode),
        "disabled_access_allow_tenant_admins": bool(tenant.disabled_access_allow_tenant_admins),
        "disabled_access_allowed_users": list(tenant.disabled_access_allowed_users or []),
    }
    restore_request.tenant_runtime_snapshot = snapshot
    restore_request.save(update_fields=["tenant_runtime_snapshot", "updated_at"])

    tenant.active = False
    tenant.maintenance_mode = True
    tenant.restoration_in_progress = True
    tenant.restoration_started_at = timezone.now()
    tenant.restoration_request_id = restore_request.id
    tenant.disabled_access_allow_tenant_admins = False
    tenant.disabled_access_allowed_users = []
    tenant.save(
        update_fields=[
            "active",
            "maintenance_mode",
            "restoration_in_progress",
            "restoration_started_at",
            "restoration_request_id",
            "disabled_access_allow_tenant_admins",
            "disabled_access_allowed_users",
        ]
    )


def _restore_tenant_runtime(restore_request):
    tenant = restore_request.tenant
    snapshot = restore_request.tenant_runtime_snapshot or {}
    if not snapshot:
        raise RestoreError("Tenant runtime snapshot is missing; refusing to guess the prior runtime state.")
    tenant.active = bool(snapshot.get("active", True))
    tenant.maintenance_mode = bool(snapshot.get("maintenance_mode", False))
    tenant.disabled_access_allow_tenant_admins = bool(snapshot.get("disabled_access_allow_tenant_admins", True))
    tenant.disabled_access_allowed_users = list(snapshot.get("disabled_access_allowed_users", []))
    tenant.restoration_in_progress = False
    tenant.restoration_started_at = None
    tenant.restoration_request_id = None
    tenant.save(
        update_fields=[
            "active",
            "maintenance_mode",
            "disabled_access_allow_tenant_admins",
            "disabled_access_allowed_users",
            "restoration_in_progress",
            "restoration_started_at",
            "restoration_request_id",
        ]
    )


def _validate_tenant_and_backup(*, tenant, backup):
    schema_name = (tenant.schema_name or "").strip()
    if not _is_safe_schema(schema_name):
        raise RestoreError("Refusing to restore an invalid/public tenant schema.")
    if backup.tenant_id != tenant.id:
        raise RestoreError("The selected backup does not belong to this tenant.")
    if backup.status != TenantBackup.Status.AVAILABLE:
        raise RestoreError("Only an available backup can be restored.")
    if backup.schema_name != schema_name:
        raise RestoreError("The backup schema no longer matches the tenant's current schema name.")
    if not backup.storage_key or not backup.sha256 or not backup.file_size:
        raise RestoreError("The selected backup is missing verified restore metadata.")


def _validate_execution_prerequisites(restore_request):
    _validate_tenant_and_backup(tenant=restore_request.tenant, backup=restore_request.backup)
    safety_backup = restore_request.safety_backup
    if not safety_backup or safety_backup.tenant_id != restore_request.tenant_id:
        raise RestoreError("A same-tenant pre-restore safety backup is required.")
    if safety_backup.status != TenantBackup.Status.AVAILABLE:
        raise RestoreError("The pre-restore safety backup is not available.")
    if not safety_backup.storage_key or not safety_backup.sha256 or not safety_backup.file_size:
        raise RestoreError("The pre-restore safety backup is missing verified metadata.")


def _download_and_verify_backup(*, storage, backup):
    fd, name = tempfile.mkstemp(prefix=f"ezyschool-restore-{backup.id}-", suffix=".dump")
    os.close(fd)
    path = Path(name)
    digest = hashlib.sha256()
    size = 0
    try:
        with storage.open(backup.storage_key, "rb") as source, open(path, "wb") as target:
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                target.write(chunk)
                digest.update(chunk)
                size += len(chunk)
        if size != backup.file_size:
            raise RestoreError(f"Restore archive size verification failed ({size} != {backup.file_size}).")
        if digest.hexdigest() != backup.sha256:
            raise RestoreError("Restore archive SHA-256 verification failed.")
        return path
    except Exception:
        path.unlink(missing_ok=True)
        raise


def _validate_archive(*, temp_path, schema_name):
    """Validate pg_restore archive.
    
    Checks:
    1. Archive is readable by pg_restore
    2. Archive contains the expected tenant schema
    3. Archive does not contain forbidden object types (DATABASE, EXTENSION, etc.)
       by parsing actual TOC lines, not substring matching
    """
    result = subprocess.run(
        ["pg_restore", "--list", str(temp_path)],
        capture_output=True,
        text=True,
        timeout=getattr(settings, "TENANT_BACKUP_TIMEOUT_SECONDS", 1800),
    )
    if result.returncode != 0:
        raise RestoreError((result.stderr or "pg_restore could not read the archive").strip()[-4000:])
    toc = result.stdout or ""
    if f"SCHEMA - {schema_name} " not in toc and f"SCHEMA {schema_name} " not in toc:
        raise RestoreError("Restore archive does not contain the expected tenant schema.")
    
    # Parse TOC lines to find forbidden object types (not substring matches on object names).
    forbidden_lines = _find_forbidden_toc_entries(toc)
    if forbidden_lines:
        offending = "; ".join(forbidden_lines[:3])  # Show first 3 offending lines
        if len(forbidden_lines) > 3:
            offending += f"; ... and {len(forbidden_lines) - 3} more"
        raise RestoreError(
            f"Restore archive contains forbidden object type(s). "
            f"Offending TOC entries: {offending}"
        )


def _find_forbidden_toc_entries(toc):
    """Parse pg_restore --list output and find TOC lines with forbidden catalog types.
    
    pg_restore --list format: "; <oid>; <catalog-type> <schema> <name> <owner> ..."
    Examples:
      "; 1234; TABLE SCHEMA public my_table postgres  "
      "; 5678; EVENT TRIGGER log_changes postgres  "
    
    Returns list of sanitized TOC lines (object names redacted) that triggered the filter.
    """
    forbidden_lines = []
    for line in toc.split("\n"):
        if not line.strip():
            continue
        if not line.startswith(";"):
            continue
        # Parse: "; <oid>; <catalog-type> <rest>"
        # Extract the part after ";<digits>;"
        parts = line.split(";", 2)
        if len(parts) < 3:
            continue
        type_and_rest = parts[2].strip()
        
        # Now match the catalog type. Handle both single-word and multi-word types.
        # Try to match "EVENT TRIGGER" first (longest), then others.
        matched_type = None
        if type_and_rest.upper().startswith("EVENT TRIGGER "):
            matched_type = "EVENT TRIGGER"
        else:
            # Try single-word types
            first_word = type_and_rest.split()[0].upper() if type_and_rest else ""
            if first_word in _FORBIDDEN_TOC_TYPES:
                matched_type = first_word
        
        if matched_type:
            # Extract schema (should be first part after type)
            rest_after_type = type_and_rest[len(matched_type):].strip()
            schema_part = rest_after_type.split()[0] if rest_after_type else "(unknown)"
            sanitized = f"[{matched_type} in {schema_part}]"
            forbidden_lines.append(sanitized)
    
    return forbidden_lines


def _pg_restore(temp_path):
    db, env = _database_environment()
    command = ["pg_restore", "--exit-on-error", "--no-owner", "--no-privileges"]
    if db.get("HOST"):
        command.extend(["--host", str(db["HOST"])])
    if db.get("PORT"):
        command.extend(["--port", str(db["PORT"])])
    if db.get("USER"):
        command.extend(["--username", str(db["USER"])])
    command.extend(["--dbname", str(db["NAME"]), str(temp_path)])
    result = subprocess.run(
        command,
        env=env,
        capture_output=True,
        text=True,
        timeout=getattr(settings, "TENANT_BACKUP_TIMEOUT_SECONDS", 1800),
    )
    if result.returncode != 0:
        raise RestoreError((result.stderr or "pg_restore failed").strip()[-4000:])


def _database_environment():
    db = settings.DATABASES["default"]
    env = os.environ.copy()
    if db.get("PASSWORD"):
        env["PGPASSWORD"] = str(db["PASSWORD"])
    return db, env


def _validate_restored_schema(schema_name):
    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = %s", [schema_name])
        table_count = cursor.fetchone()[0]
        cursor.execute(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = %s AND table_name = 'django_migrations')",
            [schema_name],
        )
        has_migrations = cursor.fetchone()[0]
    if table_count <= 0 or not has_migrations:
        raise RestoreError("Restored schema failed structural validation.")


def _rollback_schema_name(schema_name, restore_id):
    suffix = f"__restore_rb_{restore_id.hex[:10]}"
    return f"{schema_name[: 63 - len(suffix)]}{suffix}"


def _schema_exists(schema_name):
    if not _is_safe_schema(schema_name, allow_public=False):
        return False
    with connection.cursor() as cursor:
        cursor.execute("SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = %s)", [schema_name])
        return bool(cursor.fetchone()[0])


def _rename_schema(source, target):
    if not _is_safe_schema(source) or not _is_safe_schema(target, allow_public=False):
        raise RestoreError("Unsafe schema identifier encountered during restore.")
    with connection.cursor() as cursor:
        cursor.execute(
            f"ALTER SCHEMA {connection.ops.quote_name(source)} RENAME TO {connection.ops.quote_name(target)}"
        )


def _drop_schema_if_exists(schema_name):
    if not schema_name:
        return
    if not _is_safe_schema(schema_name, allow_public=False):
        raise RestoreError("Unsafe schema identifier encountered during restore cleanup.")
    with connection.cursor() as cursor:
        cursor.execute(f"DROP SCHEMA IF EXISTS {connection.ops.quote_name(schema_name)} CASCADE")


def _is_safe_schema(schema_name, *, allow_public=False):
    return bool(
        schema_name
        and _SAFE_SCHEMA_RE.fullmatch(schema_name)
        and (allow_public or schema_name.lower() != "public")
    )


def _fail_restore(restore_request, message):
    restore_request.status = TenantRestoreRequest.Status.FAILED
    restore_request.error_message = (message or "Unknown restore failure")[:8000]
    restore_request.completed_at = timezone.now()
    restore_request.save(update_fields=["status", "error_message", "completed_at", "updated_at"])
