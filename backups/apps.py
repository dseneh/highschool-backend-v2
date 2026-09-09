from django.apps import AppConfig


class BackupsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "backups"
    verbose_name = "Tenant Backups"

    def ready(self):
        from auditlog.registry import auditlog
        from backups.models import TenantBackup

        if not auditlog.contains(TenantBackup):
            auditlog.register(
                TenantBackup,
                exclude_fields=["storage_key", "error_message"],
            )
