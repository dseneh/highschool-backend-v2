from django.core.management.base import BaseCommand
from django_tenants.utils import get_public_schema_name, schema_context

from backups.services import purge_expired_backups, queue_due_scheduled_backups, recover_stale_backups


class Command(BaseCommand):
    help = "Run tenant backup maintenance: stale recovery, scheduled queueing, and retention cleanup."

    def handle(self, *args, **options):
        with schema_context(get_public_schema_name()):
            stale = recover_stale_backups()
            queued = queue_due_scheduled_backups()
            deleted = purge_expired_backups()

        self.stdout.write(
            self.style.SUCCESS(
                f"Backup maintenance complete: stale={len(stale)}, queued={len(queued)}, deleted={len(deleted)}."
            )
        )
