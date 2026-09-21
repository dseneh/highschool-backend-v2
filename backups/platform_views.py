from datetime import timedelta

from django.utils import timezone
from django_tenants.utils import get_public_schema_name, schema_context
from rest_framework.decorators import action
from rest_framework.response import Response

from backups.models import TenantBackup, TenantBackupPolicy
from backups.policies import calculate_next_run, effective_policy
from backups.views import PlatformBackupViewSet
from core.models import Tenant


class PolicyAwarePlatformBackupViewSet(PlatformBackupViewSet):
    """Platform backup history with policy-aware scheduling summary metrics."""

    @action(detail=False, methods=["get"])
    def summary(self, request):
        self._require_public_workspace()
        now = timezone.now()
        with schema_context(get_public_schema_name()):
            backups = TenantBackup.objects.select_related("tenant")
            total_backup_count = backups.count()
            available_backups = backups.filter(status=TenantBackup.Status.AVAILABLE)
            available_backup_count = available_backups.count()
            total_storage_bytes = sum(backup.file_size or 0 for backup in available_backups)
            failed_backup_count = backups.filter(status=TenantBackup.Status.FAILED).count()
            scheduled_backup_count = backups.filter(
                backup_type=TenantBackup.BackupType.SCHEDULED
            ).count()

            protected_tenant_count = len(
                set(available_backups.values_list("tenant_id", flat=True))
            )

            upcoming_backup_count = 0
            upcoming_times = []
            active_tenants = Tenant.objects.exclude(
                schema_name=get_public_schema_name()
            ).filter(active=True)

            for tenant in active_tenants.iterator():
                policy = effective_policy(tenant)
                if not policy.automatic_backups_enabled:
                    continue

                try:
                    state = TenantBackupPolicy.objects.get(tenant=tenant)
                    next_due = state.next_run_at
                except TenantBackupPolicy.DoesNotExist:
                    next_due = None

                if next_due is None:
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
                    next_due = calculate_next_run(policy, after=base)

                upcoming_times.append(next_due)
                if next_due <= now:
                    upcoming_backup_count += 1

            next_scheduled_backup_at = min(upcoming_times) if upcoming_times else None

            return Response(
                {
                    "total_backup_count": total_backup_count,
                    "available_backup_count": available_backup_count,
                    "total_storage_bytes": total_storage_bytes,
                    "protected_tenant_count": protected_tenant_count,
                    "failed_backup_count": failed_backup_count,
                    "scheduled_backup_count": scheduled_backup_count,
                    "upcoming_backup_count": upcoming_backup_count,
                    "next_scheduled_backup_at": (
                        next_scheduled_backup_at.isoformat()
                        if next_scheduled_backup_at
                        else None
                    ),
                }
            )
