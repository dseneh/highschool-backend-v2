import hashlib
import os
import subprocess
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.files.storage import default_storage
from django.db import connection, transaction
from django.utils import timezone

from backups.models import TenantBackup


ACTIVE_STATUSES = {
    TenantBackup.Status.QUEUED,
    TenantBackup.Status.PREPARING,
    TenantBackup.Status.BACKING_UP,
    TenantBackup.Status.UPLOADING,
    TenantBackup.Status.VERIFYING,
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
    return f"tenants/{backup.tenant_id}/{now:%Y/%m}/{backup.id}.dump"


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def request_backup(*, tenant, requested_by=None, backup_type=TenantBackup.BackupType.MANUAL):
    """Create a backup request while preventing concurrent jobs for one tenant."""
    with transaction.atomic():
        # Serialize request creation against the tenant row. This is database
        # backed and works across multiple web/worker replicas.
        tenant.__class__.objects.select_for_update().get(pk=tenant.pk)
        if TenantBackup.objects.filter(tenant=tenant, status__in=ACTIVE_STATUSES).exists():
            raise BackupError("A backup is already in progress for this tenant.")
        return TenantBackup.objects.create(
            tenant=tenant,
            schema_name=tenant.schema_name,
            backup_type=backup_type,
            requested_by=requested_by,
        )


def run_backup(backup_id):
    """Run one tenant schema backup synchronously.

    Intended to be called by a worker/management command. It deliberately does
    not accept a schema name; the authoritative schema is resolved from the
    backup's tenant relation immediately before pg_dump.
    """
    backup = TenantBackup.objects.select_related("tenant").get(pk=backup_id)
    if backup.status != TenantBackup.Status.QUEUED:
        raise BackupError(f"Backup {backup.id} is not queued (status={backup.status}).")

    backup.status = TenantBackup.Status.PREPARING
    backup.started_at = timezone.now()
    backup.error_message = ""
    backup.save(update_fields=["status", "started_at", "error_message", "updated_at"])

    schema_name = backup.tenant.schema_name
    if not schema_name or schema_name == "public":
        _fail(backup, "Refusing to create a tenant backup for an invalid/public schema.")
        raise BackupError(backup.error_message)

    db, env = _database_environment()
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(prefix=f"ezyschool-{backup.id}-", suffix=".dump", delete=False) as tmp:
            temp_path = Path(tmp.name)

        backup.status = TenantBackup.Status.BACKING_UP
        backup.save(update_fields=["status", "updated_at"])

        command = [
            "pg_dump",
            "--format=custom",
            "--no-owner",
            "--no-privileges",
            "--schema", schema_name,
            "--file", str(temp_path),
        ]
        if db.get("HOST"):
            command.extend(["--host", str(db["HOST"])])
        if db.get("PORT"):
            command.extend(["--port", str(db["PORT"])])
        if db.get("USER"):
            command.extend(["--username", str(db["USER"])])
        command.append(str(db["NAME"]))

        result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=getattr(settings, "TENANT_BACKUP_TIMEOUT_SECONDS", 1800))
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
            saved_key = default_storage.save(storage_key, File(stream))

        backup.status = TenantBackup.Status.VERIFYING
        backup.storage_key = saved_key
        backup.save(update_fields=["status", "storage_key", "updated_at"])

        remote_size = default_storage.size(saved_key)
        if remote_size != file_size:
            default_storage.delete(saved_key)
            raise BackupError(f"Backup verification failed: uploaded size {remote_size} != local size {file_size}.")

        with connection.cursor() as cursor:
            cursor.execute("SHOW server_version")
            postgres_version = cursor.fetchone()[0]

        backup.status = TenantBackup.Status.AVAILABLE
        backup.storage_provider = "s3" if getattr(settings, "USE_S3_STORAGE", False) else "filesystem"
        backup.file_size = file_size
        backup.sha256 = checksum
        backup.postgres_version = postgres_version
        backup.application_version = getattr(settings, "APP_VERSION", "")
        backup.completed_at = timezone.now()
        backup.save(update_fields=[
            "status", "storage_provider", "storage_key", "file_size", "sha256",
            "postgres_version", "application_version", "completed_at", "updated_at",
        ])
        return backup
    except Exception as exc:
        _fail(backup, str(exc))
        raise
    finally:
        if temp_path:
            temp_path.unlink(missing_ok=True)


def _fail(backup, message):
    backup.status = TenantBackup.Status.FAILED
    backup.error_message = (message or "Unknown backup failure")[:8000]
    backup.completed_at = timezone.now()
    backup.save(update_fields=["status", "error_message", "completed_at", "updated_at"])
