"""Academic year rollover orchestration.

This module powers a wizard-like flow with two phases:
1) preview - validates target year data and reports readiness blockers
2) apply   - creates target year and clones configured defaults
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.db.models import Sum

from academics.models import AcademicYear, MarkingPeriod, Semester
from common.status import EnrollmentStatus, YearEndOutcome
from finance.models import PaymentInstallment
from grading.gradebook_initializer import initialize_gradebooks_for_academic_year
from grading.models import Grade
from students.models import Enrollment, StudentEnrollmentBill


@dataclass
class RolloverOptions:
    clone_semesters: bool = True
    clone_marking_periods: bool = True
    clone_installments: bool = True
    clone_fee_rates: bool = True
    clone_accounting_installment_plans: bool = True
    carry_forward_balances: bool = True
    initialize_gradebooks: bool = False
    set_as_current: bool = False
    close_current_year: bool = True
    require_ready: bool = True


def _parse_date(value: Any, field_name: str) -> date:
    if isinstance(value, date):
        return value
    if not value:
        raise ValueError(f"{field_name} is required.")
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"{field_name} must use YYYY-MM-DD format.") from exc


def _load_options(raw: dict[str, Any] | None) -> RolloverOptions:
    raw = raw or {}
    return RolloverOptions(
        clone_semesters=bool(raw.get("clone_semesters", True)),
        clone_marking_periods=bool(raw.get("clone_marking_periods", True)),
        clone_installments=bool(raw.get("clone_installments", True)),
        clone_fee_rates=bool(raw.get("clone_fee_rates", True)),
        clone_accounting_installment_plans=bool(
            raw.get("clone_accounting_installment_plans", True)
        ),
        carry_forward_balances=bool(raw.get("carry_forward_balances", True)),
        initialize_gradebooks=bool(raw.get("initialize_gradebooks", False)),
        set_as_current=bool(raw.get("set_as_current", False)),
        close_current_year=bool(raw.get("close_current_year", True)),
        require_ready=bool(raw.get("require_ready", True)),
    )


def _validate_target_dates(
    source_year: AcademicYear,
    start_date: date,
    end_date: date,
) -> None:
    if start_date >= end_date:
        raise ValueError("start_date must be before end_date.")

    duration = (end_date - start_date).days
    if duration < 30:
        raise ValueError("Academic year must be at least 30 days.")
    if duration > 365:
        raise ValueError("Academic year cannot exceed 365 days.")

    overlap = AcademicYear.objects.filter(
        year_type=AcademicYear.YearType.REGULAR,
        start_date__lt=end_date,
        end_date__gt=start_date,
    )
    if source_year.id:
        overlap = overlap.exclude(id=source_year.id)
    if overlap.exists():
        raise ValueError("Target dates overlap an existing academic year.")


def _build_readiness(source_year: AcademicYear) -> dict[str, Any]:
    from accounting.models import AccountingStudentBill
    from settings.models import GradingSettings

    enrollments = Enrollment.objects.filter(academic_year=source_year)
    open_enrollment_count = enrollments.filter(
        status__in=[EnrollmentStatus.PENDING, EnrollmentStatus.ENROLLED]
    ).count()
    completed_missing_outcome = enrollments.filter(
        status=EnrollmentStatus.COMPLETED,
        year_end_outcome__isnull=True,
    ).count()
    promoted_missing_next_grade = enrollments.filter(
        status=EnrollmentStatus.COMPLETED,
        year_end_outcome=YearEndOutcome.PROMOTED,
        next_grade_level__isnull=True,
    ).count()

    grade_settings = GradingSettings.objects.first()
    require_approved = bool(
        grade_settings.year_closure_require_approved_grades
    ) if grade_settings else True

    unapproved_grade_count = Grade.objects.filter(
        academic_year=source_year,
        score__isnull=False,
    ).exclude(status=Grade.Status.APPROVED).count()

    unpaid_bills = AccountingStudentBill.objects.filter(
        academic_year=source_year,
        outstanding_amount__gt=0,
    ).exclude(status=AccountingStudentBill.BillStatus.CANCELLED)
    unpaid_bill_count = unpaid_bills.count()
    unpaid_total = unpaid_bills.aggregate(total=Sum("outstanding_amount"))["total"] or Decimal("0")

    checks = [
        {
            "key": "open_enrollments",
            "label": "Open enrollments",
            "ok": open_enrollment_count == 0,
            "value": open_enrollment_count,
            "detail": "All students should have year-end outcomes before rollover.",
            "blocking": True,
        },
        {
            "key": "completed_missing_outcome",
            "label": "Completed enrollments missing outcome",
            "ok": completed_missing_outcome == 0,
            "value": completed_missing_outcome,
            "detail": "Completed rows must be marked promoted, repeated, graduated, transferred, or withdrawn.",
            "blocking": True,
        },
        {
            "key": "promoted_missing_next_grade",
            "label": "Promoted rows missing next grade",
            "ok": promoted_missing_next_grade == 0,
            "value": promoted_missing_next_grade,
            "detail": "Promoted rows should define next_grade_level.",
            "blocking": True,
        },
        {
            "key": "unapproved_grades",
            "label": "Unapproved grades",
            "ok": (not require_approved) or unapproved_grade_count == 0,
            "value": unapproved_grade_count,
            "detail": "Only blocking when grading settings require approved grades.",
            "blocking": bool(require_approved),
        },
        {
            "key": "unpaid_bills",
            "label": "Unpaid student bills",
            "ok": True,
            "value": unpaid_bill_count,
            "detail": f"Outstanding total: {unpaid_total}",
            "blocking": False,
        },
    ]

    blocking_issues = [
        {
            "key": check["key"],
            "label": check["label"],
            "value": check["value"],
            "detail": check["detail"],
        }
        for check in checks
        if check["blocking"] and not check["ok"]
    ]

    return {
        "is_ready": len(blocking_issues) == 0,
        "checks": checks,
        "blocking_issues": blocking_issues,
        "outstanding_balance_total": str(unpaid_total),
    }


def _build_activation_plan(options: RolloverOptions) -> dict[str, Any]:
    current_year = AcademicYear.objects.filter(
        current=True,
        year_type=AcademicYear.YearType.REGULAR,
    ).first()

    if not options.set_as_current:
        summary = "New year will not be set as current."
    elif not current_year:
        summary = "New year will be set as current. No current active year was found to close or unset."
    elif options.close_current_year:
        summary = "Current active year will be marked inactive, and the new year will be set as current."
    else:
        summary = "Current active year will only be unset as current, and the new year will be set as current."

    return {
        "set_as_current": options.set_as_current,
        "close_current_year": options.close_current_year,
        "current_year": (
            {
                "id": str(current_year.id),
                "name": current_year.name,
                "start_date": current_year.start_date,
                "end_date": current_year.end_date,
                "status": current_year.status,
                "current": current_year.current,
            }
            if current_year
            else None
        ),
        "summary": summary,
    }


def _clone_semesters_and_marking_periods(
    source_year: AcademicYear,
    target_year: AcademicYear,
    *,
    clone_semesters: bool,
    clone_marking_periods: bool,
    actor,
) -> dict[str, int]:
    if not clone_semesters:
        return {
            "semesters_created": 0,
            "marking_periods_created": 0,
        }

    source_start = source_year.start_date
    target_start = target_year.start_date
    if not source_start or not target_start:
        return {
            "semesters_created": 0,
            "marking_periods_created": 0,
        }

    offset = target_start - source_start
    semester_map: dict[str, Semester] = {}
    semesters_created = 0
    marking_periods_created = 0

    source_semesters = source_year.semesters.filter(active=True).order_by("start_date", "name")
    for source_semester in source_semesters:
        sem_start = source_semester.start_date + offset if source_semester.start_date else None
        sem_end = source_semester.end_date + offset if source_semester.end_date else None
        if not sem_start or not sem_end:
            continue
        target_semester = Semester.objects.create(
            academic_year=target_year,
            name=source_semester.name,
            start_date=sem_start,
            end_date=sem_end,
            created_by=actor,
            updated_by=actor,
        )
        semester_map[str(source_semester.id)] = target_semester
        semesters_created += 1

    if clone_marking_periods:
        source_periods = (
            MarkingPeriod.objects.filter(
                semester__academic_year=source_year,
                active=True,
            )
            .select_related("semester")
            .order_by("start_date", "name")
        )
        for source_period in source_periods:
            mapped_semester = semester_map.get(str(source_period.semester_id))
            if not mapped_semester:
                continue
            MarkingPeriod.objects.create(
                semester=mapped_semester,
                name=source_period.name,
                short_name=source_period.short_name,
                description=source_period.description,
                start_date=source_period.start_date + offset,
                end_date=source_period.end_date + offset,
                created_by=actor,
                updated_by=actor,
            )
            marking_periods_created += 1

    return {
        "semesters_created": semesters_created,
        "marking_periods_created": marking_periods_created,
    }


def _clone_installments(
    source_year: AcademicYear,
    target_year: AcademicYear,
    actor,
) -> int:
    if not source_year.start_date or not target_year.start_date:
        return 0

    offset = target_year.start_date - source_year.start_date
    created = 0
    source_installments = source_year.payment_installments.filter(active=True).order_by("sequence", "due_date")
    for installment in source_installments:
        PaymentInstallment.objects.create(
            academic_year=target_year,
            name=installment.name,
            description=installment.description,
            value=installment.value,
            due_date=installment.due_date + offset,
            sequence=installment.sequence,
            created_by=actor,
            updated_by=actor,
        )
        created += 1
    return created


def _clone_accounting_defaults(
    source_year: AcademicYear,
    target_year: AcademicYear,
    *,
    clone_fee_rates: bool,
    clone_installment_plans: bool,
    actor,
) -> dict[str, int]:
    from accounting.models import (
        AccountingFeeRate,
        AccountingInstallmentLine,
        AccountingInstallmentPlan,
    )

    fee_rates_created = 0
    plans_created = 0
    lines_created = 0

    if clone_fee_rates:
        fee_rates = AccountingFeeRate.objects.filter(academic_year=source_year, active=True)
        for rate in fee_rates:
            AccountingFeeRate.objects.create(
                fee_item=rate.fee_item,
                academic_year=target_year,
                grade_level=rate.grade_level,
                student_category=rate.student_category,
                amount=rate.amount,
                currency=rate.currency,
                created_by=actor,
                updated_by=actor,
            )
            fee_rates_created += 1

    if clone_installment_plans:
        source_plans = AccountingInstallmentPlan.objects.filter(
            academic_year=source_year,
            active=True,
        ).prefetch_related("lines")

        if source_year.start_date and target_year.start_date:
            offset = target_year.start_date - source_year.start_date
        else:
            offset = timedelta(days=0)

        for plan in source_plans:
            new_plan = AccountingInstallmentPlan.objects.create(
                academic_year=target_year,
                name=plan.name,
                description=plan.description,
                is_active=plan.is_active,
                created_by=actor,
                updated_by=actor,
            )
            plans_created += 1

            for line in plan.lines.filter(active=True).order_by("sequence"):
                AccountingInstallmentLine.objects.create(
                    installment_plan=new_plan,
                    sequence=line.sequence,
                    name=line.name,
                    due_date=line.due_date + offset,
                    percentage=line.percentage,
                    grace_days=line.grace_days,
                    created_by=actor,
                    updated_by=actor,
                )
                lines_created += 1

    return {
        "fee_rates_created": fee_rates_created,
        "installment_plans_created": plans_created,
        "installment_plan_lines_created": lines_created,
    }


def _carry_forward_balances(
    source_year: AcademicYear,
    target_year: AcademicYear,
    actor,
) -> dict[str, int]:
    from accounting.models import AccountingStudentBill

    bills = (
        AccountingStudentBill.objects.filter(
            academic_year=source_year,
            outstanding_amount__gt=0,
            enrollment__active=True,
        )
        .exclude(status=AccountingStudentBill.BillStatus.CANCELLED)
        .values("student_id")
        .annotate(total=Sum("outstanding_amount"))
    )

    created = 0
    skipped = 0
    for row in bills:
        student_id = row["student_id"]
        outstanding = row["total"] or Decimal("0")
        target_enrollment = Enrollment.objects.filter(
            student_id=student_id,
            academic_year=target_year,
            active=True,
        ).first()
        if not target_enrollment:
            skipped += 1
            continue

        existing = target_enrollment.student_bills.filter(
            type="other",
            name__iexact=f"Brought Forward ({source_year.name})",
            active=True,
        ).exists()
        if existing:
            continue

        StudentEnrollmentBill.objects.create(
            enrollment=target_enrollment,
            name=f"Brought Forward ({source_year.name})",
            amount=outstanding,
            type="other",
            notes="Auto-created by academic year rollover wizard.",
            created_by=actor,
            updated_by=actor,
        )
        created += 1

    return {
        "brought_forward_bills_created": created,
        "brought_forward_skipped_missing_enrollment": skipped,
    }


def preview_rollover(payload: dict[str, Any]) -> dict[str, Any]:
    source_year_id = payload.get("source_academic_year_id")
    if not source_year_id:
        raise ValueError("source_academic_year_id is required.")

    source_year = AcademicYear.objects.filter(id=source_year_id).first()
    if not source_year:
        raise ValueError("Source academic year not found.")

    target_name = (payload.get("target_name") or "").strip()
    if not target_name:
        raise ValueError("target_name is required.")

    target_start_date = _parse_date(payload.get("target_start_date"), "target_start_date")
    target_end_date = _parse_date(payload.get("target_end_date"), "target_end_date")
    _validate_target_dates(source_year, target_start_date, target_end_date)

    options = _load_options(payload.get("options"))
    readiness = _build_readiness(source_year)
    activation_plan = _build_activation_plan(options)

    semesters_count = source_year.semesters.filter(active=True).count() if options.clone_semesters else 0
    marking_periods_count = (
        MarkingPeriod.objects.filter(semester__academic_year=source_year, active=True).count()
        if options.clone_semesters and options.clone_marking_periods
        else 0
    )
    installment_count = (
        source_year.payment_installments.filter(active=True).count()
        if options.clone_installments
        else 0
    )

    from accounting.models import AccountingFeeRate, AccountingInstallmentPlan

    fee_rate_count = (
        AccountingFeeRate.objects.filter(academic_year=source_year, active=True).count()
        if options.clone_fee_rates
        else 0
    )
    installment_plan_count = (
        AccountingInstallmentPlan.objects.filter(academic_year=source_year, active=True).count()
        if options.clone_accounting_installment_plans
        else 0
    )

    return {
        "source_year": {
            "id": str(source_year.id),
            "name": source_year.name,
            "start_date": source_year.start_date,
            "end_date": source_year.end_date,
        },
        "target_year": {
            "name": target_name,
            "start_date": target_start_date,
            "end_date": target_end_date,
        },
        "options": {
            "clone_semesters": options.clone_semesters,
            "clone_marking_periods": options.clone_marking_periods,
            "clone_installments": options.clone_installments,
            "clone_fee_rates": options.clone_fee_rates,
            "clone_accounting_installment_plans": options.clone_accounting_installment_plans,
            "carry_forward_balances": options.carry_forward_balances,
            "initialize_gradebooks": options.initialize_gradebooks,
            "set_as_current": options.set_as_current,
            "close_current_year": options.close_current_year,
            "require_ready": options.require_ready,
        },
        "activation_plan": activation_plan,
        "readiness": readiness,
        "clone_preview": {
            "semesters": semesters_count,
            "marking_periods": marking_periods_count,
            "payment_installments": installment_count,
            "accounting_fee_rates": fee_rate_count,
            "accounting_installment_plans": installment_plan_count,
        },
    }


def apply_rollover(payload: dict[str, Any], *, actor) -> dict[str, Any]:
    preview = preview_rollover(payload)
    source_year = AcademicYear.objects.get(id=preview["source_year"]["id"])
    target_name = preview["target_year"]["name"]
    target_start = preview["target_year"]["start_date"]
    target_end = preview["target_year"]["end_date"]
    options = _load_options(payload.get("options"))

    if options.require_ready and not preview["readiness"]["is_ready"]:
        raise ValueError("Year rollover blocked by readiness checks.")

    closed_current_years: list[dict[str, str]] = []

    with transaction.atomic():
        if options.set_as_current:
            current_years = AcademicYear.objects.filter(
                current=True,
                year_type=AcademicYear.YearType.REGULAR,
            )
            current_year_list = list(
                current_years.values("id", "name", "status")
            )

            if options.close_current_year:
                current_years.update(current=False, status="inactive")
                closed_current_years = [
                    {
                        "id": str(item["id"]),
                        "name": item["name"] or "",
                        "status": "inactive",
                    }
                    for item in current_year_list
                ]
            else:
                current_years.update(current=False)

        target_year = AcademicYear.objects.create(
            name=target_name,
            start_date=target_start,
            end_date=target_end,
            current=options.set_as_current,
            status="active",
            year_type=AcademicYear.YearType.REGULAR,
            created_by=actor,
            updated_by=actor,
        )

        clone_counts = _clone_semesters_and_marking_periods(
            source_year,
            target_year,
            clone_semesters=options.clone_semesters,
            clone_marking_periods=options.clone_marking_periods,
            actor=actor,
        )

        installments_created = 0
        if options.clone_installments:
            installments_created = _clone_installments(source_year, target_year, actor)

        accounting_counts = _clone_accounting_defaults(
            source_year,
            target_year,
            clone_fee_rates=options.clone_fee_rates,
            clone_installment_plans=options.clone_accounting_installment_plans,
            actor=actor,
        )

        carry_forward_counts = {
            "brought_forward_bills_created": 0,
            "brought_forward_skipped_missing_enrollment": 0,
        }
        if options.carry_forward_balances:
            carry_forward_counts = _carry_forward_balances(
                source_year,
                target_year,
                actor,
            )

    gradebook_result: dict[str, Any] | None = None
    if options.initialize_gradebooks:
        gradebook_result = initialize_gradebooks_for_academic_year(
            academic_year=target_year,
            created_by=actor,
            regenerate=False,
        )

    return {
        "academic_year": {
            "id": str(target_year.id),
            "name": target_year.name,
            "start_date": target_year.start_date,
            "end_date": target_year.end_date,
            "current": target_year.current,
            "status": target_year.status,
        },
        "summary": {
            **clone_counts,
            "payment_installments_created": installments_created,
            **accounting_counts,
            **carry_forward_counts,
            "closed_current_years": closed_current_years,
        },
        "activation_result": {
            "set_as_current": options.set_as_current,
            "close_current_year": options.close_current_year,
            "closed_current_year_count": len(closed_current_years),
        },
        "readiness": preview["readiness"],
        "gradebook_initialization": gradebook_result,
    }
