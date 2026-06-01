"""YTD accumulation from active disbursement records."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from employee_disbursements.enums import DisbursementRecordStatus, DisbursementSourceType
from employee_disbursements.models import EmployeeDisbursementRecord


@dataclass
class DisbursementYtdAccumulator:
    gross: Decimal = Decimal("0.00")
    net: Decimal = Decimal("0.00")
    tax: Decimal = Decimal("0.00")
    deductions: Decimal = Decimal("0.00")
    benefit_type_amounts: dict[str, Decimal] = field(default_factory=lambda: defaultdict(Decimal))
    all_benefits: Decimal = Decimal("0.00")
    line_amounts: dict[str, Decimal] = field(default_factory=lambda: defaultdict(Decimal))


def _parse_amount(value) -> Decimal:
    if value is None or value == "":
        return Decimal("0.00")
    try:
        return Decimal(str(value).replace(",", ""))
    except Exception:
        return Decimal("0.00")


def _accumulate_payroll_snapshot(acc: DisbursementYtdAccumulator, snapshot: dict) -> None:
    acc.gross += _parse_amount(snapshot.get("grossPay") or snapshot.get("periodGross"))
    acc.net += _parse_amount(snapshot.get("netPay") or snapshot.get("periodNet"))
    acc.tax += _parse_amount(snapshot.get("periodTax"))
    acc.deductions += _parse_amount(snapshot.get("periodDeductions"))

    for row in snapshot.get("earnings") or []:
        key = row.get("ytdKey") or f"earning:{(row.get('label') or '').strip().lower()}"
        acc.line_amounts[key] += _parse_amount(row.get("periodAmount") or row.get("amount"))

    for row in (snapshot.get("taxes") or []) + (snapshot.get("deductions") or []):
        key = row.get("ytdKey") or f"tax_deduction:{(row.get('label') or '').strip().lower()}"
        acc.line_amounts[key] += _parse_amount(row.get("periodAmount") or row.get("amount"))


def _accumulate_benefit_snapshot(acc: DisbursementYtdAccumulator, snapshot: dict) -> None:
    amount = _parse_amount(snapshot.get("periodAmountRaw"))
    benefit_name = ((snapshot.get("period") or {}).get("benefitName") or "").strip()
    acc.all_benefits += amount
    if benefit_name:
        acc.benefit_type_amounts[benefit_name] += amount


def active_disbursement_records_for_ytd(
    *,
    employee_id,
    payment_date: date,
    source_type: str | None = None,
    exclude_record_id=None,
):
    year_start = date(payment_date.year, 1, 1)
    qs = EmployeeDisbursementRecord.objects.filter(
        employee_id=employee_id,
        status=DisbursementRecordStatus.ACTIVE,
        payment_date__gte=year_start,
        payment_date__lte=payment_date,
    )
    if source_type:
        qs = qs.filter(source_type=source_type)
    if exclude_record_id:
        qs = qs.exclude(id=exclude_record_id)
    return qs.order_by("payment_date", "paid_at", "created_at")


def build_ytd_from_disbursement_records(
    *,
    employee_id,
    payment_date: date,
    source_type: str | None = None,
) -> DisbursementYtdAccumulator:
    acc = DisbursementYtdAccumulator()
    for record in active_disbursement_records_for_ytd(
        employee_id=employee_id,
        payment_date=payment_date,
        source_type=source_type,
    ):
        snapshot = record.snapshot or {}
        if record.source_type == DisbursementSourceType.PAYROLL:
            _accumulate_payroll_snapshot(acc, snapshot)
        elif record.source_type == DisbursementSourceType.BENEFIT:
            _accumulate_benefit_snapshot(acc, snapshot)
    return acc


def sum_active_benefit_ytd(
    *,
    employee_id,
    payment_date: date,
    benefit_type_name: str,
) -> Decimal:
    acc = build_ytd_from_disbursement_records(
        employee_id=employee_id,
        payment_date=payment_date,
        source_type=DisbursementSourceType.BENEFIT,
    )
    return acc.benefit_type_amounts.get(benefit_type_name, Decimal("0.00"))


def sum_active_all_benefits_ytd(*, employee_id, payment_date: date) -> Decimal:
    acc = build_ytd_from_disbursement_records(
        employee_id=employee_id,
        payment_date=payment_date,
        source_type=DisbursementSourceType.BENEFIT,
    )
    return acc.all_benefits
