from __future__ import annotations

from datetime import datetime, timezone

from django.utils import timezone as dj_timezone

from billing.constants import (
    ADDON_KEYS,
    STRIPE_PRODUCT_TYPE_ADDON,
    STRIPE_PRODUCT_TYPE_BASE,
)
from billing.services.state import compute_billing_state
from core.models import Tenant


def _product_meta(product) -> dict:
    if isinstance(product, dict):
        return product.get("metadata") or {}
    return getattr(product, "metadata", None) or {}


def _parse_subscription_items(subscription: dict) -> tuple[list[str], int, int, str]:
    enabled_addons: list[str] = []
    enrollment_count = 0
    employee_count = 0
    billing_interval = ""

    for item in subscription.get("items", {}).get("data", []):
        price = item.get("price") or {}
        product = price.get("product") or {}
        meta = _product_meta(product)
        product_type = meta.get("type", "")
        quantity = int(item.get("quantity") or 0)
        interval = (price.get("recurring") or {}).get("interval") or ""

        if product_type == STRIPE_PRODUCT_TYPE_BASE:
            enrollment_count = quantity
            if interval:
                billing_interval = interval
        elif product_type == STRIPE_PRODUCT_TYPE_ADDON:
            addon_key = meta.get("addon_key", "")
            if addon_key in ADDON_KEYS:
                enabled_addons.append(addon_key)
            if addon_key == "payroll":
                employee_count = quantity

        if not billing_interval and interval:
            billing_interval = interval

    return enabled_addons, enrollment_count, employee_count, billing_interval


def _to_datetime(ts) -> datetime | None:
    if not ts:
        return None
    return datetime.fromtimestamp(int(ts), tz=timezone.utc)


def sync_tenant_from_subscription(tenant: Tenant, subscription: dict) -> Tenant:
    enabled_addons, enrollment_count, employee_count, billing_interval = _parse_subscription_items(
        subscription
    )

    status = subscription.get("status") or ""
    period_end = _to_datetime(subscription.get("current_period_end"))

    update_fields = [
        "stripe_subscription_id",
        "subscription_status",
        "billing_interval",
        "current_period_end",
        "enabled_addons",
        "billing_enrollment_count",
        "billing_employee_count",
        "updated_at",
    ]

    tenant.stripe_subscription_id = subscription.get("id") or tenant.stripe_subscription_id
    tenant.subscription_status = status
    tenant.billing_interval = billing_interval
    tenant.current_period_end = period_end
    tenant.enabled_addons = enabled_addons
    tenant.billing_enrollment_count = enrollment_count
    tenant.billing_employee_count = employee_count

    if status == "past_due" and not tenant.past_due_since:
        tenant.past_due_since = dj_timezone.now()
        update_fields.append("past_due_since")
    elif status in {"active", "trialing"}:
        if tenant.past_due_since:
            tenant.past_due_since = None
            update_fields.append("past_due_since")
        if status == "active" and tenant.login_access_policy != "all_users":
            tenant.login_access_policy = "all_users"
            update_fields.append("login_access_policy")

    billing_state = compute_billing_state(tenant)
    if billing_state == "expired":
        tenant.login_access_policy = "tenant_admin_only"
        if "login_access_policy" not in update_fields:
            update_fields.append("login_access_policy")

    tenant.save(update_fields=update_fields)
    return tenant


def find_tenant_for_stripe_object(obj: dict) -> Tenant | None:
    metadata = obj.get("metadata") or {}
    schema_name = metadata.get("schema_name")
    tenant_id = metadata.get("tenant_id")

    if tenant_id:
        tenant = Tenant.objects.filter(id=tenant_id).first()
        if tenant:
            return tenant

    if schema_name:
        return Tenant.objects.filter(schema_name=schema_name).first()

    customer_id = obj.get("customer")
    if customer_id:
        return Tenant.objects.filter(stripe_customer_id=customer_id).first()

    return None
