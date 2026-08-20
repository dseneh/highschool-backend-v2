from collections import defaultdict
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Case, Count, DecimalField, Exists, F, OuterRef, Q, Sum, Value, When
from django.db.models.functions import Abs, Coalesce
from django.utils import timezone

from academics.models import AcademicYear, GradeLevel, GradeLevelTuitionFee, Section
from accounting.models import (
    AccountingCashTransaction,
    AccountingJournalEntry,
    AccountingJournalLine,
    AccountingStudentBill,
    AccountingStudentBillLine,
    AccountingStudentPaymentAllocation,
)
from finance.models import SectionFee
from payroll_v2.models import EmployeeCompensation
from students.models import Enrollment

from .models import (
    Budget, BudgetLifecycleEvent, BudgetLine, BudgetRevision,
)

ZERO = Decimal("0.00")


def validate_budget_for_submission(budget, require_gl_accounts=False):
    errors = []
    used_accounts = {}
    lines = BudgetLine.objects.filter(section__budget=budget).select_related("gl_account", "section")
    if not lines.exists():
        errors.append("Budget must contain at least one line.")
    for line in lines:
        if require_gl_accounts and not line.gl_account_id:
            errors.append(f"Line '{line.name}' requires a GL account.")
        elif line.gl_account_id and line.section.section_type == "revenue" and line.gl_account.account_type != "income":
            errors.append(f"Revenue line '{line.name}' requires an income GL account.")
        elif line.gl_account_id and line.section.section_type == "expense" and line.gl_account.account_type != "expense":
            errors.append(f"Expense line '{line.name}' requires an expense GL account.")
        elif line.gl_account_id and (not line.gl_account.is_active or line.gl_account.is_header):
            errors.append(f"Line '{line.name}' requires an active posting GL account.")
        if line.gl_account_id:
            if line.gl_account_id in used_accounts:
                errors.append(
                    f"GL account on '{line.name}' is already assigned to '{used_accounts[line.gl_account_id]}'."
                )
            used_accounts[line.gl_account_id] = line.name
        period_total = sum((p.planned_amount for p in line.periods.all()), ZERO)
        if line.periods.exists() and period_total != line.annual_planned_amount:
            errors.append(f"Periods for '{line.name}' must total its annual planned amount.")
    if errors:
        raise ValidationError(errors)


@transaction.atomic
def transition_budget(budget, target, actor, reason=""):
    budget = Budget.objects.select_for_update().get(pk=budget.pk)
    allowed = {
        Budget.Status.DRAFT: {Budget.Status.SUBMITTED},
        Budget.Status.SUBMITTED: {Budget.Status.DRAFT, Budget.Status.APPROVED},
        Budget.Status.APPROVED: {Budget.Status.ACTIVE},
        Budget.Status.ACTIVE: {Budget.Status.CLOSED},
    }
    if target not in allowed.get(budget.status, set()):
        raise ValidationError(f"Cannot transition budget from {budget.status} to {target}.")
    if target in {Budget.Status.SUBMITTED, Budget.Status.APPROVED}:
        validate_budget_for_submission(budget, require_gl_accounts=target == Budget.Status.APPROVED)
    if target == Budget.Status.ACTIVE:
        now = timezone.now()
        for current in Budget.objects.select_for_update().filter(status=Budget.Status.ACTIVE).exclude(pk=budget.pk):
            current.status = Budget.Status.CLOSED
            current.closed_at = now
            current.closed_by = actor
            current.updated_by = actor
            current.save(update_fields=["status", "closed_at", "closed_by", "updated_by", "updated_at"])
            BudgetLifecycleEvent.objects.create(
                budget=current, from_status=Budget.Status.ACTIVE, to_status=Budget.Status.CLOSED,
                event_type="closed_on_activation", actor=actor,
                metadata={"activated_budget_id": str(budget.id)}, created_by=actor, updated_by=actor,
            )

    previous = budget.status
    budget.status = target
    now = timezone.now()
    field = {
        Budget.Status.SUBMITTED: "submitted",
        Budget.Status.APPROVED: "approved",
        Budget.Status.ACTIVE: "activated",
        Budget.Status.CLOSED: "closed",
    }.get(target)
    update_fields = ["status", "updated_at", "updated_by"]
    budget.updated_by = actor
    if field:
        setattr(budget, f"{field}_at", now)
        setattr(budget, f"{field}_by", actor)
        update_fields.extend([f"{field}_at", f"{field}_by"])
    budget.save(update_fields=update_fields)
    BudgetLifecycleEvent.objects.create(
        budget=budget, from_status=previous, to_status=target,
        event_type="rejected" if target == Budget.Status.DRAFT else target,
        actor=actor, reason=reason, created_by=actor, updated_by=actor,
    )
    return budget


@transaction.atomic
def approve_revision(revision, actor):
    revision = BudgetRevision.objects.select_for_update().select_related("budget").get(pk=revision.pk)
    if revision.status != BudgetRevision.Status.DRAFT:
        raise ValidationError("Only draft revisions can be approved.")
    if revision.budget.status not in {Budget.Status.APPROVED, Budget.Status.ACTIVE}:
        raise ValidationError("Revisions can only be approved for approved or active budgets.")
    deltas = list(revision.line_deltas.select_related("budget_line"))
    if not deltas:
        raise ValidationError("A revision must contain at least one line delta.")
    for delta in deltas:
        prior_delta = delta.budget_line.revision_deltas.filter(
            revision__status=BudgetRevision.Status.APPROVED
        ).aggregate(total=Coalesce(
            Sum("amount_delta"), Value(ZERO),
            output_field=DecimalField(max_digits=18, decimal_places=2),
        ))["total"]
        if delta.budget_line.annual_planned_amount + prior_delta + delta.amount_delta < ZERO:
            raise ValidationError(f"Revision would make '{delta.budget_line.name}' negative.")
    revision.status = BudgetRevision.Status.APPROVED
    revision.approved_at = timezone.now()
    revision.approved_by = actor
    revision.updated_by = actor
    revision.save(update_fields=["status", "approved_at", "approved_by", "updated_by", "updated_at"])
    revision.budget.version = F("version") + 1
    revision.budget.updated_by = actor
    revision.budget.save(update_fields=["version", "updated_by", "updated_at"])
    BudgetLifecycleEvent.objects.create(
        budget=revision.budget, from_status=revision.budget.status, to_status=revision.budget.status,
        event_type="revision_approved", actor=actor, metadata={"revision_id": str(revision.id)},
        created_by=actor, updated_by=actor,
    )
    return revision


def effective_planned_amounts(budget, include_periods=True):
    approved_delta = Coalesce(
        Sum("revision_deltas__amount_delta", filter=Q(revision_deltas__revision__status=BudgetRevision.Status.APPROVED)),
        Value(ZERO), output_field=DecimalField(max_digits=18, decimal_places=2),
    )
    queryset = BudgetLine.objects.filter(section__budget=budget).select_related(
        "section", "gl_account"
    ).annotate(approved_delta=approved_delta)
    return queryset.prefetch_related("periods") if include_periods else queryset


def actuals_by_account_for_year(academic_year, start_date=None, end_date=None, account_ids=None):
    start = start_date or academic_year.start_date
    end = end_date or academic_year.end_date
    signed_base = Case(
        When(debit_amount__gt=0, then=F("base_amount")),
        When(credit_amount__gt=0, then=-F("base_amount")),
        default=Value(ZERO), output_field=DecimalField(max_digits=18, decimal_places=2),
    )
    queryset = AccountingJournalLine.objects.filter(
        journal_entry__status=AccountingJournalEntry.EntryStatus.POSTED,
        journal_entry__academic_year=academic_year,
        journal_entry__posting_date__range=(start, end),
    )
    if account_ids is not None:
        queryset = queryset.filter(ledger_account_id__in=account_ids)
    rows = (
        queryset
        .values("ledger_account_id")
        .annotate(net_debit=Coalesce(Sum(signed_base), Value(ZERO), output_field=DecimalField(max_digits=18, decimal_places=2)))
    )
    return {row["ledger_account_id"]: row["net_debit"] for row in rows}


def actuals_by_account(budget, start_date=None, end_date=None):
    return actuals_by_account_for_year(
        budget.academic_year, start_date, end_date
    )


def budget_summary_payload(budget, start_date=None, end_date=None, report_type="budget-summary"):
    actuals = actuals_by_account(budget, start_date, end_date)
    results = []
    totals = defaultdict(lambda: ZERO)
    period_start = start_date or budget.academic_year.start_date
    period_end = end_date or budget.academic_year.end_date
    full_year = (
        period_start == budget.academic_year.start_date
        and period_end == budget.academic_year.end_date
    )
    for line in effective_planned_amounts(budget):
        planned = line.annual_planned_amount + line.approved_delta
        periods = list(line.periods.all())
        if not full_year and periods:
            period_plan = ZERO
            for period in periods:
                overlap_start = max(period.start_date, period_start)
                overlap_end = min(period.end_date, period_end)
                if overlap_start > overlap_end:
                    continue
                overlap_days = Decimal((overlap_end - overlap_start).days + 1)
                period_days = Decimal((period.end_date - period.start_date).days + 1)
                period_plan += period.planned_amount * overlap_days / period_days
            period_plan = period_plan.quantize(Decimal("0.01"))
            revision_share = (
                line.approved_delta * period_plan / line.annual_planned_amount
                if line.annual_planned_amount else ZERO
            )
            planned = period_plan + revision_share
        net_debit = actuals.get(line.gl_account_id, ZERO) if line.gl_account_id else ZERO
        actual = -net_debit if line.section.section_type == "revenue" else net_debit
        variance = actual - planned if line.section.section_type == "revenue" else planned - actual
        variance_pct = (variance / planned * Decimal("100")) if planned else None
        row = {
            "line_id": str(line.id), "section": line.section.name,
            "section_type": line.section.section_type, "line": line.name,
            "source_type": line.source_type,
            "gl_account_code": line.gl_account.code if line.gl_account else None,
            "planned_amount": planned, "actual_amount": actual,
            "variance_amount": variance, "variance_percentage": variance_pct,
        }
        results.append(row)
        totals[f"planned_{line.section.section_type}"] += planned
        totals[f"actual_{line.section.section_type}"] += actual
    summary = {
        "planned_revenue": totals["planned_revenue"], "actual_revenue": totals["actual_revenue"],
        "planned_expense": totals["planned_expense"], "actual_expense": totals["actual_expense"],
        "planned_surplus": totals["planned_revenue"] - totals["planned_expense"],
        "actual_surplus": totals["actual_revenue"] - totals["actual_expense"],
    }
    summary.update({
        "revenue_variance": summary["actual_revenue"] - summary["planned_revenue"],
        "expense_variance": summary["planned_expense"] - summary["actual_expense"],
        "surplus_variance": summary["actual_surplus"] - summary["planned_surplus"],
        "revenue_performance_percentage": (
            summary["actual_revenue"] / summary["planned_revenue"] * Decimal("100")
            if summary["planned_revenue"] else None
        ),
        "expense_utilization_percentage": (
            summary["actual_expense"] / summary["planned_expense"] * Decimal("100")
            if summary["planned_expense"] else None
        ),
        "planned_revenue_expense_ratio": (
            summary["planned_revenue"] / summary["planned_expense"]
            if summary["planned_expense"] else None
        ),
        "actual_revenue_expense_ratio": (
            summary["actual_revenue"] / summary["actual_expense"]
            if summary["actual_expense"] else None
        ),
    })
    return {
        "summary": summary, "results": results, "count": len(results),
        "context": {
            "report_type": report_type, "budget_id": str(budget.id), "budget_name": budget.name,
            "academic_year_id": str(budget.academic_year_id), "academic_year": str(budget.academic_year),
            "currency": budget.base_currency.code,
            "start_date": (start_date or budget.academic_year.start_date).isoformat(),
            "end_date": (end_date or budget.academic_year.end_date).isoformat(),
        },
        "definitions": {
            "actual": "POSTED journal-line base amounts only; credits are revenue and debits are expense.",
            "variance": "Revenue: actual minus plan. Expense: plan minus actual.",
            "planned": "Original line amount plus approved revision deltas.",
        },
    }


def prior_year_baseline(budget):
    previous_year = AcademicYear.objects.filter(
        year_type=AcademicYear.YearType.REGULAR,
        end_date__lt=budget.academic_year.start_date,
    ).order_by("-end_date", "-start_date").first()
    base_context = {
        "report_type": "prior-year-baseline",
        "budget_id": str(budget.id),
        "academic_year_id": str(budget.academic_year_id),
        "currency": budget.base_currency.code,
    }
    if not previous_year:
        return {
            "summary": {}, "results": [], "count": 0,
            "enrollment_actuals": [], "context": base_context,
            "definitions": {"baseline": "No preceding regular academic year exists."},
        }

    lines = list(effective_planned_amounts(budget, include_periods=False))
    account_ids = {line.gl_account_id for line in lines if line.gl_account_id}
    prior_actuals = actuals_by_account_for_year(
        previous_year, account_ids=account_ids
    )
    results = []
    totals = defaultdict(lambda: ZERO)
    for line in lines:
        current_plan = line.annual_planned_amount + line.approved_delta
        net_debit = prior_actuals.get(line.gl_account_id, ZERO) if line.gl_account_id else ZERO
        prior_actual = -net_debit if line.section.section_type == "revenue" else net_debit
        results.append({
            "line_id": str(line.id),
            "section": line.section.name,
            "section_type": line.section.section_type,
            "line": line.name,
            "gl_account_code": line.gl_account.code if line.gl_account else None,
            "current_planned_amount": current_plan,
            "prior_actual_amount": prior_actual,
            "change_from_prior_actual": current_plan - prior_actual,
        })
        totals[f"current_planned_{line.section.section_type}"] += current_plan
        totals[f"prior_actual_{line.section.section_type}"] += prior_actual

    enrollment_rows = list(
        Enrollment.objects.filter(
            academic_year=previous_year,
            status__in=["enrolled", "completed"],
        )
        .values("grade_level_id", "grade_level__name")
        .annotate(actual_students=Count("id"))
        .order_by("grade_level__level", "grade_level__name")
    )
    enrollment_actuals = [
        {
            "grade_level_id": str(row["grade_level_id"]),
            "grade_level": row["grade_level__name"],
            "actual_students": row["actual_students"],
        }
        for row in enrollment_rows
    ]
    summary = {
        "current_planned_revenue": totals["current_planned_revenue"],
        "prior_actual_revenue": totals["prior_actual_revenue"],
        "current_planned_expense": totals["current_planned_expense"],
        "prior_actual_expense": totals["prior_actual_expense"],
        "prior_actual_surplus": totals["prior_actual_revenue"] - totals["prior_actual_expense"],
        "prior_enrollment_actual": sum(row["actual_students"] for row in enrollment_actuals),
    }
    return {
        "summary": summary,
        "results": results,
        "count": len(results),
        "enrollment_actuals": enrollment_actuals,
        "context": {
            **base_context,
            "prior_academic_year_id": str(previous_year.id),
            "prior_academic_year": str(previous_year),
            "start_date": previous_year.start_date.isoformat(),
            "end_date": previous_year.end_date.isoformat(),
        },
        "definitions": {
            "baseline": "Prior-year POSTED journal base amounts for the current budget's mapped GL accounts.",
            "prior_budget": "A prior Budget is optional and is not copied or used to select accounts.",
            "enrollment_actuals": "Enrolled or completed enrollments in the immediately preceding regular academic year, grouped by grade.",
        },
    }


def _normalize_budget_student_category(value):
    normalized = (value or "").strip().lower()
    if normalized in {"", "old", "returning"}:
        return "returning"
    if normalized in {"transfer", "transferred"}:
        return "transferred"
    return "new"


def projection_payload(budget):
    assumptions = list(budget.enrollment_assumptions.select_related("grade_level"))
    active_grades = list(GradeLevel.objects.filter(active=True).order_by("level", "name"))
    planning_rows = [
        {
            "grade_level": assumption.grade_level,
            "student_category": assumption.student_category,
            "estimated_students": assumption.estimated_students,
        }
        for assumption in assumptions
    ]
    assumption_grade_ids = {assumption.grade_level_id for assumption in assumptions}
    planning_rows.extend(
        {
            "grade_level": grade,
            "student_category": "",
            "estimated_students": 0,
        }
        for grade in active_grades
        if grade.id not in assumption_grade_ids
    )
    grade_ids = {row["grade_level"].id for row in planning_rows}
    tuition_rows = list(
        GradeLevelTuitionFee.objects.filter(
            grade_level_id__in=grade_ids,
            active=True,
        ).order_by("grade_level_id", "targeted_student_type", "created_at")
    )
    active_sections = list(
        Section.objects.filter(
            grade_level_id__in=grade_ids,
            active=True,
        ).values("id", "grade_level_id")
    )
    section_fees = list(
        SectionFee.objects.filter(
            section__grade_level_id__in=grade_ids,
            section__active=True,
            active=True,
            general_fee__active=True,
        ).select_related("section", "general_fee")
    )
    tuition_by_grade_category = defaultdict(list)
    for tuition in tuition_rows:
        tuition_by_grade_category[
            (tuition.grade_level_id, _normalize_budget_student_category(tuition.targeted_student_type))
        ].append(tuition)
    section_ids_by_grade = defaultdict(list)
    for section in active_sections:
        section_ids_by_grade[section["grade_level_id"]].append(section["id"])
    fees_by_section = defaultdict(list)
    for section_fee in section_fees:
        fees_by_section[section_fee.section_id].append(section_fee)

    results = []
    student_fee_total = ZERO
    tuition_total = ZERO
    enrollment_rows = list(
        Enrollment.objects.filter(
            academic_year=budget.academic_year,
            status__in=["enrolled", "completed"],
        )
        .values("grade_level_id", "enrolled_as")
        .annotate(actual_students=Count("id"))
    )
    grade_totals = defaultdict(int)
    category_totals = defaultdict(int)
    for row in enrollment_rows:
        grade_totals[row["grade_level_id"]] += row["actual_students"]
        category_totals[(row["grade_level_id"], row["enrolled_as"])] += row["actual_students"]
    for planning_row in planning_rows:
        grade_level = planning_row["grade_level"]
        raw_student_category = planning_row["student_category"]
        estimated_students = planning_row["estimated_students"]
        student_category = _normalize_budget_student_category(raw_student_category)
        matching_tuitions = tuition_by_grade_category[
            (grade_level.id, student_category)
        ]
        per_student_tuition = matching_tuitions[0].amount if matching_tuitions else ZERO
        section_ids = section_ids_by_grade[grade_level.id]
        section_fee_totals = []
        for section_id in section_ids:
            total = sum(
                (
                    section_fee.amount
                    for section_fee in fees_by_section[section_id]
                    if (
                        (section_fee.general_fee.student_target or "").strip().lower()
                        in {"", "all", "all students"}
                        or _normalize_budget_student_category(
                            section_fee.general_fee.student_target
                        ) == student_category
                    )
                ),
                ZERO,
            )
            section_fee_totals.append(total)
        per_student_other_fees = (
            sum(section_fee_totals, ZERO) / Decimal(len(section_fee_totals))
            if section_fee_totals
            else ZERO
        ).quantize(Decimal("0.01"))
        per_student_fees = per_student_tuition + per_student_other_fees
        amount = per_student_fees * estimated_students
        tuition_amount = per_student_tuition * estimated_students
        setup_warnings = []
        if not matching_tuitions:
            setup_warnings.append(
                f"No {student_category} tuition is configured for {grade_level.name}."
            )
        elif len(matching_tuitions) > 1:
            setup_warnings.append(
                f"Multiple {student_category} tuition rows exist for {grade_level.name}; the oldest active row is used."
            )
        if not section_ids:
            setup_warnings.append(
                f"No active class sections are configured for {grade_level.name}."
            )
        elif not any(section_fee_totals):
            setup_warnings.append(
                f"No applicable active section fees are configured for {grade_level.name}."
            )
        student_fee_total += amount
        tuition_total += tuition_amount
        actual_students = (
            category_totals[(grade_level.id, raw_student_category)]
            if raw_student_category
            else grade_totals[grade_level.id]
        )
        results.append({
            "projection_type": "enrollment_fees", "grade_level_id": str(grade_level.id),
            "grade_level": grade_level.name,
            "student_category": raw_student_category, "headcount": estimated_students,
            "actual_headcount": actual_students,
            "headcount_variance": actual_students - estimated_students,
            "tuition_per_student": per_student_tuition,
            "other_fees_per_student": per_student_other_fees,
            "total_fees_per_student": per_student_fees,
            "projected_amount": amount,
            "projected_tuition_amount": tuition_amount,
            "projected_other_fee_amount": amount - tuition_amount,
            "section_count": len(section_ids),
            "setup_complete": not setup_warnings,
            "setup_warnings": setup_warnings,
        })
    start, end = budget.academic_year.start_date, budget.academic_year.end_date
    compensations = EmployeeCompensation.objects.filter(
        is_active=True,
        effective_start_date__lte=end,
    ).filter(
        Q(effective_end_date__isnull=True) | Q(effective_end_date__gte=start),
        Q(currency=budget.base_currency) | Q(currency__isnull=True),
    )
    payroll_total = ZERO
    employee_ids = set()
    for compensation in compensations:
        employee_ids.add(compensation.employee_id)
        effective_start = max(start, compensation.effective_start_date)
        effective_end = min(end, compensation.effective_end_date or end)
        effective_days = Decimal((effective_end - effective_start).days + 1)
        payroll_total += compensation.annual_salary * effective_days / Decimal("365")
    payroll_total = payroll_total.quantize(Decimal("0.01"))
    results.append({
        "projection_type": "payroll", "grade_level": None, "student_category": "",
        "headcount": len(employee_ids), "projected_amount": payroll_total,
    })
    return {
        "summary": {
            "student_fee_projection": student_fee_total,
            "tuition_projection": tuition_total,
            "other_student_fee_projection": student_fee_total - tuition_total,
            "payroll_projection": payroll_total,
            "estimated_students": sum(assumption.estimated_students for assumption in assumptions),
            "actual_students": sum(row["actual_students"] for row in enrollment_rows),
            "setup_incomplete_grades": sum(
                1
                for row in results
                if row["projection_type"] == "enrollment_fees" and not row["setup_complete"]
            ),
        },
        "results": results, "count": len(results),
        "context": {
            "budget_id": str(budget.id),
            "academic_year_id": str(budget.academic_year_id),
            "academic_year": str(budget.academic_year),
            "currency": budget.base_currency.code,
            "projection_start_date": budget.academic_year.start_date.isoformat(),
            "projection_end_date": budget.academic_year.end_date.isoformat(),
        },
        "definitions": {
            "fees": "Projected student fees equal estimated enrollment multiplied by tuition and the average applicable active fee total across the grade's active class sections. These rates come from the current Academic Setup and are treated as base-currency amounts.",
            "tuition": "Tuition comes from the grade-level tuition table. Grade-level assumptions without a student category use returning-student tuition.",
            "setup": "Configure grade tuition, active class sections, and active section fees in Academic Setup before completing the budget. The setup models are current configuration and are not versioned by academic year.",
            "enrollment": "Actual headcount is the current enrolled-or-completed count for the academic year and is not reconstructed as of a selected report date.",
            "payroll": "Active EmployeeCompensation annual salaries in the budget currency, or with no currency (treated as base currency), prorated by effective dates across the full academic year.",
        },
    }


def student_receivables_metrics(budget, start_date=None, end_date=None):
    start = start_date or budget.academic_year.start_date
    end = end_date or budget.academic_year.end_date
    valid_bills = AccountingStudentBill.objects.filter(
        academic_year=budget.academic_year,
        currency=budget.base_currency,
    ).exclude(status=AccountingStudentBill.BillStatus.CANCELLED)
    tuition_billed = AccountingStudentBillLine.objects.filter(
        student_bill__academic_year=budget.academic_year,
        student_bill__bill_date__range=(start, end),
        student_bill__currency=budget.base_currency,
        currency=budget.base_currency,
        fee_item__category="tuition",
    ).exclude(student_bill__status=AccountingStudentBill.BillStatus.CANCELLED).aggregate(
        total=Coalesce(
            Sum("line_amount"), Value(ZERO),
            output_field=DecimalField(max_digits=18, decimal_places=2),
        )
    )["total"]
    current_outstanding = valid_bills.aggregate(
        total=Coalesce(
            Sum("outstanding_amount"), Value(ZERO),
            output_field=DecimalField(max_digits=18, decimal_places=2),
        )
    )["total"]
    year_allocation = AccountingStudentPaymentAllocation.objects.filter(
        cash_transaction_id=OuterRef("pk"),
        student_bill__academic_year=budget.academic_year,
        student_bill__currency=budget.base_currency,
    ).exclude(student_bill__status=AccountingStudentBill.BillStatus.CANCELLED)
    any_allocation = AccountingStudentPaymentAllocation.objects.filter(
        cash_transaction_id=OuterRef("pk")
    )
    student_has_year_bill = AccountingStudentBill.objects.filter(
        student_id=OuterRef("student_id"),
        academic_year=budget.academic_year,
        currency=budget.base_currency,
    ).exclude(status=AccountingStudentBill.BillStatus.CANCELLED)
    total_student_collections = AccountingCashTransaction.objects.annotate(
        has_year_allocation=Exists(year_allocation),
        has_any_allocation=Exists(any_allocation),
        student_has_year_bill=Exists(student_has_year_bill),
    ).filter(
        status=AccountingCashTransaction.TransactionStatus.COMPLETED,
        transaction_type__transaction_category="income",
        transaction_date__range=(start, end),
    ).filter(
        Q(has_year_allocation=True)
        | Q(has_any_allocation=False, student_has_year_bill=True)
    ).aggregate(
        total=Coalesce(
            Sum(Abs(F("base_amount"))), Value(ZERO),
            output_field=DecimalField(max_digits=18, decimal_places=2),
        )
    )["total"]
    return {
        "actual_tuition_billed": tuition_billed,
        "total_student_collections": total_student_collections,
        "current_student_outstanding": current_outstanding,
    }


def _user_display_name(user):
    if not user:
        return ""
    full_name = getattr(user, "get_full_name", lambda: "")() or ""
    return full_name.strip() or getattr(user, "username", "") or str(user)


def comprehensive_budget_details(budget, summary_payload):
    projection = projection_payload(budget)
    summary_rows = {row["line_id"]: row for row in summary_payload["results"]}
    revisions = list(budget.revisions.all())
    approved_deltas = defaultdict(lambda: ZERO)
    revision_rows = []

    for revision in revisions:
        delta_rows = []
        for delta in revision.line_deltas.all():
            if revision.status == BudgetRevision.Status.APPROVED:
                approved_deltas[str(delta.budget_line_id)] += delta.amount_delta
            delta_rows.append({
                "line_id": str(delta.budget_line_id),
                "section": delta.budget_line.section.name,
                "line": delta.budget_line.name,
                "amount_delta": delta.amount_delta,
                "rationale": delta.rationale,
            })
        revision_rows.append({
            "number": revision.number,
            "status": revision.status,
            "reason": revision.reason,
            "approved_at": revision.approved_at.isoformat() if revision.approved_at else None,
            "approved_by": _user_display_name(revision.approved_by),
            "line_deltas": delta_rows,
        })

    sections = []
    period_allocations = []
    for section in budget.sections.all():
        lines = []
        section_totals = defaultdict(lambda: ZERO)
        for line in section.lines.all():
            line_id = str(line.id)
            result = summary_rows.get(line_id, {})
            approved_delta = approved_deltas[line_id]
            effective_amount = line.annual_planned_amount + approved_delta
            periods = []
            for period in line.periods.all():
                period_row = {
                    "section": section.name,
                    "line": line.name,
                    "start_date": period.start_date.isoformat(),
                    "end_date": period.end_date.isoformat(),
                    "planned_amount": period.planned_amount,
                }
                periods.append(period_row)
                period_allocations.append(period_row)
            line_row = {
                "id": line_id,
                "name": line.name,
                "source_type": line.source_type,
                "source_ref": line.source_ref,
                "gl_account_code": line.gl_account.code if line.gl_account else "",
                "gl_account_name": line.gl_account.name if line.gl_account else "",
                "original_amount": line.annual_planned_amount,
                "approved_amendments": approved_delta,
                "effective_amount": effective_amount,
                "report_planned_amount": result.get("planned_amount", ZERO),
                "actual_amount": result.get("actual_amount", ZERO),
                "variance_amount": result.get("variance_amount", ZERO),
                "variance_percentage": result.get("variance_percentage"),
                "periods": periods,
            }
            lines.append(line_row)
            for key in (
                "original_amount", "approved_amendments", "effective_amount",
                "report_planned_amount", "actual_amount", "variance_amount",
            ):
                section_totals[key] += line_row[key]
        sections.append({
            "id": str(section.id),
            "name": section.name,
            "section_type": section.section_type,
            "line_count": len(lines),
            "totals": dict(section_totals),
            "lines": lines,
        })

    assumptions_by_grade = {
        (str(assumption.grade_level_id), assumption.student_category): assumption
        for assumption in budget.enrollment_assumptions.all()
    }
    enrollment = []
    for projection_row in projection["results"]:
        if projection_row["projection_type"] != "enrollment_fees":
            continue
        assumption = assumptions_by_grade.get(
            (projection_row["grade_level_id"], projection_row["student_category"])
        )
        enrollment.append({
            "grade_level": projection_row["grade_level"],
            "student_category": projection_row["student_category"],
            "prior_actual_students": assumption.prior_actual_students if assumption else None,
            "estimated_students": projection_row["headcount"],
            "actual_students": projection_row["actual_headcount"],
            "headcount_variance": projection_row["headcount_variance"],
            "tuition_per_student": projection_row.get("tuition_per_student", ZERO),
            "other_fees_per_student": projection_row.get("other_fees_per_student", ZERO),
            "total_fees_per_student": projection_row.get("total_fees_per_student", ZERO),
            "projected_tuition": projection_row.get("projected_tuition_amount", ZERO),
            "projected_other_fees": projection_row.get("projected_other_fee_amount", ZERO),
            "projected_student_fees": projection_row.get("projected_amount", ZERO),
            "section_count": projection_row.get("section_count", 0),
            "setup_complete": projection_row.get("setup_complete", False),
            "setup_warnings": projection_row.get("setup_warnings", []),
        })

    payroll_projection = next(
        (row for row in projection["results"] if row["projection_type"] == "payroll"),
        {"headcount": 0, "projected_amount": ZERO},
    )
    actual_payroll = sum(
        (
            row["actual_amount"]
            for row in summary_payload["results"]
            if row["source_type"] == BudgetLine.SourceType.PAYROLL
        ),
        ZERO,
    )
    full_year_report = (
        summary_payload["context"]["start_date"] == budget.academic_year.start_date.isoformat()
        and summary_payload["context"]["end_date"] == budget.academic_year.end_date.isoformat()
    )
    lifecycle = [
        {
            "event_type": event.event_type,
            "from_status": event.from_status,
            "to_status": event.to_status,
            "reason": event.reason,
            "actor": _user_display_name(event.actor),
            "created_at": event.created_at.isoformat(),
        }
        for event in budget.lifecycle_events.all()
    ]

    return {
        "budget": {
            "name": budget.name,
            "status": budget.status,
            "version": budget.version,
            "is_original": budget.is_original,
            "notes": budget.notes,
            "academic_year": str(budget.academic_year),
            "academic_year_start": budget.academic_year.start_date.isoformat(),
            "academic_year_end": budget.academic_year.end_date.isoformat(),
            "currency": budget.base_currency.code,
            "submitted_at": budget.submitted_at.isoformat() if budget.submitted_at else None,
            "submitted_by": _user_display_name(budget.submitted_by),
            "approved_at": budget.approved_at.isoformat() if budget.approved_at else None,
            "approved_by": _user_display_name(budget.approved_by),
            "activated_at": budget.activated_at.isoformat() if budget.activated_at else None,
            "activated_by": _user_display_name(budget.activated_by),
            "closed_at": budget.closed_at.isoformat() if budget.closed_at else None,
            "closed_by": _user_display_name(budget.closed_by),
            "created_at": budget.created_at.isoformat(),
            "updated_at": budget.updated_at.isoformat(),
        },
        "sections": sections,
        "period_allocations": period_allocations,
        "enrollment": enrollment,
        "enrollment_summary": {
            "prior_actual_students": sum(row["prior_actual_students"] or 0 for row in enrollment),
            "estimated_students": projection["summary"]["estimated_students"],
            "actual_students": projection["summary"]["actual_students"],
            "projected_tuition": projection["summary"]["tuition_projection"],
            "projected_other_fees": projection["summary"]["other_student_fee_projection"],
            "projected_student_fees": projection["summary"]["student_fee_projection"],
        },
        "workforce": {
            "compensation_covered_employees": payroll_projection["headcount"],
            "projected_base_payroll": payroll_projection["projected_amount"],
            "actual_mapped_payroll_report_period": actual_payroll,
            "variance": payroll_projection["projected_amount"] - actual_payroll if full_year_report else None,
            "staffing_plan_available": False,
            "methodology": projection["definitions"]["payroll"],
            "limitation": (
                "Compensation-covered employees are existing employees with active compensation "
                "overlapping the academic year. This is not an approved staffing or FTE plan and "
                "does not include future vacant positions, hourly earnings without an annual salary, "
                "or employer benefits and contributions. Variance is shown only for a full-year report."
            ),
        },
        "revisions": revision_rows,
        "lifecycle": lifecycle,
        "definitions": {
            **summary_payload["definitions"],
            "enrollment": projection["definitions"]["enrollment"],
            "fees": projection["definitions"]["fees"],
            "tuition": projection["definitions"]["tuition"],
            "academic_setup": projection["definitions"]["setup"],
            "payroll_projection": projection["definitions"]["payroll"],
        },
    }


def add_projected_student_revenue(summary_payload, details):
    summary = summary_payload["summary"]
    enrollment = details["enrollment_summary"]
    budget_line_revenue = summary["planned_revenue"]
    projected_tuition = enrollment["projected_tuition"]
    projected_section_fees = enrollment["projected_other_fees"]
    projected_student_fees = enrollment["projected_student_fees"]
    total_projected_revenue = budget_line_revenue + projected_student_fees
    planned_surplus = total_projected_revenue - summary["planned_expense"]

    details["revenue_composition"] = {
        "budget_line_revenue": budget_line_revenue,
        "projected_student_tuition": projected_tuition,
        "projected_class_section_fees": projected_section_fees,
        "projected_student_fees": projected_student_fees,
        "total_projected_revenue": total_projected_revenue,
    }
    summary.update({
        "budget_line_planned_revenue": budget_line_revenue,
        "projected_student_tuition": projected_tuition,
        "projected_class_section_fees": projected_section_fees,
        "projected_student_fees": projected_student_fees,
        "planned_revenue": total_projected_revenue,
        "planned_surplus": planned_surplus,
        "revenue_variance": summary["actual_revenue"] - total_projected_revenue,
        "surplus_variance": summary["actual_surplus"] - planned_surplus,
        "revenue_performance_percentage": (
            summary["actual_revenue"] / total_projected_revenue * Decimal("100")
            if total_projected_revenue else None
        ),
        "planned_revenue_expense_ratio": (
            total_projected_revenue / summary["planned_expense"]
            if summary["planned_expense"] else None
        ),
    })
    summary_payload["definitions"]["total_projected_revenue"] = (
        "Budget line revenue plus projected student tuition and projected class-section fees "
        "derived from enrollment estimates and the current Academic Setup."
    )
    return summary_payload


SUMMARY_REPORT_TYPES = {
    "budget-summary", "budget-vs-actual", "revenue-performance",
    "expense-performance", "variance-analysis", "annual-financial-performance",
}
PROJECTION_REPORT_TYPES = {
    "enrollment-vs-budget", "tuition-projection-vs-actual", "payroll-staff-cost",
}


def build_budget_report(budget, report_type, start_date=None, end_date=None):
    if report_type in SUMMARY_REPORT_TYPES:
        payload = budget_summary_payload(budget, start_date, end_date, report_type)
        if report_type == "budget-summary":
            payload["details"] = comprehensive_budget_details(budget, payload)
            add_projected_student_revenue(payload, payload["details"])
        if report_type == "revenue-performance":
            payload["results"] = [row for row in payload["results"] if row["section_type"] == "revenue"]
            payload["summary"] = {
                key: payload["summary"][key]
                for key in (
                    "planned_revenue", "actual_revenue", "revenue_variance",
                    "revenue_performance_percentage",
                )
            }
        elif report_type == "expense-performance":
            payload["results"] = [row for row in payload["results"] if row["section_type"] == "expense"]
            payload["summary"] = {
                key: payload["summary"][key]
                for key in (
                    "planned_expense", "actual_expense", "expense_variance",
                    "expense_utilization_percentage",
                )
            }
        elif report_type == "variance-analysis":
            payload["results"] = sorted(payload["results"], key=lambda row: abs(row["variance_amount"]), reverse=True)
            payload["summary"] = {
                key: payload["summary"][key]
                for key in (
                    "revenue_variance", "expense_variance", "planned_surplus",
                    "actual_surplus", "surplus_variance",
                )
            }
        payload["count"] = len(payload["results"])
        payload["columns"] = [
            ["Section", "section"], ["Type", "section_type"], ["Budget Line", "line"],
            ["GL Account", "gl_account_code"], ["Planned Amount", "planned_amount"],
            ["Actual Amount", "actual_amount"], ["Variance Amount", "variance_amount"],
            ["Variance Percentage", "variance_percentage"],
        ]
        return payload

    if report_type in PROJECTION_REPORT_TYPES:
        payload = projection_payload(budget)
        actual_start = start_date or budget.academic_year.start_date
        actual_end = end_date or budget.academic_year.end_date
        payload["context"].update({
            "report_type": report_type,
            "actual_start_date": actual_start.isoformat(),
            "actual_end_date": actual_end.isoformat(),
        })
        if report_type == "enrollment-vs-budget":
            payload["results"] = [row for row in payload["results"] if row["projection_type"] == "enrollment_fees"]
            payload["summary"] = {
                "estimated_students": payload["summary"]["estimated_students"],
                "actual_students": payload["summary"]["actual_students"],
                "student_variance": payload["summary"]["actual_students"] - payload["summary"]["estimated_students"],
                "setup_incomplete_grades": payload["summary"]["setup_incomplete_grades"],
                "student_fee_projection": payload["summary"]["student_fee_projection"],
                "tuition_projection": payload["summary"]["tuition_projection"],
            }
            payload["columns"] = [
                ["Grade Level", "grade_level"], ["Student Category", "student_category"],
                ["Budget Headcount", "headcount"], ["Actual Headcount", "actual_headcount"],
                ["Headcount Variance", "headcount_variance"],
                ["Tuition Per Student", "tuition_per_student"],
                ["Other Fees Per Student", "other_fees_per_student"],
                ["Total Fees Per Student", "total_fees_per_student"],
                ["Projected Student Fees", "projected_amount"],
                ["Projected Tuition", "projected_tuition_amount"],
                ["Projected Other Fees", "projected_other_fee_amount"],
            ]
        elif report_type == "tuition-projection-vs-actual":
            receivables = student_receivables_metrics(budget, start_date, end_date)
            tuition_projection = payload["summary"]["tuition_projection"]
            payload["summary"] = {
                "tuition_projection": tuition_projection,
                "all_student_fee_projection": payload["summary"]["student_fee_projection"],
                "other_student_fee_projection": payload["summary"]["other_student_fee_projection"],
                **receivables,
                "tuition_billing_variance": receivables["actual_tuition_billed"] - tuition_projection,
            }
            payload["results"] = [row for row in payload["results"] if row["projection_type"] == "enrollment_fees"]
            payload["columns"] = [
                ["Grade Level", "grade_level"], ["Student Category", "student_category"],
                ["Budget Headcount", "headcount"],
                ["Tuition Per Student", "tuition_per_student"],
                ["Other Fees Per Student", "other_fees_per_student"],
                ["Total Fees Per Student", "total_fees_per_student"],
                ["Projected Tuition", "projected_tuition_amount"],
                ["Projected Other Fees", "projected_other_fee_amount"],
                ["Projected Student Fees", "projected_amount"],
            ]
            payload["definitions"].update({
                "actual_tuition_billed": "Gross base-currency AccountingStudentBillLine amounts categorized as tuition on non-cancelled bills dated in the selected actual period; concessions are not allocated to bill lines.",
                "total_student_collections": "Completed student cash receipts counted once in base_amount for the selected actual period. A receipt is included when it has a non-cancelled bill allocation for the academic year, or when it is directly linked to a student with such a bill and has no allocations. It is not tuition-only because payment allocations do not identify fee lines.",
                "collection_limitation": "Collections cannot be precisely allocated to tuition versus other fees with the current payment-allocation model and are deliberately labeled total student collections.",
                "current_student_outstanding": "Current non-cancelled base-currency student-bill outstanding balance for the academic year. This is a current balance, not a historical as-of balance for the selected actual period.",
                "currency": "Non-base-currency bill lines, bills, and fee rates are excluded because those models do not store base amounts; completed cash collections use base_amount.",
            })
        elif report_type == "payroll-staff-cost":
            payload["results"] = [row for row in payload["results"] if row["projection_type"] == "payroll"]
            actual_payload = budget_summary_payload(budget, start_date, end_date)
            actual = sum(
                (row["actual_amount"] for row in actual_payload["results"] if row["source_type"] == BudgetLine.SourceType.PAYROLL),
                ZERO,
            )
            payroll_projection = payload["summary"]["payroll_projection"]
            payload["summary"] = {
                "payroll_projection": payroll_projection,
                "actual_payroll": actual,
                "payroll_variance": payroll_projection - actual,
            }
            for row in payload["results"]:
                row["actual_amount"] = actual
                row["variance_amount"] = row["projected_amount"] - actual
            payload["columns"] = [
                ["Staff Headcount", "headcount"], ["Projected Amount", "projected_amount"],
                ["Actual Amount", "actual_amount"], ["Variance Amount", "variance_amount"],
            ]
        payload["count"] = len(payload["results"])
        return payload
    raise ValidationError("Unsupported budget report type.")
