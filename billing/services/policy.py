from __future__ import annotations

from billing.services.state import compute_billing_state


def apply_billing_access_policy(tenant) -> None:
    """Auto-adjust login_access_policy for billing lock / restore."""
    if getattr(tenant, "login_access_policy", "") == "disabled":
        return

    state = compute_billing_state(tenant)
    update_fields = []

    if state in {"expired", "none"}:
        if tenant.login_access_policy != "tenant_admin_only":
            tenant.login_access_policy = "tenant_admin_only"
            update_fields.append("login_access_policy")
    elif state in {"active", "trialing", "expiring_soon", "past_due", "grace", "complimentary"}:
        if (
            tenant.login_access_policy == "tenant_admin_only"
            and (tenant.subscription_status or state == "complimentary")
        ):
            tenant.login_access_policy = "all_users"
            update_fields.append("login_access_policy")

    if update_fields:
        update_fields.append("updated_at")
        tenant.save(update_fields=update_fields)
