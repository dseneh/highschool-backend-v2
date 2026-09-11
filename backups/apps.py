from django.apps import AppConfig


class BackupsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "backups"
    verbose_name = "Tenant Backups"

    def ready(self):
        from auditlog.registry import auditlog
        from backups.models import TenantBackup, TenantRestoreRequest

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
