import hashlib
import os
import subprocess
import tempfile
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.files.storage import storages
from django.db import connection, transaction
from django.utils import timezone

from backups.models import TenantBackup, TenantRestoreRequest
from core.models import Tenant


ACTIVE_STATUSES = {
    TenantBackup.Status.QUEUED,
    TenantBackup.Status.PREPARING,
    TenantBackup.Status.BACKING_UP,
    TenantBackup.Status.UPLOADING,
    TenantBackup.Status.VERIFYING,
}
RUNNING_STATUSES = ACTIVE_STATUSES - {TenantBackup.Status.QUEUED}
ACTIVE_RESTORE_STATUSES = {
    TenantRestoreRequest.Status.REQUESTED,
    TenantRestoreRequest.Status.SAFETY_BACKUP_PENDING,
    TenantRestoreRequest.Status.READY_FOR_APPROVAL,
    TenantRestoreRequest.Status.APPROVED,
    TenantRestoreRequest.Status.RESTORING,
}


class BackupError(RuntimeError):
    pass


def _database_environment():
    db = settings.DATABASES["default"]
    env = os.environ.copy()
    if db.get("PASSWORD"):
        env["PGPASSWORD"] = str(db["PASSWORD"])
    return db, env


def _storage_key(backup):
    now = timezone.now()
    schema_name = (backup.schema_name or "").strip().lower()
    if not schema_name or schema_name == "public":
        raise BackupError("Refusing to create a backup object key for an invalid/public schema.")
    return f"tenants/{schema_name}/{now:%Y/%m}/{backup.id}.dump"


def _hash_stream(stream):
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def _sha256(path):
    with open(path, "rb") as stream:
        return _hash_stream(stream)


def _storage_sha256(storage, key):
    with storage.open(key, "rb") as stream:
        return _hash_stream(stream)


def _retention_days(backup_type):
    mapping = {
        TenantBackup.BackupType.MANUAL: settings.TENANT_BACKUP_RETENTION_MANUAL_DAYS,
        TenantBackup.BackupType.SCHEDULED: settings.TENANT_BACKUP_RETENTION_SCHEDULED_DAYS,
        TenantBackup.BackupType.PRE_RESTORE: settings.TENANT_BACKUP_RETENTION_PRE_RESTORE_DAYS,
        TenantBackup.BackupType.SYSTEM: settings.TENANT_BACKUP_RETENTION_SYSTEM_DAYS,
    }
    return max(0, int(mapping[backup_type]))


def request_backup(*, tenant, requested_by=None, backup_type=TenantBackup.BackupType.MANUAL, reason=""):
    with transaction.atomic():
        tenant = tenant.__class__.objects.select_for_update().get(pk=tenant.pk)
        if not tenant.schema_name or tenant.schema_name == "public":
            raise BackupError("Refusing to queue a tenant backup for an invalid/public schema.")
        if TenantBackup.objects.filter(tenant=tenant, status__in=ACTIVE_STATUSES).exists():
            raise BackupError("A backup is already in progress for this tenant.")
        retention_days = _retention_days(backup_type)
        expires_at = timezone.now() + timedelta(days=retention_days) if retention_days else None
        return TenantBackup.objects.create(
            tenant=tenant,
            schema_name=tenant.schema_name,
            backup_type=backup_type,
            requested_by=requested_by,
            reason=(reason or "").strip(),
            expires_at=expires_at,
        )


def delete_backup(backup):
    with transaction.atomic():
        backup = TenantBackup.objects.select_for_update().get(pk=backup.pk)
        if backup.status != TenantBackup.Status.AVAILABLE:
            raise BackupError("Only available backups can be deleted.")
        if TenantRestoreRequest.objects.filter(
            backup=backup,
            status__in=ACTIVE_RESTORE_STATUSES,
        ).exists() or TenantRestoreRequest.objects.filter(
            safety_backup=backup,
            status__in=ACTIVE_RESTORE_STATUSES,
        ).exists():
            raise BackupError("This backup is currently required by an active restore request and cannot be deleted.")

        backup.status = TenantBackup.Status.DELETING
        backup.save(update_fields=["status", "updated_at"])

    storage = storages["backups"]
    try:
        if backup.storage_key and storage.exists(backup.storage_key):
            storage.delete(backup.storage_key)
    except Exception as exc:
        backup.status = TenantBackup.Status.AVAILABLE
        backup.error_message = f"Manual backup deletion failed: {exc}"[:8000]
        backup.save(update_fields=["status", "error_message", "updated_at"])
        raise BackupError("The backup artifact could not be deleted. Please try again.") from exc

    backup.status = TenantBackup.Status.DELETED
    backup.deleted_at = timezone.now()
    backup.storage_key = ""
    backup.error_message = ""
    backup.save(update_fields=["status", "deleted_at", "storage_key", "error_message", "updated_at"])
    return backup


def run_backup(backup_id):
    """Run one queued schema backup and atomically claim it for this worker."""
    started_at = timezone.now()
    claimed = TenantBackup.objects.filter(
        pk=backup_id,
        status=TenantBackup.Status.QUEUED,
    ).update(
        status=TenantBackup.Status.PREPARING,
        started_at=started_at,
        error_message="",
        updated_at=started_at,
    )
    if claimed != 1:
        try:
            current_status = TenantBackup.objects.only("status").get(pk=backup_id).status
        except TenantBackup.DoesNotExist as exc:
            raise BackupError(f"Backup {backup_id} does not exist.") from exc
        raise BackupError(f"Backup {backup_id} is not queued (status={current_status}).")

    backup = TenantBackup.objects.select_related("tenant").get(pk=backup_id)
    schema_name = backup.tenant.schema_name
    if not schema_name or schema_name == "public":
        _fail(backup, "Refusing to create a tenant backup for an invalid/public schema.")
        raise BackupError(backup.error_message)

    db, env = _database_environment()
    backup_storage = storages["backups"]
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(prefix=f"ezyschool-{backup.id}-", suffix=".dump", delete=False) as tmp:
            temp_path = Path(tmp.name)

        backup.status = TenantBackup.Status.BACKING_UP
        backup.save(update_fields=["status", "updated_at"])

        command = ["pg_dump", "--format=custom", "--no-owner", "--no-privileges", "--schema", schema_name, "--file", str(temp_path)]
        if db.get("HOST"):
            command.extend(["--host", str(db["HOST"])])
        if db.get("PORT"):
            command.extend(["--port", str(db["PORT"])])
        if db.get("USER"):
            command.extend(["--username", str(db["USER"])])
        command.append(str(db["NAME"]))

        result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=settings.TENANT_BACKUP_TIMEOUT_SECONDS)
        if result.returncode != 0:
            raise BackupError((result.stderr or "pg_dump failed").strip()[-4000:])
        if not temp_path.exists() or temp_path.stat().st_size == 0:
            raise BackupError("pg_dump completed without producing a backup file.")

        file_size = temp_path.stat().st_size
        checksum = _sha256(temp_path)
        storage_key = _storage_key(backup)

        backup.status = TenantBackup.Status.UPLOADING
        backup.save(update_fields=["status", "updated_at"])
        with open(temp_path, "rb") as stream:
            saved_key = backup_storage.save(storage_key, File(stream))

        backup.status = TenantBackup.Status.VERIFYING
        backup.storage_key = saved_key
        backup.save(update_fields=["status", "storage_key", "updated_at"])

        remote_size = backup_storage.size(saved_key)
        if remote_size != file_size:
            backup_storage.delete(saved_key)
            raise BackupError(f"Backup verification failed: uploaded size {remote_size} != local size {file_size}.")
        remote_checksum = _storage_sha256(backup_storage, saved_key)
        if remote_checksum != checksum:
            backup_storage.delete(saved_key)
            raise BackupError("Backup verification failed: uploaded SHA-256 does not match the local dump.")

        with connection.cursor() as cursor:
            cursor.execute("SHOW server_version")
            postgres_version = cursor.fetchone()[0]

        backup.status = TenantBackup.Status.AVAILABLE
        backup.storage_provider = "s3" if settings.USE_S3_STORAGE else "filesystem"
        backup.file_size = file_size
        backup.sha256 = checksum
        backup.postgres_version = postgres_version
        backup.application_version = getattr(settings, "APP_VERSION", "")
        backup.completed_at = timezone.now()
        backup.save(update_fields=["status", "storage_provider", "storage_key", "file_size", "sha256", "postgres_version", "application_version", "completed_at", "updated_at"])
        return backup
    except Exception as exc:
        _fail(backup, str(exc))
        raise
    finally:
        if temp_path:
            temp_path.unlink(missing_ok=True)


def queue_due_scheduled_backups(*, now=None):
    if not settings.TENANT_BACKUP_SCHEDULE_ENABLED:
        return []
    now = now or timezone.now()
    cutoff = now - timedelta(hours=max(1, settings.TENANT_BACKUP_SCHEDULE_INTERVAL_HOURS))
    queued = []
    for tenant in Tenant.objects.exclude(schema_name="public").filter(active=True).iterator():
        if TenantBackup.objects.filter(tenant=tenant, status__in=ACTIVE_STATUSES).exists():
            continue
        recent = TenantBackup.objects.filter(
            tenant=tenant,
            backup_type=TenantBackup.BackupType.SCHEDULED,
            status=TenantBackup.Status.AVAILABLE,
            completed_at__gt=cutoff,
        ).exists()
        if recent:
            continue
        try:
            queued.append(request_backup(tenant=tenant, backup_type=TenantBackup.BackupType.SCHEDULED))
        except BackupError:
            continue
    return queued


def recover_stale_backups(*, now=None):
    now = now or timezone.now()
    cutoff = now - timedelta(minutes=max(1, settings.TENANT_BACKUP_STALE_MINUTES))
    stale = list(TenantBackup.objects.filter(status__in=RUNNING_STATUSES, updated_at__lt=cutoff))
    for backup in stale:
        _fail(backup, "Backup job exceeded the stale-job threshold and was marked failed for operator review.")
    return stale


def purge_expired_backups(*, now=None):
    now = now or timezone.now()
    storage = storages["backups"]
    expired = list(TenantBackup.objects.filter(
        status__in=[TenantBackup.Status.AVAILABLE, TenantBackup.Status.DELETING],
        expires_at__isnull=False,
        expires_at__lte=now,
    ))
    deleted = []
    for backup in expired:
        backup.status = TenantBackup.Status.DELETING
        backup.save(update_fields=["status", "updated_at"])
        try:
            if backup.storage_key and storage.exists(backup.storage_key):
                storage.delete(backup.storage_key)
        except Exception as exc:
            backup.status = TenantBackup.Status.AVAILABLE
            backup.error_message = f"Retention cleanup failed and will be retried: {exc}"[:8000]
            backup.save(update_fields=["status", "error_message", "updated_at"])
            continue
        backup.status = TenantBackup.Status.DELETED
        backup.deleted_at = timezone.now()
        backup.storage_key = ""
        backup.error_message = ""
        backup.save(update_fields=["status", "deleted_at", "storage_key", "error_message", "updated_at"])
        deleted.append(backup)
    return deleted


def _fail(backup, message):
    backup.status = TenantBackup.Status.FAILED
    backup.error_message = (message or "Unknown backup failure")[:8000]
    backup.completed_at = timezone.now()
    backup.save(update_fields=["status", "error_message", "completed_at", "updated_at"])
