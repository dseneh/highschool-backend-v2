from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone
from django_tenants.utils import get_public_schema_name, schema_context

from backups.models import TenantBackup, TenantBackupPolicy, TenantRestoreRequest
from backups.policies import calculate_next_run, effective_policy
from backups.restore_services import recover_stale_restores
from backups.services import (
    ACTIVE_STATUSES,
    RUNNING_STATUSES,
    _backup_required_by_active_restore,
    _retention_candidates,
    purge_expired_backups,
    queue_due_scheduled_backups,
    recover_stale_backups,
)
from core.models import Tenant


class Command(BaseCommand):
    help = "Run tenant backup/restore maintenance: stale recovery, scheduled queueing, and retention cleanup."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report maintenance actions without changing backup records, restore records, schemas, or storage.",
        )
        group = parser.add_mutually_exclusive_group()
        group.add_argument("--stale-only", action="store_true", help="Run only stale backup/restore recovery.")
        group.add_argument("--schedule-only", action="store_true", help="Run only scheduled backup queueing.")
        group.add_argument("--retention-only", action="store_true", help="Run only expired backup cleanup.")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        run_stale = not (options["schedule_only"] or options["retention_only"])
        run_schedule = not (options["stale_only"] or options["retention_only"])
        run_retention = not (options["stale_only"] or options["schedule_only"])

        with schema_context(get_public_schema_name()):
            if dry_run:
                stale_backup_count = self._preview_stale_backup_count() if run_stale else 0
                stale_restore_count = self._preview_stale_restore_count() if run_stale else 0
                scheduled_count = self._preview_schedule_count() if run_schedule else 0
                retention_count = self._preview_retention_count() if run_retention else 0
                self.stdout.write(
                    self.style.WARNING(
                        "DRY RUN — no database records, schemas, or backup objects were changed. "
                        f"stale_backups_would_fail={stale_backup_count}, "
                        f"stale_restores_would_recover={stale_restore_count}, "
                        f"scheduled_would_queue={scheduled_count}, "
                        f"retention_would_delete={retention_count}."
                    )
                )
                return

            stale_backups = recover_stale_backups() if run_stale else []
            stale_restores = recover_stale_restores() if run_stale else []
            queued = queue_due_scheduled_backups() if run_schedule else []
            deleted = purge_expired_backups() if run_retention else []

        self.stdout.write(
            self.style.SUCCESS(
                "Backup/restore maintenance complete: "
                f"stale_backups={len(stale_backups)}, "
                f"stale_restores={len(stale_restores)}, "
                f"queued={len(queued)}, deleted={len(deleted)}."
            )
        )

    @staticmethod
    def _preview_stale_backup_count():
        cutoff = timezone.now() - timedelta(minutes=max(1, settings.TENANT_BACKUP_STALE_MINUTES))
        return TenantBackup.objects.filter(status__in=RUNNING_STATUSES, updated_at__lt=cutoff).count()

    @staticmethod
    def _preview_stale_restore_count():
        cutoff = timezone.now() - timedelta(minutes=max(1, settings.TENANT_RESTORE_STALE_MINUTES))
        return TenantRestoreRequest.objects.filter(
            status=TenantRestoreRequest.Status.RESTORING,
            updated_at__lt=cutoff,
        ).count()

    @staticmethod
    def _preview_retention_count():
        now = timezone.now()
        return sum(
            1
            for backup in _retention_candidates(now)
            if not _backup_required_by_active_restore(backup)
        )

    @staticmethod
    def _preview_schedule_count():
        now = timezone.now()
        count = 0
        for tenant in Tenant.objects.exclude(schema_name=get_public_schema_name()).filter(active=True).iterator():
            policy = effective_policy(tenant)
            if not policy.automatic_backups_enabled:
                continue
            if TenantBackup.objects.filter(tenant=tenant, status__in=ACTIVE_STATUSES).exists():
                continue

            try:
                state = TenantBackupPolicy.objects.get(tenant=tenant)
                next_run_at = state.next_run_at
            except TenantBackupPolicy.DoesNotExist:
                next_run_at = None

            if next_run_at is None:
                latest = (
                    TenantBackup.objects.filter(
                        tenant=tenant,
                        backup_type=TenantBackup.BackupType.SCHEDULED,
                        status=TenantBackup.Status.AVAILABLE,
                        completed_at__isnull=False,
                    )
                    .order_by("-completed_at")
                    .first()
                )
                base = latest.completed_at if latest else now - timedelta(seconds=1)
                next_run_at = calculate_next_run(policy, after=base)

            if next_run_at <= now:
                count += 1
        return count
