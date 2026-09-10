from django.db import transaction

from backups.models import TenantBackup, TenantRestoreRequest
from backups.services import BackupError, request_backup


class RestoreError(RuntimeError):
    pass


ACTIVE_RESTORE_STATUSES = {
    TenantRestoreRequest.Status.REQUESTED,
    TenantRestoreRequest.Status.SAFETY_BACKUP_PENDING,
    TenantRestoreRequest.Status.READY_FOR_APPROVAL,
    TenantRestoreRequest.Status.APPROVED,
    TenantRestoreRequest.Status.RESTORING,
}


def request_restore(*, tenant, backup, requested_by=None, reason=""):
    """Create a non-destructive restore request and queue a pre-restore safety backup.

    This function intentionally does not perform pg_restore or alter schemas.
    Execution is a separate privileged phase.
    """
    with transaction.atomic():
        tenant = tenant.__class__.objects.select_for_update().get(pk=tenant.pk)
        backup = TenantBackup.objects.select_for_update().get(pk=backup.pk)

        if not tenant.schema_name or tenant.schema_name == "public":
            raise RestoreError("Refusing to restore an invalid/public tenant schema.")
        if backup.tenant_id != tenant.id:
            raise RestoreError("The selected backup does not belong to this tenant.")
        if backup.status != TenantBackup.Status.AVAILABLE:
            raise RestoreError("Only an available backup can be restored.")
        if not backup.storage_key or not backup.sha256 or not backup.file_size:
            raise RestoreError("The selected backup is missing verified restore metadata.")
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
    """Promote a restore request to approval-ready only after its safety backup is available."""
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
