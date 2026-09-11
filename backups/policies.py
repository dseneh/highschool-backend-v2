from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from django.utils import timezone

from backups.models import BackupPlatformSettings, TenantBackup, TenantBackupPolicy


class BackupPolicyError(RuntimeError):
    pass


@dataclass(frozen=True)
class EffectiveBackupPolicy:
    automatic_backups_enabled: bool
    frequency: str
    scheduled_time: object
    timezone: str
    scheduled_retention_days: int
    manual_retention_days: int
    safety_retention_days: int
    system_retention_days: int
    maximum_retained_scheduled_backups: int
    manual_backups_allowed: bool
    restore_requests_allowed: bool
    restore_execution_allowed: bool
    storage_quota_bytes: int | None


def _platform_defaults_from_settings():
    interval_hours = max(1, int(getattr(settings, "TENANT_BACKUP_SCHEDULE_INTERVAL_HOURS", 168)))
    frequency = (
        BackupPlatformSettings.Frequency.DAILY
        if interval_hours <= 24
        else BackupPlatformSettings.Frequency.WEEKLY
    )
    return {
        "automatic_backups_enabled": bool(getattr(settings, "TENANT_BACKUP_SCHEDULE_ENABLED", True)),
        "frequency": frequency,
        "timezone": getattr(settings, "TIME_ZONE", "UTC") or "UTC",
        "scheduled_retention_days": max(0, int(getattr(settings, "TENANT_BACKUP_RETENTION_SCHEDULED_DAYS", 30))),
        "manual_retention_days": max(0, int(getattr(settings, "TENANT_BACKUP_RETENTION_MANUAL_DAYS", 30))),
        "safety_retention_days": max(0, int(getattr(settings, "TENANT_BACKUP_RETENTION_PRE_RESTORE_DAYS", 14))),
        "system_retention_days": max(0, int(getattr(settings, "TENANT_BACKUP_RETENTION_SYSTEM_DAYS", 30))),
    }


def get_platform_backup_settings():
    obj, _ = BackupPlatformSettings.objects.get_or_create(pk=1, defaults=_platform_defaults_from_settings())
    return obj


def get_or_create_tenant_policy(tenant):
    policy, _ = TenantBackupPolicy.objects.get_or_create(tenant=tenant)
    return policy


def _choose(override, default):
    return default if override is None else override


def effective_policy(tenant, *, create_state=False):
    platform = get_platform_backup_settings()
    if create_state:
        policy = get_or_create_tenant_policy(tenant)
    else:
        try:
            policy = TenantBackupPolicy.objects.get(tenant=tenant)
        except TenantBackupPolicy.DoesNotExist:
            policy = None

    def attr(name):
        return getattr(policy, name) if policy is not None else None

    timezone_name = attr("timezone") or platform.timezone
    storage_quota_bytes = (
        attr("storage_quota_bytes")
        if policy is not None and policy.storage_quota_overridden
        else platform.default_storage_quota_bytes
    )
    return EffectiveBackupPolicy(
        automatic_backups_enabled=_choose(attr("automatic_backups_enabled"), platform.automatic_backups_enabled),
        frequency=_choose(attr("frequency"), platform.frequency),
        scheduled_time=_choose(attr("scheduled_time"), platform.scheduled_time),
        timezone=timezone_name,
        scheduled_retention_days=_choose(attr("scheduled_retention_days"), platform.scheduled_retention_days),
        manual_retention_days=_choose(attr("manual_retention_days"), platform.manual_retention_days),
        safety_retention_days=_choose(attr("safety_retention_days"), platform.safety_retention_days),
        system_retention_days=_choose(attr("system_retention_days"), platform.system_retention_days),
        maximum_retained_scheduled_backups=_choose(
            attr("maximum_retained_scheduled_backups"), platform.maximum_retained_scheduled_backups
        ),
        manual_backups_allowed=_choose(attr("manual_backups_allowed"), platform.tenant_manual_backups_allowed),
        restore_requests_allowed=_choose(attr("restore_requests_allowed"), platform.tenant_restore_requests_allowed),
        restore_execution_allowed=_choose(attr("restore_execution_allowed"), platform.tenant_restore_execution_allowed),
        storage_quota_bytes=storage_quota_bytes,
    )


def retention_days_for(tenant, backup_type):
    policy = effective_policy(tenant)
    mapping = {
        TenantBackup.BackupType.MANUAL: policy.manual_retention_days,
        TenantBackup.BackupType.SCHEDULED: policy.scheduled_retention_days,
        TenantBackup.BackupType.PRE_RESTORE: policy.safety_retention_days,
        TenantBackup.BackupType.SYSTEM: policy.system_retention_days,
    }
    return max(0, int(mapping[backup_type]))


def require_manual_backup_allowed(tenant):
    if not effective_policy(tenant).manual_backups_allowed:
        raise BackupPolicyError("Manual backups have been disabled for this workspace by EzySchool.")


def require_restore_request_allowed(tenant):
    if not effective_policy(tenant).restore_requests_allowed:
        raise BackupPolicyError("Restore requests have been disabled for this workspace by EzySchool.")


def require_restore_execution_allowed(tenant):
    if not effective_policy(tenant).restore_execution_allowed:
        raise BackupPolicyError("Restore execution has been disabled for this workspace by EzySchool.")


def calculate_next_run(policy, *, after=None):
    """Return the next UTC run at or after the tenant's configured local wall-clock schedule."""
    after = after or timezone.now()
    try:
        tz = ZoneInfo(policy.timezone)
    except ZoneInfoNotFoundError as exc:
        raise BackupPolicyError(f"Invalid backup timezone: {policy.timezone}") from exc

    local_after = after.astimezone(tz)
    candidate = datetime.combine(local_after.date(), policy.scheduled_time, tzinfo=tz)
    if candidate <= local_after:
        days = 1 if policy.frequency == BackupPlatformSettings.Frequency.DAILY else 7
        candidate += timedelta(days=days)
    return candidate.astimezone(ZoneInfo("UTC"))


def ensure_schedule_state(tenant, *, now=None, recalculate=False):
    state = get_or_create_tenant_policy(tenant)
    policy = effective_policy(tenant)
    now = now or timezone.now()
    if not policy.automatic_backups_enabled:
        if state.next_run_at is not None:
            state.next_run_at = None
            state.save(update_fields=["next_run_at", "updated_at"])
        return state
    if recalculate or state.next_run_at is None:
        state.next_run_at = calculate_next_run(policy, after=now - timedelta(seconds=1))
        state.save(update_fields=["next_run_at", "updated_at"])
    return state


def mark_scheduled_backup_completed(backup, *, completed_at=None):
    if backup.backup_type != TenantBackup.BackupType.SCHEDULED:
        return
    state = get_or_create_tenant_policy(backup.tenant)
    completed_at = completed_at or backup.completed_at or timezone.now()
    state.last_run_at = completed_at
    policy = effective_policy(backup.tenant)
    state.next_run_at = calculate_next_run(policy, after=completed_at)
    state.save(update_fields=["last_run_at", "next_run_at", "updated_at"])
