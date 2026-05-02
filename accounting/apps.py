from django.apps import AppConfig


class AccountingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounting"
    verbose_name = "Accounting"

    def ready(self):
        # Wire up signal handlers.
        from accounting import signals  # noqa: F401
