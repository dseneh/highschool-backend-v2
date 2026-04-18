from django.apps import AppConfig


class CommonConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "common"

    def ready(self):
        """Import signal handlers and audit trail registration when app is ready."""
        import common.cache_signals  # noqa: F401

        # Register all models with django-auditlog for change tracking.
        # Wrapped in try/except so the app still starts during initial
        # migrations before the auditlog table exists.
        try:
            from common.audit_registry import register_all_models
            register_all_models()
        except Exception:
            pass
