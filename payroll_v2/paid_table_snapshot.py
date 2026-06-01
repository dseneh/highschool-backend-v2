"""Build frozen payroll run table snapshot at mark-paid time."""

from __future__ import annotations

from django.utils import timezone

from common.json_utils import make_json_safe
from payroll_v2.enums import PaymentStatus, PayrollStatus
from payroll_v2.models import PayrollRunRecord


def _snapshot_populated(snapshot: dict | None) -> bool:
    return bool(snapshot and (snapshot.get("rows") or snapshot.get("columns")))


def snapshot_has_rebuild_payload(snapshot: dict | None) -> bool:
    """True when snapshot can restore live payroll rows after deletion."""
    return bool(snapshot and snapshot.get("employee_items"))


def build_payroll_paid_table_snapshot(payroll_run: PayrollRunRecord) -> dict:
    from payroll_v2.serializers import PayrollEmployeeItemSerializer, PayrollRunDetailSerializer

    run = (
        PayrollRunRecord.objects.filter(pk=payroll_run.pk)
        .prefetch_related(
            "employee_items__line_items",
            "employee_items__employee",
            "employee_items__employee__department",
            "employee_items__employee__position",
        )
        .first()
    )
    if run is None:
        run = payroll_run

    serializer = PayrollRunDetailSerializer(run, context={})
    columns = serializer.get_columns(run)
    rows = serializer.get_rows(run)
    totals = serializer.get_totals(run)
    employee_items = PayrollEmployeeItemSerializer(
        run.employee_items.all(),
        many=True,
    ).data

    for row in rows:
        row["payment_status"] = PaymentStatus.PAID

    totals = dict(totals or {})
    totals["line_count"] = len(rows)

    return make_json_safe(
        {
            "schema_version": 2,
            "captured_at": timezone.now().isoformat(),
            "columns": columns,
            "rows": rows,
            "totals": totals,
            "employee_items": employee_items,
        }
    )


def capture_payroll_paid_table_snapshot(payroll_run: PayrollRunRecord) -> PayrollRunRecord:
    if payroll_run.status != PayrollStatus.PAID:
        return payroll_run
    existing = payroll_run.paid_table_snapshot or {}
    if _snapshot_populated(existing) and snapshot_has_rebuild_payload(existing):
        return payroll_run
    payroll_run.paid_table_snapshot = build_payroll_paid_table_snapshot(payroll_run)
    payroll_run.save(update_fields=["paid_table_snapshot", "updated_at"])
    return payroll_run


def clear_payroll_paid_table_snapshot(payroll_run: PayrollRunRecord) -> None:
    if not payroll_run.paid_table_snapshot:
        return
    payroll_run.paid_table_snapshot = {}
    payroll_run.save(update_fields=["paid_table_snapshot", "updated_at"])
