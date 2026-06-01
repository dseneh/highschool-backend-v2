"""Delete and restore live benefit request lines around mark-paid."""

from __future__ import annotations

from decimal import Decimal

from django.conf import settings

from employee_benefits.enums import BenefitRequestStatus
from employee_benefits.models import BenefitRequest, BenefitRequestLine


def delete_paid_live_rows_enabled() -> bool:
    return getattr(settings, "DELETE_PAID_LIVE_ROWS", True)


def delete_paid_live_rows(benefit_request: BenefitRequest) -> int:
    """Remove live benefit request lines for a paid request. Returns deleted line count."""
    deleted_count, _ = benefit_request.lines.all().delete()
    return deleted_count


def restore_benefit_lines_from_snapshot(benefit_request: BenefitRequest, *, actor=None) -> int:
    """Recreate benefit request lines from paid_table_snapshot rows."""
    if benefit_request.lines.exists():
        return benefit_request.lines.count()

    snapshot = benefit_request.paid_table_snapshot or {}
    rows = snapshot.get("rows") or []
    if not rows:
        raise ValueError(
            "Cannot revert paid benefit request: paid_table_snapshot is missing line rows. "
            "Run backfill_disbursement_snapshots to capture the snapshot first."
        )

    restored = 0
    read_only_keys = {
        "employee_display",
        "benefit_type_name",
        "request_number",
        "request_status",
        "period_start",
        "period_end",
        "payment_date",
        "created_at",
        "updated_at",
        "request",
    }

    for row in rows:
        line_fields = {
            key: value for key, value in row.items() if key not in read_only_keys and key != "id"
        }
        line_fields["request_id"] = benefit_request.id
        for amount_field in ("computed_amount", "final_amount"):
            if amount_field in line_fields and line_fields[amount_field] is not None:
                line_fields[amount_field] = Decimal(str(line_fields[amount_field]))

        line_id = row.get("id")
        line = BenefitRequestLine(id=line_id, **line_fields)
        if actor is not None:
            line.created_by = actor
            line.updated_by = actor
        line.save(force_insert=True)
        restored += 1

    benefit_request.recalculate_totals()
    return restored


def purge_paid_live_rows_if_enabled(benefit_request: BenefitRequest) -> int:
    if benefit_request.status != BenefitRequestStatus.PAID or not delete_paid_live_rows_enabled():
        return 0
    return delete_paid_live_rows(benefit_request)
