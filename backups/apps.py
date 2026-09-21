from django.apps import AppConfig


class BackupsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "backups"
    verbose_name = "Tenant Backups"

    def ready(self):
        from auditlog.registry import auditlog
        from backups.models import (
            BackupPlatformSettings,
            TenantBackup,
            TenantBackupPolicy,
            TenantRestoreRequest,
        )

        if not auditlog.contains(TenantBackup):
            auditlog.register(
                TenantBackup,
                exclude_fields=["storage_key", "error_message"],
            )

        if not auditlog.contains(TenantRestoreRequest):
            auditlog.register(
                TenantRestoreRequest,
                exclude_fields=["tenant_runtime_snapshot", "error_message"],
            )

        if not auditlog.contains(BackupPlatformSettings):
            auditlog.register(BackupPlatformSettings)

        if not auditlog.contains(TenantBackupPolicy):
            auditlog.register(TenantBackupPolicy)
