import shutil

from django.conf import settings
from django.core.files.storage import storages
from django.core.management.base import BaseCommand, CommandError
from django.db import connection


class Command(BaseCommand):
    help = "Validate database tools, object storage, and database access required by backup services."

    def add_arguments(self, parser):
        parser.add_argument(
            "--mode",
            choices=("backup", "restore", "maintenance"),
            required=True,
        )
        parser.add_argument("--require-object-storage", action="store_true")

    def handle(self, *args, **options):
        mode = options["mode"]
        errors = []

        required_binary = {"backup": "pg_dump", "restore": "pg_restore"}.get(mode)
        if required_binary and shutil.which(required_binary) is None:
            errors.append(f"{required_binary} is not installed or is not on PATH")

        if options["require_object_storage"] and not settings.USE_S3_STORAGE:
            errors.append("USE_S3_STORAGE must be True; Railway filesystem storage is ephemeral")

        try:
            backup_storage = storages["backups"]
            if options["require_object_storage"] and not getattr(backup_storage, "bucket_name", None):
                errors.append("the backups storage alias is not configured with an object-storage bucket")
        except Exception as exc:
            errors.append(f"the backups storage alias could not be initialized: {exc}")

        try:
            connection.ensure_connection()
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
        except Exception as exc:
            errors.append(f"the production database is unavailable: {exc}")

        if errors:
            raise CommandError("Backup runtime validation failed: " + "; ".join(errors))

        self.stdout.write(self.style.SUCCESS(f"Backup runtime validation passed for {mode}."))
