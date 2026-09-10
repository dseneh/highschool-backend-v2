import time

from django.core.management.base import BaseCommand
from django_tenants.utils import get_public_schema_name, schema_context

from backups.models import TenantRestoreRequest
from backups.restore_services import RestoreError, run_restore


class Command(BaseCommand):
    help = "Process approved tenant restore requests from the shared/public schema."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Process currently approved restores and exit.")
        parser.add_argument("--poll-seconds", type=int, default=10, help="Seconds to wait when no restore is approved.")

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
            restore_id = (
                TenantRestoreRequest.objects.filter(status=TenantRestoreRequest.Status.APPROVED)
                .order_by("approved_at", "requested_at")
                .values_list("pk", flat=True)
                .first()
            )
            if restore_id is None:
                return False
            try:
                restore_request = run_restore(restore_id)
            except RestoreError as exc:
                self.stderr.write(f"Restore {restore_id} was not processed: {exc}")
            except Exception as exc:
                self.stderr.write(self.style.ERROR(f"Restore {restore_id} failed: {exc}"))
            else:
                self.stdout.write(self.style.SUCCESS(f"Restore {restore_request.id} completed."))
            return True
