from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from django.conf import settings
from django.utils import timezone as dj_timezone

from billing.constants import (
    BILLING_STATE_ACTIVE,
    BILLING_STATE_COMPLIMENTARY,
    BILLING_STATE_EXPIRED,
    BILLING_STATE_EXPIRING_SOON,
    BILLING_STATE_GRACE,
    BILLING_STATE_NONE,
    BILLING_STATE_PAST_DUE,
    BILLING_STATE_TRIALING,
)


def _now() -> datetime:
    return dj_timezone.now()


def _days_between(start: datetime | None, end: datetime | None) -> int | None:
    if not start or not end:
        return None
    delta = end - start
    return max(0, delta.days)


@dataclass
class BillingSnapshot:
    billing_state: str
    days_until_renewal: int | None
    days_past_due: int | None
    renewal_date: datetime | None
    complimentary_until: datetime | None
    enabled_addons: list[str]
    subscription_status: str
    billing_interval: str
    is_write_allowed: bool
    is_admin_login_only: bool
    show_billing_banner: bool
    banner_variant: str
    banner_message: str
    banner_cta_label: str | None


def compute_billing_state(tenant) -> str:
    now = _now()

    complimentary_until = getattr(tenant, "complimentary_until", None)
    if complimentary_until and complimentary_until > now:
        return BILLING_STATE_COMPLIMENTARY

    status = (getattr(tenant, "subscription_status", "") or "").lower()
    if status == "trialing":
        return BILLING_STATE_TRIALING

    if status in {"canceled", "unpaid", "incomplete_expired"}:
        return BILLING_STATE_EXPIRED

    if status == "past_due":
        past_due_since = getattr(tenant, "past_due_since", None)
        if past_due_since:
            days = (now - past_due_since).days
            grace_start = settings.BILLING_PAST_DUE_FULL_ACCESS_DAYS
            grace_end = grace_start + settings.BILLING_GRACE_DAYS
            if days >= grace_end:
                return BILLING_STATE_EXPIRED
            if days >= grace_start:
                return BILLING_STATE_GRACE
        return BILLING_STATE_PAST_DUE

    if status in {"active", "paused"}:
        period_end = getattr(tenant, "current_period_end", None)
        if period_end and period_end > now:
            days_left = (period_end - now).days
            if days_left <= settings.BILLING_EXPIRING_SOON_DAYS:
                return BILLING_STATE_EXPIRING_SOON
        return BILLING_STATE_ACTIVE

    if complimentary_until and complimentary_until <= now:
        return BILLING_STATE_NONE

    if getattr(tenant, "stripe_subscription_id", ""):
        return BILLING_STATE_NONE

    return BILLING_STATE_NONE


def build_billing_snapshot(tenant, *, for_admin: bool = False) -> BillingSnapshot:
    state = compute_billing_state(tenant)
    now = _now()
    period_end = getattr(tenant, "current_period_end", None)
    complimentary_until = getattr(tenant, "complimentary_until", None)
    past_due_since = getattr(tenant, "past_due_since", None)
    enabled_addons = list(getattr(tenant, "enabled_addons", None) or [])

    days_until_renewal = None
    renewal_date = None
    if state in {BILLING_STATE_COMPLIMENTARY, BILLING_STATE_TRIALING} and complimentary_until:
        renewal_date = complimentary_until
        days_until_renewal = max(0, (complimentary_until - now).days)
    elif period_end and period_end > now:
        renewal_date = period_end
        days_until_renewal = max(0, (period_end - now).days)

    days_past_due = None
    if past_due_since and state in {BILLING_STATE_PAST_DUE, BILLING_STATE_GRACE, BILLING_STATE_EXPIRED}:
        days_past_due = max(0, (now - past_due_since).days)

    is_write_allowed = state not in {BILLING_STATE_GRACE, BILLING_STATE_EXPIRED, BILLING_STATE_NONE}
    is_admin_login_only = state in {BILLING_STATE_EXPIRED, BILLING_STATE_NONE}

    banner_variant = "info"
    banner_message = ""
    banner_cta_label = None
    show_billing_banner = False

    if state == BILLING_STATE_COMPLIMENTARY and for_admin:
        if days_until_renewal is not None and days_until_renewal <= settings.BILLING_EXPIRING_SOON_DAYS:
            show_billing_banner = True
            banner_variant = "warning" if days_until_renewal <= 7 else "info"
            banner_message = (
                f"Complimentary partner access ends on {complimentary_until.date().isoformat()}. "
                "Set up billing to avoid interruption."
            )
            banner_cta_label = "Set up billing"
    elif state == BILLING_STATE_TRIALING and for_admin:
        if days_until_renewal is not None and days_until_renewal <= settings.BILLING_EXPIRING_SOON_DAYS:
            show_billing_banner = True
            banner_variant = "warning"
            banner_message = f"Your trial ends on {renewal_date.date().isoformat() if renewal_date else 'soon'}."
            banner_cta_label = "Manage billing"
    elif state == BILLING_STATE_EXPIRING_SOON and for_admin:
        show_billing_banner = True
        banner_variant = "warning"
        banner_message = (
            f"Your subscription renews on {period_end.date().isoformat() if period_end else 'soon'}."
        )
        banner_cta_label = "Manage billing"
    elif state == BILLING_STATE_PAST_DUE and for_admin:
        show_billing_banner = True
        banner_variant = "error"
        grace_end_days = settings.BILLING_PAST_DUE_FULL_ACCESS_DAYS + settings.BILLING_GRACE_DAYS
        banner_message = "Payment failed. Update your billing details to avoid service interruption."
        banner_cta_label = "Update payment"
    elif state == BILLING_STATE_GRACE:
        show_billing_banner = True
        banner_variant = "error"
        banner_message = (
            "This workspace is read-only until billing is resolved."
            if not for_admin
            else "Payment overdue — workspace is read-only for non-admins until billing is resolved."
        )
        banner_cta_label = "Pay now" if for_admin else None
    elif state in {BILLING_STATE_EXPIRED, BILLING_STATE_NONE} and for_admin:
        show_billing_banner = True
        banner_variant = "error"
        banner_message = "Subscription inactive — renew to restore full access."
        banner_cta_label = "Renew subscription"

    return BillingSnapshot(
        billing_state=state,
        days_until_renewal=days_until_renewal,
        days_past_due=days_past_due,
        renewal_date=renewal_date,
        complimentary_until=complimentary_until,
        enabled_addons=enabled_addons,
        subscription_status=getattr(tenant, "subscription_status", "") or "",
        billing_interval=getattr(tenant, "billing_interval", "") or "",
        is_write_allowed=is_write_allowed,
        is_admin_login_only=is_admin_login_only,
        show_billing_banner=show_billing_banner,
        banner_variant=banner_variant,
        banner_message=banner_message,
        banner_cta_label=banner_cta_label,
    )


_PUBLIC_BILLING_FIELDS = frozenset(
    {
        "billing_state",
        "days_until_renewal",
        "complimentary_until",
        "is_write_allowed",
        "is_admin_login_only",
        "show_billing_banner",
        "banner_variant",
        "banner_message",
        "banner_cta_label",
    }
)

# Read-only subscription view for school tenant admins (Settings → Billing).
_TENANT_ADMIN_BILLING_FIELDS = _PUBLIC_BILLING_FIELDS | frozenset(
    {
        "renewal_date",
        "subscription_status",
        "billing_interval",
        "enabled_addons",
        "days_past_due",
    }
)


def billing_summary_dict(
    tenant,
    *,
    for_banner: bool = False,
    scope: str = "public",
) -> dict[str, Any]:
    """
    scope:
      - public: unauthenticated / generic tenant discovery
      - tenant_admin: school workspace admin (subscribe + read-only status)
      - platform: platform superadmin (full operational fields)
    """
    snap = build_billing_snapshot(tenant, for_admin=for_banner)
    payload = {
        "billing_state": snap.billing_state,
        "days_until_renewal": snap.days_until_renewal,
        "days_past_due": snap.days_past_due,
        "renewal_date": snap.renewal_date.isoformat() if snap.renewal_date else None,
        "complimentary_until": snap.complimentary_until.isoformat() if snap.complimentary_until else None,
        "enabled_addons": snap.enabled_addons,
        "subscription_status": snap.subscription_status,
        "billing_interval": snap.billing_interval,
        "is_write_allowed": snap.is_write_allowed,
        "is_admin_login_only": snap.is_admin_login_only,
        "show_billing_banner": snap.show_billing_banner,
        "banner_variant": snap.banner_variant,
        "banner_message": snap.banner_message,
        "banner_cta_label": snap.banner_cta_label,
    }
    if scope == "platform":
        return payload
    if scope == "tenant_admin":
        return {key: payload[key] for key in _TENANT_ADMIN_BILLING_FIELDS if key in payload}
    return {key: payload[key] for key in _PUBLIC_BILLING_FIELDS if key in payload}
