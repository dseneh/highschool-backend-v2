"""Delete and restore live payroll employee/line rows around mark-paid."""

from __future__ import annotations

from decimal import Decimal

from django.conf import settings

from payroll_v2.enums import PaymentStatus, PayrollStatus
from payroll_v2.models import PayrollEmployeeItem, PayrollLineItem, PayrollRunRecord
from payroll_v2.paid_table_snapshot import snapshot_has_rebuild_payload


def delete_paid_live_rows_enabled() -> bool:
    return getattr(settings, "DELETE_PAID_LIVE_ROWS", True)


def delete_paid_live_rows(payroll_run: PayrollRunRecord) -> int:
    """Remove live employee and line rows for a paid run. Returns deleted employee item count."""
    deleted_count, _ = payroll_run.employee_items.all().delete()
    return deleted_count


def restore_payroll_live_rows_from_snapshot(payroll_run: PayrollRunRecord, *, actor=None) -> int:
    """Recreate employee items and line items from paid_table_snapshot. Returns restored count."""
    if payroll_run.employee_items.exists():
        return payroll_run.employee_items.count()

    snapshot = payroll_run.paid_table_snapshot or {}
    if not snapshot_has_rebuild_payload(snapshot):
        raise ValueError(
            "Cannot revert paid payroll run: paid_table_snapshot is missing employee_items rebuild payload. "
            "Run backfill_disbursement_snapshots to upgrade the snapshot first."
        )

    employee_payloads = snapshot.get("employee_items") or []
    restored = 0

    for raw_payload in employee_payloads:
        payload = dict(raw_payload)
        line_payloads = list(payload.pop("line_items", []) or [])
        read_only_keys = {
            "employee_display",
            "payroll_run_period_name",
            "payroll_run_status",
            "payroll_number",
            "pay_period_start",
            "pay_period_end",
            "payment_date",
            "pay_schedule_frequency",
            "line_items",
            "payroll",
        }
        item_fields = {
            key: value
            for key, value in payload.items()
            if key not in read_only_keys and key != "id"
        }
        item_fields["payroll_id"] = payroll_run.id
        item_fields["payment_status"] = PaymentStatus.UNPAID

        for amount_field in (
            "basic_salary",
            "gross_pay",
            "taxable_income",
            "total_tax",
            "total_deductions",
            "total_benefits",
            "total_reimbursements",
            "net_pay",
        ):
            if amount_field in item_fields and item_fields[amount_field] is not None:
                item_fields[amount_field] = Decimal(str(item_fields[amount_field]))

        item_id = payload.get("id")
        employee_item = PayrollEmployeeItem(id=item_id, **item_fields)
        if actor is not None:
            employee_item.created_by = actor
            employee_item.updated_by = actor
        employee_item.save(force_insert=True)

        line_read_only = {"column_key", "created_at", "updated_at"}
        for line_payload in line_payloads:
            line_fields = {
                key: value
                for key, value in line_payload.items()
                if key not in line_read_only and key != "id"
            }
            line_fields.pop("payroll_employee_item", None)
            line_fields["payroll_employee_item_id"] = employee_item.id
            if line_fields.get("amount") is not None:
                line_fields["amount"] = Decimal(str(line_fields["amount"]))
            if not line_fields.get("metadata"):
                line_fields["metadata"] = {}

            line_id = line_payload.get("id")
            line = PayrollLineItem(id=line_id, **line_fields)
            if actor is not None:
                line.created_by = actor
                line.updated_by = actor
            line.save(force_insert=True)

        restored += 1

    return restored


def purge_paid_live_rows_if_enabled(payroll_run: PayrollRunRecord) -> int:
    if payroll_run.status != PayrollStatus.PAID or not delete_paid_live_rows_enabled():
        return 0
    return delete_paid_live_rows(payroll_run)
