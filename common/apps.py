from django.apps import AppConfig


class CommonConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "common"

    def ready(self):
        """Import signal handlers when app is ready."""
        import common.cache_signals  # noqa: F401
