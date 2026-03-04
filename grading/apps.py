from django.apps import AppConfig


class GradingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "grading"

    def ready(self):
        """Register signals when app is ready"""
        import grading.signals  # noqa

