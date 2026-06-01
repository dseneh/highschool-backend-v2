"""Helpers for reading payroll run data from paid_table_snapshot when live rows are deleted."""

from __future__ import annotations

from decimal import Decimal

from payroll_v2.enums import PayrollStatus


def paid_snapshot_rows(run) -> list[dict]:
    if run.status != PayrollStatus.PAID:
        return []
    snapshot = getattr(run, "paid_table_snapshot", None) or {}
    return list(snapshot.get("rows") or [])


def paid_run_employee_count(run) -> int:
    snapshot = getattr(run, "paid_table_snapshot", None) or {}
    totals = snapshot.get("totals") or {}
    line_count = totals.get("line_count")
    if line_count is not None:
        return int(line_count)
    rows = paid_snapshot_rows(run)
    if rows:
        return len(rows)
    return run.employee_items.count()


def _decimal(value) -> Decimal:
    if value is None:
        return Decimal("0.00")
    return Decimal(str(value))


def summarize_paid_snapshot_rows(rows: list[dict]) -> dict:
    gross = sum((_decimal(row.get("gross_pay")) for row in rows), Decimal("0.00"))
    tax = sum((_decimal(row.get("total_tax")) for row in rows), Decimal("0.00"))
    deductions = sum((_decimal(row.get("total_deductions")) for row in rows), Decimal("0.00"))
    reimbursements = sum((_decimal(row.get("total_reimbursements")) for row in rows), Decimal("0.00"))
    take_home = sum((_decimal(row.get("net_pay")) for row in rows), Decimal("0.00"))
    return {
        "employee_count": len(rows),
        "gross": gross,
        "tax": tax,
        "deductions": deductions,
        "reimbursements": reimbursements,
        "take_home": take_home,
    }


def summarize_run_employees(run) -> dict:
    rows = paid_snapshot_rows(run)
    if rows:
        return summarize_paid_snapshot_rows(rows)

    items = run.employee_items.all()
    gross = sum((item.gross_pay for item in items), Decimal("0.00"))
    tax = sum((item.total_tax for item in items), Decimal("0.00"))
    deductions = sum((item.total_deductions for item in items), Decimal("0.00"))
    reimbursements = sum((item.total_reimbursements for item in items), Decimal("0.00"))
    take_home = sum((item.net_pay for item in items), Decimal("0.00"))
    return {
        "employee_count": items.count(),
        "gross": gross,
        "tax": tax,
        "deductions": deductions,
        "reimbursements": reimbursements,
        "take_home": take_home,
    }
