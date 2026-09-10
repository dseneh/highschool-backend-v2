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


class TenantRestoreRequest(models.Model):
    class Status(models.TextChoices):
        REQUESTED = "requested", "Requested"
        SAFETY_BACKUP_PENDING = "safety_backup_pending", "Safety backup pending"
        READY_FOR_APPROVAL = "ready_for_approval", "Ready for approval"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        RESTORING = "restoring", "Restoring"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey("core.Tenant", on_delete=models.PROTECT, related_name="restore_requests")
    backup = models.ForeignKey(TenantBackup, on_delete=models.PROTECT, related_name="restore_requests")
    schema_name = models.CharField(max_length=63)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.REQUESTED, db_index=True)
    reason = models.TextField(blank=True, default="")
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="requested_tenant_restores",
    )
    requested_at = models.DateTimeField(auto_now_add=True)
    safety_backup = models.ForeignKey(
        TenantBackup,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="safety_backup_for_restore_requests",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_tenant_restores",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rejected_tenant_restores",
    )
    rejected_at = models.DateTimeField(null=True, blank=True)
    decision_note = models.TextField(blank=True, default="")
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True, default="")
    tenant_runtime_snapshot = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "backups_tenant_restore_request"
        ordering = ("-requested_at",)
        indexes = [
            models.Index(fields=("tenant", "status", "-requested_at"), name="restore_tenant_status_idx"),
        ]

    def __str__(self):
        return f"{self.tenant_id}:{self.id} ({self.status})"
