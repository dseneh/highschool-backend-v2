import time

from django.core.management.base import BaseCommand
from django_tenants.utils import get_public_schema_name, schema_context

from backups.models import TenantBackup
from backups.services import BackupError, run_backup


class Command(BaseCommand):
    help = "Process queued tenant backups from the shared/public schema."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Process currently queued jobs and exit.")
        parser.add_argument("--poll-seconds", type=int, default=10, help="Seconds to wait when the queue is empty.")

    def handle(self, *args, **options):
        poll_seconds = max(1, options["poll_seconds"])
        while True:
            processed = self._process_one()
            if processed:
                continue
            if options["once"]:
                return
            time.sleep(poll_seconds)

    def _process_one(self):
        with schema_context(get_public_schema_name()):
            backup_id = (
                TenantBackup.objects.filter(status=TenantBackup.Status.QUEUED)
                .order_by("requested_at")
                .values_list("pk", flat=True)
                .first()
            )
            if backup_id is None:
                return False
            try:
                backup = run_backup(backup_id)
            except BackupError as exc:
                self.stderr.write(f"Backup {backup_id} was not processed: {exc}")
            except Exception as exc:
                self.stderr.write(self.style.ERROR(f"Backup {backup_id} failed: {exc}"))
            else:
                self.stdout.write(self.style.SUCCESS(f"Backup {backup.id} is available."))
            return True
