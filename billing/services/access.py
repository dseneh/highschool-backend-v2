from __future__ import annotations

from billing.constants import ADDON_PAYROLL, ADDON_SMS
from billing.services.state import compute_billing_state


def tenant_has_addon(tenant, addon_key: str) -> bool:
    enabled = getattr(tenant, "enabled_addons", None) or []
    if addon_key not in enabled:
        return False
    state = compute_billing_state(tenant)
    if state in {"complimentary", "trialing", "active", "expiring_soon", "past_due"}:
        return True
    return False


def tenant_has_payroll(tenant) -> bool:
    return tenant_has_addon(tenant, ADDON_PAYROLL)


def tenant_has_sms(tenant) -> bool:
    return tenant_has_addon(tenant, ADDON_SMS)


def billing_blocks_writes(tenant, *, is_tenant_admin: bool) -> bool:
    state = compute_billing_state(tenant)
    if state == "grace" and not is_tenant_admin:
        return True
    if state in {"expired", "none"}:
        return not is_tenant_admin
    return False
