from __future__ import annotations

import logging
from datetime import datetime

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone
from django_tenants.utils import schema_context

from billing.constants import (
    BILLING_STATE_COMPLIMENTARY,
    BILLING_STATE_EXPIRING_SOON,
    BILLING_STATE_GRACE,
    BILLING_STATE_PAST_DUE,
)
from billing.services.state import compute_billing_state
from common.status import Roles
from core.models import Tenant
from users.utils import build_frontend_url

logger = logging.getLogger(__name__)

REMINDER_MILESTONES = (30, 14, 7, 3)
PAST_DUE_REMINDER_DAYS = (1, 6)


def _reminder_cache_key(tenant_id, kind: str, marker: str) -> str:
    return f"billing_reminder:{tenant_id}:{kind}:{marker}"


def _mark_reminder_sent(tenant_id, kind: str, marker: str) -> None:
    cache.set(_reminder_cache_key(tenant_id, kind, marker), True, timeout=60 * 60 * 48)


def _reminder_already_sent(tenant_id, kind: str, marker: str) -> bool:
    return bool(cache.get(_reminder_cache_key(tenant_id, kind, marker)))


def collect_tenant_admin_emails(tenant: Tenant) -> list[str]:
    emails: set[str] = set()
    if tenant.email:
        emails.add(tenant.email.strip().lower())

    schema = tenant.schema_name
    if not schema or schema == "public":
        return sorted(emails)

    with schema_context(schema):
        from users.models import User

        admins = User.objects.filter(
            is_active=True,
            role__in=[Roles.ADMIN, Roles.SUPERADMIN],
        ).exclude(email="")
        for user in admins:
            emails.add(user.email.strip().lower())

    return sorted(emails)


def _tenant_workspace(tenant: Tenant) -> str:
    return tenant.schema_name


def _billing_settings_url(tenant: Tenant) -> str:
    return build_frontend_url(_tenant_workspace(tenant), "/settings/billing")


def _days_until(end: datetime | None, *, now: datetime | None = None) -> int | None:
    if not end:
        return None
    now = now or timezone.now()
    return max(0, (end - now).days)


def _send_reminder(tenant: Tenant, *, kind: str, marker: str, subject: str, template_context: dict) -> bool:
    if _reminder_already_sent(tenant.id, kind, marker):
        return False

    recipients = collect_tenant_admin_emails(tenant)
    if not recipients:
        logger.warning("No admin recipients for billing reminder (%s) on tenant %s", kind, tenant.schema_name)
        return False

    from common.email_service import send_billing_reminder_email

    ok = send_billing_reminder_email(
        to=recipients,
        subject=subject,
        tenant=tenant,
        context=template_context,
    )
    if ok:
        _mark_reminder_sent(tenant.id, kind, marker)
    return ok


def process_tenant_billing_reminders(tenant: Tenant, *, now: datetime | None = None) -> int:
    """Return count of reminder emails sent for this tenant."""
    now = now or timezone.now()
    sent = 0
    state = compute_billing_state(tenant)
    billing_url = _billing_settings_url(tenant)
    school_name = tenant.name or tenant.schema_name

    complimentary_until = getattr(tenant, "complimentary_until", None)
    if state == BILLING_STATE_COMPLIMENTARY and complimentary_until and complimentary_until > now:
        days_left = _days_until(complimentary_until, now=now)
        if days_left in REMINDER_MILESTONES:
            marker = f"complimentary:{complimentary_until.date().isoformat()}:{days_left}"
            if _send_reminder(
                tenant,
                kind="complimentary_ending",
                marker=marker,
                subject=f"EzySchool billing starts in {days_left} days — {school_name}",
                template_context={
                    "reminder_type": "complimentary_ending",
                    "days_remaining": days_left,
                    "end_date": complimentary_until.strftime("%B %d, %Y"),
                    "billing_url": billing_url,
                    "school_name": school_name,
                },
            ):
                sent += 1

    period_end = getattr(tenant, "current_period_end", None)
    if state == BILLING_STATE_EXPIRING_SOON and period_end and period_end > now:
        days_left = _days_until(period_end, now=now)
        if days_left in REMINDER_MILESTONES:
            marker = f"renewal:{period_end.date().isoformat()}:{days_left}"
            if _send_reminder(
                tenant,
                kind="subscription_renewal",
                marker=marker,
                subject=f"EzySchool subscription renews in {days_left} days — {school_name}",
                template_context={
                    "reminder_type": "subscription_renewal",
                    "days_remaining": days_left,
                    "end_date": period_end.strftime("%B %d, %Y"),
                    "billing_url": billing_url,
                    "school_name": school_name,
                },
            ):
                sent += 1

    past_due_since = getattr(tenant, "past_due_since", None)
    if state in {BILLING_STATE_PAST_DUE, BILLING_STATE_GRACE} and past_due_since:
        days_overdue = max(0, (now - past_due_since).days)
        if days_overdue in PAST_DUE_REMINDER_DAYS:
            marker = f"past_due:{past_due_since.date().isoformat()}:{days_overdue}"
            if _send_reminder(
                tenant,
                kind="past_due",
                marker=marker,
                subject=f"Action required: EzySchool payment overdue — {school_name}",
                template_context={
                    "reminder_type": "past_due",
                    "days_overdue": days_overdue,
                    "billing_url": billing_url,
                    "school_name": school_name,
                    "in_grace": state == BILLING_STATE_GRACE,
                },
            ):
                sent += 1

    return sent


def send_all_billing_reminders(*, dry_run: bool = False) -> dict[str, int]:
    """Scan all active tenants and send due billing reminder emails."""
    totals = {"tenants_checked": 0, "emails_sent": 0, "skipped_dry_run": 0}

    tenants = Tenant.objects.exclude(schema_name="public").filter(is_active=True)
    for tenant in tenants.iterator():
        totals["tenants_checked"] += 1
        if dry_run:
            totals["skipped_dry_run"] += 1
            continue
        totals["emails_sent"] += process_tenant_billing_reminders(tenant)

    return totals
