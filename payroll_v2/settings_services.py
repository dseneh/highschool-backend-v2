"""Tenant payroll settings helpers."""

from __future__ import annotations

from .models import PayrollSettings


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
