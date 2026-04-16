from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
import re
from typing import Iterable

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from accounting.models import (
    AccountingConcession,
    AccountingCurrency,
    AccountingFeeItem,
    AccountingStudentBill,
    AccountingStudentBillLine,
)
from students.models import Enrollment, StudentEnrollmentBill


@dataclass
class BillingLineInput:
    name: str
    amount: Decimal
    category: str
    description: str = ""


def _to_decimal(value: Decimal | int | float | str | None) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def _round_money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


def _normalize_student_category(enrolled_as: str | None) -> str:
    value = (enrolled_as or "").strip().lower()
    if value in {"old", "returning"}:
        return "returning"
    if value in {"transfer", "transferred"}:
        return "transferred"
    return "new"


def _safe_code_from_name(name: str, max_length: int = 50) -> str:
    base = re.sub(r"[^a-zA-Z0-9]+", "_", name.strip().upper()).strip("_")
    base = base[:max_length] if base else "FEE_ITEM"
    code = base
    suffix = 1
    while AccountingFeeItem.objects.filter(code=code).exists():
        suffix_str = f"_{suffix}"
        code = f"{base[: max_length - len(suffix_str)]}{suffix_str}"
        suffix += 1
    return code


def _resolve_base_currency() -> AccountingCurrency:
    currency = AccountingCurrency.objects.filter(is_base_currency=True, is_active=True).first()
    if currency is None:
        currency = AccountingCurrency.objects.filter(is_active=True).order_by("-is_base_currency", "code").first()
    if currency is None:
        raise ValueError("No active accounting currency found. Configure currency before creating bills.")
    return currency


def _get_or_create_fee_item(name: str, category: str, description: str = "") -> AccountingFeeItem:
    existing = AccountingFeeItem.objects.filter(name=name).first()
    if existing:
        return existing

    return AccountingFeeItem.objects.create(
        name=name,
        code=_safe_code_from_name(name),
        category=category,
        description=description or None,
        is_active=True,
    )


def build_billing_lines_for_enrollment(enrollment: Enrollment) -> list[BillingLineInput]:
    student_category = _normalize_student_category(getattr(enrollment, "enrolled_as", None))

    lines: list[BillingLineInput] = []

    all_section_fees = enrollment.section.section_fees.select_related("general_fee").filter(active=True)
    for section_fee in all_section_fees:
        target_type = (section_fee.general_fee.student_target or "").strip().lower()
        if target_type in {"", student_category}:
            lines.append(
                BillingLineInput(
                    name=section_fee.general_fee.name,
                    amount=_to_decimal(section_fee.amount),
                    category=AccountingFeeItem.FeeCategory.GENERAL,
                    description=section_fee.general_fee.description or "",
                )
            )

    tuition_fee = enrollment.grade_level.tuition_fees.filter(targeted_student_type=enrollment.enrolled_as).first()
    if not tuition_fee or tuition_fee.amount is None or _to_decimal(tuition_fee.amount) <= 0:
        raise ValueError(
            f"No {str(enrollment.enrolled_as).upper()} tuition fee found for grade level. Cannot create student bill."
        )

    lines.append(
        BillingLineInput(
            name="Tuition",
            amount=_to_decimal(tuition_fee.amount),
            category=AccountingFeeItem.FeeCategory.TUITION,
            description="Tuition",
        )
    )

    return lines


@transaction.atomic
def create_or_update_accounting_bill_for_enrollment(
    enrollment: Enrollment,
    created_by=None,
    preserve_existing_lines: bool = False,
) -> AccountingStudentBill:
    currency = _resolve_base_currency()
    bill_lines = build_billing_lines_for_enrollment(enrollment)

    gross_amount = sum((line.amount for line in bill_lines), Decimal("0"))
    bill_date = getattr(enrollment, "date_enrolled", None) or timezone.now().date()
    due_date = getattr(enrollment.academic_year, "end_date", None) or bill_date

    bill = AccountingStudentBill.objects.filter(
        enrollment=enrollment,
        academic_year=enrollment.academic_year,
        student=enrollment.student,
    ).first()

    if bill is None:
        bill = AccountingStudentBill.objects.create(
            enrollment=enrollment,
            academic_year=enrollment.academic_year,
            student=enrollment.student,
            grade_level=enrollment.grade_level,
            bill_date=bill_date,
            due_date=due_date,
            gross_amount=gross_amount,
            concession_amount=Decimal("0"),
            net_amount=gross_amount,
            paid_amount=Decimal("0"),
            outstanding_amount=gross_amount,
            currency=currency,
            status=AccountingStudentBill.BillStatus.ISSUED,
            notes="Auto-generated from enrollment",
            created_by=created_by,
            updated_by=created_by,
        )
    else:
        bill.gross_amount = gross_amount
        bill.net_amount = max(Decimal("0"), gross_amount - _to_decimal(bill.concession_amount))
        bill.outstanding_amount = max(Decimal("0"), bill.net_amount - _to_decimal(bill.paid_amount))
        bill.bill_date = bill_date
        bill.due_date = due_date
        bill.grade_level = enrollment.grade_level
        bill.currency = currency
        bill.updated_by = created_by or bill.updated_by
        bill.save(
            update_fields=[
                "gross_amount",
                "net_amount",
                "outstanding_amount",
                "bill_date",
                "due_date",
                "grade_level",
                "currency",
                "updated_by",
                "updated_at",
            ]
        )

    if not preserve_existing_lines:
        bill.lines.all().delete()

    for idx, line in enumerate(bill_lines, start=1):
        fee_item = _get_or_create_fee_item(
            name=line.name,
            category=line.category,
            description=line.description,
        )
        AccountingStudentBillLine.objects.create(
            student_bill=bill,
            fee_item=fee_item,
            description=line.description or line.name,
            quantity=Decimal("1"),
            unit_amount=line.amount,
            line_amount=line.amount,
            currency=currency,
            line_sequence=idx,
            created_by=created_by,
            updated_by=created_by,
        )

    return bill


def _group_legacy_rows(rows: Iterable[StudentEnrollmentBill]) -> dict[str, list[StudentEnrollmentBill]]:
    grouped: dict[str, list[StudentEnrollmentBill]] = {}
    for row in rows:
        key = str(row.enrollment_id)
        grouped.setdefault(key, []).append(row)
    return grouped


@transaction.atomic
def sync_accounting_bill_concession_totals(student, academic_year) -> int:
    """
    Recompute concession/net/outstanding totals for all accounting bills in a student-year.

    Returns:
        int: Number of bills updated.
    """
    bills = list(
        AccountingStudentBill.objects.filter(
            student=student,
            academic_year=academic_year,
        ).order_by("bill_date", "created_at")
    )
    if not bills:
        return 0

    total_concession = _to_decimal(
        AccountingConcession.objects.filter(
            student=student,
            academic_year=academic_year,
            is_active=True,
            active=True,
        ).aggregate(total=Sum("computed_amount"))["total"]
    )

    total_gross = sum((_to_decimal(bill.gross_amount) for bill in bills), Decimal("0"))
    if total_gross <= 0:
        total_concession = Decimal("0")
    else:
        total_concession = min(total_concession, total_gross)

    remaining_concession = _round_money(total_concession)
    updated_count = 0

    for idx, bill in enumerate(bills):
        gross_amount = _to_decimal(bill.gross_amount)
        paid_amount = _to_decimal(bill.paid_amount)

        if gross_amount <= 0:
            allocated_concession = Decimal("0")
        elif idx == len(bills) - 1:
            allocated_concession = min(gross_amount, remaining_concession)
        else:
            proportional = (gross_amount / total_gross) * total_concession if total_gross > 0 else Decimal("0")
            allocated_concession = min(gross_amount, _round_money(proportional), remaining_concession)

        remaining_concession = max(Decimal("0"), _round_money(remaining_concession - allocated_concession))

        net_amount = max(Decimal("0"), gross_amount - allocated_concession)
        outstanding_amount = max(Decimal("0"), net_amount - paid_amount)

        bill.concession_amount = _round_money(allocated_concession)
        bill.net_amount = _round_money(net_amount)
        bill.outstanding_amount = _round_money(outstanding_amount)
        bill.save(update_fields=["concession_amount", "net_amount", "outstanding_amount", "updated_at"])
        updated_count += 1

    return updated_count


@transaction.atomic
def migrate_legacy_student_bills(
    enrollment_ids: Iterable[str] | None = None,
    dry_run: bool = False,
) -> dict[str, int]:
    queryset = StudentEnrollmentBill.objects.select_related(
        "enrollment",
        "enrollment__student",
        "enrollment__academic_year",
        "enrollment__grade_level",
    ).order_by("enrollment_id", "created_at")

    if enrollment_ids:
        queryset = queryset.filter(enrollment_id__in=list(enrollment_ids))

    rows = list(queryset)
    grouped = _group_legacy_rows(rows)
    currency = _resolve_base_currency()

    counters = {
        "legacy_rows": len(rows),
        "enrollments": len(grouped),
        "created_bills": 0,
        "updated_bills": 0,
        "created_lines": 0,
    }

    for grouped_rows in grouped.values():
        enrollment = grouped_rows[0].enrollment
        gross_amount = sum((_to_decimal(row.amount) for row in grouped_rows), Decimal("0"))
        bill_date = getattr(enrollment, "date_enrolled", None) or timezone.now().date()
        due_date = getattr(enrollment.academic_year, "end_date", None) or bill_date

        bill = AccountingStudentBill.objects.filter(
            enrollment=enrollment,
            academic_year=enrollment.academic_year,
            student=enrollment.student,
        ).first()

        if bill is None:
            counters["created_bills"] += 1
            if not dry_run:
                bill = AccountingStudentBill.objects.create(
                    enrollment=enrollment,
                    academic_year=enrollment.academic_year,
                    student=enrollment.student,
                    grade_level=enrollment.grade_level,
                    bill_date=bill_date,
                    due_date=due_date,
                    gross_amount=gross_amount,
                    concession_amount=Decimal("0"),
                    net_amount=gross_amount,
                    paid_amount=Decimal("0"),
                    outstanding_amount=gross_amount,
                    currency=currency,
                    status=AccountingStudentBill.BillStatus.ISSUED,
                    notes="Migrated from students.StudentEnrollmentBill",
                    created_by=enrollment.created_by,
                    updated_by=enrollment.updated_by,
                )
        else:
            counters["updated_bills"] += 1
            if not dry_run:
                bill.gross_amount = gross_amount
                bill.net_amount = gross_amount
                bill.outstanding_amount = max(Decimal("0"), gross_amount - _to_decimal(bill.paid_amount))
                bill.bill_date = bill_date
                bill.due_date = due_date
                bill.grade_level = enrollment.grade_level
                bill.currency = currency
                bill.notes = bill.notes or "Migrated from students.StudentEnrollmentBill"
                bill.save()
                bill.lines.all().delete()

        for idx, row in enumerate(grouped_rows, start=1):
            counters["created_lines"] += 1
            if dry_run or bill is None:
                continue

            category = (
                AccountingFeeItem.FeeCategory.TUITION
                if (row.type or "").strip().lower() == "tuition"
                else AccountingFeeItem.FeeCategory.GENERAL
            )
            fee_item = _get_or_create_fee_item(
                name=row.name or "Fee",
                category=category,
                description=row.notes or "",
            )
            line_amount = _to_decimal(row.amount)

            AccountingStudentBillLine.objects.create(
                student_bill=bill,
                fee_item=fee_item,
                description=row.notes or (row.name or "Fee"),
                quantity=Decimal("1"),
                unit_amount=line_amount,
                line_amount=line_amount,
                currency=currency,
                line_sequence=idx,
                created_by=row.created_by,
                updated_by=row.updated_by,
            )

    return counters