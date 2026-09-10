from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone
from django_tenants.utils import get_public_schema_name, schema_context

from backups.models import TenantBackup
from backups.services import (
    ACTIVE_STATUSES,
    RUNNING_STATUSES,
    purge_expired_backups,
    queue_due_scheduled_backups,
    recover_stale_backups,
)
from core.models import Tenant


class Command(BaseCommand):
    help = "Run tenant backup maintenance: stale recovery, scheduled queueing, and retention cleanup."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report maintenance actions without changing backup records or storage.",
        )
        group = parser.add_mutually_exclusive_group()
        group.add_argument("--stale-only", action="store_true", help="Run only stale backup recovery.")
        group.add_argument("--schedule-only", action="store_true", help="Run only scheduled backup queueing.")
        group.add_argument("--retention-only", action="store_true", help="Run only expired backup cleanup.")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        run_stale = not (options["schedule_only"] or options["retention_only"])
        run_schedule = not (options["stale_only"] or options["retention_only"])
        run_retention = not (options["stale_only"] or options["schedule_only"])

        with schema_context(get_public_schema_name()):
            if dry_run:
                stale_count = self._preview_stale_count() if run_stale else 0
                scheduled_count = self._preview_schedule_count() if run_schedule else 0
                expired_count = self._preview_retention_count() if run_retention else 0
                self.stdout.write(
                    self.style.WARNING(
                        "DRY RUN — no database records or backup objects were changed. "
                        f"stale_would_fail={stale_count}, "
                        f"scheduled_would_queue={scheduled_count}, "
                        f"expired_would_delete={expired_count}."
                    )
                )
                return

            stale = recover_stale_backups() if run_stale else []
            queued = queue_due_scheduled_backups() if run_schedule else []
            deleted = purge_expired_backups() if run_retention else []

        self.stdout.write(
            self.style.SUCCESS(
                f"Backup maintenance complete: stale={len(stale)}, queued={len(queued)}, deleted={len(deleted)}."
            )
        )

    @staticmethod
    def _preview_stale_count():
        cutoff = timezone.now() - timedelta(minutes=max(1, settings.TENANT_BACKUP_STALE_MINUTES))
        return TenantBackup.objects.filter(status__in=RUNNING_STATUSES, updated_at__lt=cutoff).count()

    @staticmethod
    def _preview_retention_count():
        now = timezone.now()
        return TenantBackup.objects.filter(
            status__in=[TenantBackup.Status.AVAILABLE, TenantBackup.Status.DELETING],
            expires_at__isnull=False,
            expires_at__lte=now,
        ).count()

    @staticmethod
    def _preview_schedule_count():
        if not settings.TENANT_BACKUP_SCHEDULE_ENABLED:
            return 0

        cutoff = timezone.now() - timedelta(hours=max(1, settings.TENANT_BACKUP_SCHEDULE_INTERVAL_HOURS))
        count = 0
        for tenant in Tenant.objects.exclude(schema_name="public").filter(active=True).iterator():
            if TenantBackup.objects.filter(tenant=tenant, status__in=ACTIVE_STATUSES).exists():
                continue
            if TenantBackup.objects.filter(
                tenant=tenant,
                backup_type=TenantBackup.BackupType.SCHEDULED,
                status=TenantBackup.Status.AVAILABLE,
                completed_at__gt=cutoff,
            ).exists():
                continue
            count += 1
        return count
