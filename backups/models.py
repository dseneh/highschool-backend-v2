import uuid

from django.conf import settings
from django.db import models


class TenantBackup(models.Model):
    class BackupType(models.TextChoices):
        MANUAL = "manual", "Manual"
        SCHEDULED = "scheduled", "Scheduled"
        PRE_RESTORE = "pre_restore", "Pre-restore"
        SYSTEM = "system", "System"

    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        PREPARING = "preparing", "Preparing"
        BACKING_UP = "backing_up", "Backing up"
        UPLOADING = "uploading", "Uploading"
        VERIFYING = "verifying", "Verifying"
        AVAILABLE = "available", "Available"
        FAILED = "failed", "Failed"
        EXPIRED = "expired", "Expired"
        DELETING = "deleting", "Deleting"
        DELETED = "deleted", "Deleted"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey("core.Tenant", on_delete=models.PROTECT, related_name="backups")
    # Snapshot for forensic/audit purposes only. Never use this field as the
    # authoritative restore target; resolve the schema from tenant at runtime.
    schema_name = models.CharField(max_length=63)
    backup_type = models.CharField(max_length=20, choices=BackupType.choices, default=BackupType.MANUAL)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.QUEUED, db_index=True)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="requested_tenant_backups",
    )
    requested_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    storage_provider = models.CharField(max_length=30, blank=True, default="")
    storage_key = models.CharField(max_length=1024, blank=True, default="")
    file_size = models.PositiveBigIntegerField(null=True, blank=True)
    sha256 = models.CharField(max_length=64, blank=True, default="")
    postgres_version = models.CharField(max_length=100, blank=True, default="")
    application_version = models.CharField(max_length=100, blank=True, default="")
    error_message = models.TextField(blank=True, default="")
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "backups_tenant_backup"
        ordering = ("-requested_at",)
        indexes = [
            models.Index(fields=("tenant", "status", "-requested_at"), name="backup_tenant_status_idx"),
        ]

    def __str__(self):
        return f"{self.tenant_id}:{self.id} ({self.status})"
