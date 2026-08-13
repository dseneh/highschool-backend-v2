"""Tenant payroll settings helpers."""

from __future__ import annotations

from .models import PayrollSettings


SALARY_ADVANCE_FEATURE = "salary_advance"
WARD_SPONSORSHIP_FEATURE = "ward_sponsorship"

FEATURE_DISABLED_MESSAGES = {
    SALARY_ADVANCE_FEATURE: "Salary Advance is disabled in Payroll Settings.",
    WARD_SPONSORSHIP_FEATURE: "Ward Sponsorship is disabled in Payroll Settings.",
}


def get_tenant_payroll_settings(*, user=None) -> PayrollSettings:
    """Return the single tenant payroll settings row, creating one if needed."""
    settings = (
        PayrollSettings.objects.select_related("transaction_type")
        .order_by("created_at")
        .first()
    )
    if settings is not None:
        return settings

    return PayrollSettings.objects.create(
        created_by=user,
        updated_by=user,
    )


def ensure_payroll_feature_enabled(feature: str, *, user=None) -> PayrollSettings:
    """Reject feature-specific writes while leaving existing deductions untouched."""
    settings = get_tenant_payroll_settings(user=user)
    setting_name = {
        SALARY_ADVANCE_FEATURE: "allow_salary_advance",
        WARD_SPONSORSHIP_FEATURE: "allow_ward_sponsorship",
    }.get(feature)
    if setting_name is None:
        raise ValueError(f"Unknown payroll feature: {feature}")
    if not getattr(settings, setting_name):
        raise ValueError(FEATURE_DISABLED_MESSAGES[feature])
    return settings
