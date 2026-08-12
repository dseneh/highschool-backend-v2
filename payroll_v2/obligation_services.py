from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

from payroll_v2.enums import (
    DeductionSourceType,
    EmployeeContributionType,
    PayrollDeductionScheduleStatus,
    SalaryAdvanceStatus,
    SponsorshipCoverageType,
)

MONEY_QUANT = Decimal("0.01")
PERCENT_QUANT = Decimal("0.0001")
HUNDRED = Decimal("100")


def to_money(value: Decimal | int | float | str | None) -> Decimal:
    return Decimal(str(value or "0")).quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def percent_of(amount: Decimal | int | float | str, percent: Decimal | int | float | str) -> Decimal:
    amount_value = Decimal(str(amount or "0"))
    percent_value = Decimal(str(percent or "0"))
    return to_money((amount_value * percent_value) / HUNDRED)


def _percent_used(*, amount: Decimal, total: Decimal) -> Decimal:
    if total <= Decimal("0.00"):
        return Decimal("0.0000")
    used = (Decimal(str(amount or "0")) * HUNDRED) / Decimal(str(total))
    if used < Decimal("0.00"):
        return Decimal("0.0000")
    if used > HUNDRED:
        return HUNDRED
    return used.quantize(PERCENT_QUANT, rounding=ROUND_HALF_UP)


def calculate_sponsorship_coverage_amount(*, eligible_fee_total: Decimal, coverage_type: str, coverage_value: Decimal) -> Decimal:
    """Calculate school coverage from policy values without hardcoded percentages."""

    eligible = to_money(eligible_fee_total)
    value = Decimal(str(coverage_value or "0"))

    if coverage_type == SponsorshipCoverageType.FULL:
        return eligible
    if coverage_type == SponsorshipCoverageType.PERCENTAGE:
        return min(eligible, percent_of(eligible, value))
    if coverage_type == SponsorshipCoverageType.FIXED_AMOUNT:
        return min(eligible, to_money(value))
    return Decimal("0.00")


def calculate_employee_contribution_amount(
    *,
    eligible_fee_total: Decimal,
    school_covered_amount: Decimal,
    contribution_type: str,
    contribution_value: Decimal,
) -> Decimal:
    """Calculate employee obligation from configured contribution mode."""

    eligible = to_money(eligible_fee_total)
    school = to_money(school_covered_amount)
    value = Decimal(str(contribution_value or "0"))

    residual = max(Decimal("0.00"), to_money(eligible - school))

    if contribution_type == EmployeeContributionType.NONE:
        return residual
    if contribution_type == EmployeeContributionType.PERCENTAGE:
        return min(eligible, percent_of(eligible, value))
    if contribution_type == EmployeeContributionType.FIXED_AMOUNT:
        return min(eligible, to_money(value))
    return residual


def calculate_equal_installment_amount(*, total_amount: Decimal, installments: int) -> Decimal:
    if installments <= 0:
        raise ValueError("installments must be greater than zero")
    return to_money(Decimal(str(total_amount or "0")) / Decimal(str(installments)))


@dataclass(frozen=True)
class DeductionLimitResult:
    is_allowed: bool
    allowed_amount: Decimal
    max_deduction_amount: Decimal
    min_net_pay_amount: Decimal
    resulting_net_pay: Decimal
    reason: str | None


def _normalize_percent(value: Decimal | int | float | str | None, *, default: str = "0") -> Decimal:
    parsed = Decimal(str(value if value is not None else default))
    if parsed < Decimal("0"):
        return Decimal("0")
    if parsed > HUNDRED:
        return HUNDRED
    return parsed


def resolve_employee_reference_gross_salary(employee) -> Decimal:
    """Resolve the employee gross salary reference used for obligation capacity checks."""

    from payroll_v2.models import EmployeeCompensation

    if employee is None:
        return Decimal("0.00")

    salary = Decimal("0.00")
    compensation = (
        EmployeeCompensation.objects.filter(
            employee=employee,
            is_active=True,
        )
        .order_by("-effective_start_date", "-created_at")
        .first()
    )
    if compensation is not None:
        salary = to_money(compensation.base_amount)

    if salary <= Decimal("0.00"):
        salary = to_money(getattr(employee, "basic_salary", None))

    return max(Decimal("0.00"), salary)


def _active_periodic_obligation_totals(*, employee, exclude_source_type=None, exclude_source_id=None):
    from payroll_v2.models import PayrollDeductionSchedule

    schedules = PayrollDeductionSchedule.objects.filter(
        employee=employee,
        remaining_amount__gt=Decimal("0.00"),
        status__in=[
            PayrollDeductionScheduleStatus.PLANNED,
            PayrollDeductionScheduleStatus.PARTIALLY_APPLIED,
            PayrollDeductionScheduleStatus.DEFERRED,
            PayrollDeductionScheduleStatus.ADJUSTED,
            PayrollDeductionScheduleStatus.APPLIED,
        ],
    )

    if exclude_source_type and exclude_source_id:
        schedules = schedules.exclude(source_type=exclude_source_type, source_id=str(exclude_source_id))

    ward_periodic = Decimal("0.00")
    salary_advance_periodic = Decimal("0.00")
    other_periodic = Decimal("0.00")
    for schedule in schedules:
        periodic = max(Decimal("0.00"), to_money(schedule.scheduled_amount))
        if schedule.source_type == DeductionSourceType.STAFF_WARD_SPONSORSHIP:
            ward_periodic += periodic
        elif schedule.source_type == DeductionSourceType.SALARY_ADVANCE:
            salary_advance_periodic += periodic
        else:
            other_periodic += periodic

    return {
        "ward": to_money(ward_periodic),
        "salary_advance": to_money(salary_advance_periodic),
        "other": to_money(other_periodic),
    }


def _active_ward_sponsorship_outstanding_amount(*, employee, exclude_source_id=None):
    from payroll_v2.models import StaffWardSponsorship

    sponsorships = StaffWardSponsorship.objects.filter(
        employee=employee,
        status__in=[
            "pending",
            "approved",
            "active",
        ],
    )
    if exclude_source_id:
        sponsorships = sponsorships.exclude(id=exclude_source_id)

    total_outstanding = Decimal("0.00")
    for sponsorship in sponsorships:
        remaining = to_money(getattr(sponsorship, "repayment_remaining_balance", None))
        if remaining <= Decimal("0.00"):
            total = to_money(getattr(sponsorship, "total_sponsored_amount", None))
            paid = to_money(getattr(sponsorship, "repayment_paid_amount", None))
            remaining = max(Decimal("0.00"), to_money(total - paid))
        total_outstanding += remaining

    return to_money(total_outstanding)


def _active_salary_advance_committed_amount(*, employee, exclude_source_id=None):
    from payroll_v2.models import SalaryAdvance

    advances = SalaryAdvance.objects.filter(
        employee=employee,
        status__in=[
            SalaryAdvanceStatus.SUBMITTED,
            SalaryAdvanceStatus.APPROVED,
            SalaryAdvanceStatus.COMPLETED,
        ],
    )
    if exclude_source_id:
        advances = advances.exclude(id=exclude_source_id)

    committed = Decimal("0.00")
    for advance in advances:
        remaining = to_money(getattr(advance, "remaining_balance", None))
        if remaining <= Decimal("0.00"):
            approved = to_money(getattr(advance, "approved_amount", None) or getattr(advance, "amount", None))
            paid = to_money(getattr(advance, "amount_paid", None))
            remaining = max(Decimal("0.00"), to_money(approved - paid))
        committed += remaining

    return to_money(committed)


def evaluate_employee_obligation_eligibility(
    *,
    employee,
    payroll_settings,
    obligation_type: str,
    requested_periodic_deduction: Decimal | None = None,
    requested_amount: Decimal | None = None,
    requested_installments: int | None = None,
    repayment_method: str | None = None,
    fixed_installment_amount: Decimal | None = None,
    exclude_source_type=None,
    exclude_source_id=None,
):
    """Centralized rule evaluation for salary advance and ward sponsorship deductions."""

    gross_salary = resolve_employee_reference_gross_salary(employee)
    installment_count = max(1, int(requested_installments or 1))
    requested_amount_value = max(Decimal("0.00"), to_money(requested_amount)) if requested_amount is not None else Decimal("0.00")

    if requested_periodic_deduction is not None:
        requested = max(Decimal("0.00"), to_money(requested_periodic_deduction))
    elif requested_amount_value > Decimal("0.00"):
        if repayment_method == "fixed_installment" and fixed_installment_amount is not None:
            requested = max(Decimal("0.00"), to_money(fixed_installment_amount))
        else:
            requested = to_money(requested_amount_value / Decimal(str(installment_count)))
    else:
        requested = Decimal("0.00")

    max_ward_pct = _normalize_percent(
        getattr(payroll_settings, "maximum_ward_sponsorship_deduction_percent", None),
        default="40",
    )
    max_salary_advance_pct = _normalize_percent(
        getattr(payroll_settings, "maximum_salary_advance_deduction_percent", None),
        default="20",
    )
    tax_reserve_pct = _normalize_percent(
        getattr(payroll_settings, "tax_reserve_percent", None),
        default="20",
    )
    min_take_home_pct = _normalize_percent(
        getattr(payroll_settings, "minimum_take_home_pay_percent", None),
        default="30",
    )

    max_ward_amount = percent_of(gross_salary, max_ward_pct)
    max_salary_advance_amount = percent_of(gross_salary, max_salary_advance_pct)
    tax_reserve_amount = percent_of(gross_salary, tax_reserve_pct)
    min_take_home_amount = percent_of(gross_salary, min_take_home_pct)
    protected_take_home_floor = max(tax_reserve_amount, min_take_home_amount)

    active_totals = _active_periodic_obligation_totals(
        employee=employee,
        exclude_source_type=exclude_source_type,
        exclude_source_id=exclude_source_id,
    )
    ward_existing_periodic = active_totals["ward"]
    salary_advance_existing = active_totals["salary_advance"]
    other_existing = active_totals["other"]
    ward_existing_outstanding = ward_existing_periodic
    try:
        ward_existing_outstanding = _active_ward_sponsorship_outstanding_amount(
            employee=employee,
            exclude_source_id=exclude_source_id if exclude_source_type == DeductionSourceType.STAFF_WARD_SPONSORSHIP else None,
        )
    except Exception:
        ward_existing_outstanding = ward_existing_periodic

    max_total_obligation_capacity = max(Decimal("0.00"), to_money(gross_salary - protected_take_home_floor))
    total_existing = to_money(ward_existing_periodic + salary_advance_existing + other_existing)
    room_by_take_home = max(Decimal("0.00"), to_money(max_total_obligation_capacity - total_existing))

    ward_used_percent = _percent_used(amount=ward_existing_periodic, total=gross_salary)
    ward_remaining_percent = max(Decimal("0.0000"), max_ward_pct - ward_used_percent)

    if obligation_type == DeductionSourceType.SALARY_ADVANCE:
        ward_unused = max(Decimal("0.00"), to_money(max_ward_amount - ward_existing_periodic))
        # Salary advance can use its own configured cap plus any currently unused ward allocation.
        available_by_category = max(
            Decimal("0.00"),
            to_money((max_salary_advance_amount + ward_unused) - salary_advance_existing),
        )
        can_borrow_ward_allocation = ward_unused > Decimal("0.00")
    elif obligation_type == DeductionSourceType.STAFF_WARD_SPONSORSHIP:
        available_by_category = max(Decimal("0.00"), to_money(max_ward_amount - ward_existing_periodic))
        can_borrow_ward_allocation = False
    else:
        available_by_category = room_by_take_home
        can_borrow_ward_allocation = False

    max_additional_allowed = min(available_by_category, room_by_take_home)
    is_eligible = requested <= max_additional_allowed

    committed_advance_amount = Decimal("0.00")
    max_request_capacity_for_installments = Decimal("0.00")
    available_to_request_amount = Decimal("0.00")
    maximum_salary_advance_capacity_percent = Decimal("0.0000")
    maximum_salary_advance_capacity_amount = Decimal("0.00")
    if obligation_type == DeductionSourceType.SALARY_ADVANCE:
        maximum_salary_advance_capacity_percent = (max_salary_advance_pct + ward_remaining_percent).quantize(
            PERCENT_QUANT,
            rounding=ROUND_HALF_UP,
        )
        maximum_salary_advance_capacity_amount = percent_of(
            gross_salary,
            maximum_salary_advance_capacity_percent,
        )
        committed_advance_amount = _active_salary_advance_committed_amount(
            employee=employee,
            exclude_source_id=exclude_source_id,
        )
        # Keep legacy field name for API compatibility; value is now salary-based maximum capacity.
        max_request_capacity_for_installments = maximum_salary_advance_capacity_amount
        available_to_request_amount = max(
            Decimal("0.00"),
            to_money(max_request_capacity_for_installments - committed_advance_amount),
        )
        if requested_amount_value > Decimal("0.00") and requested_amount_value > available_to_request_amount:
            is_eligible = False

    projected_total = to_money(total_existing + requested)
    projected_take_home = to_money(gross_salary - projected_total)
    remaining_after_request = max(Decimal("0.00"), to_money(max_additional_allowed - requested))

    reasons: list[str] = []
    warnings: list[str] = []
    if gross_salary <= Decimal("0.00"):
        reasons.append("Employee has no active gross salary configured for payroll deductions.")
    if requested > max_additional_allowed:
        reasons.append(
            "Requested deduction exceeds allowed capacity after tax reserve and minimum take-home checks."
        )
    if obligation_type == DeductionSourceType.STAFF_WARD_SPONSORSHIP and requested > available_by_category:
        reasons.append("Requested deduction exceeds the maximum ward sponsorship deduction percentage.")
    if obligation_type == DeductionSourceType.SALARY_ADVANCE and requested > available_by_category:
        reasons.append("Requested deduction exceeds the maximum salary advance deduction percentage.")
    if (
        obligation_type == DeductionSourceType.SALARY_ADVANCE
        and requested_amount_value > Decimal("0.00")
        and requested_amount_value > available_to_request_amount
    ):
        reasons.append(
            "Requested amount exceeds currently available salary advance capacity. "
            f"Available to request is {available_to_request_amount}."
        )
    if can_borrow_ward_allocation and ward_existing_periodic <= Decimal("0.00"):
        warnings.append(
            "No active ward sponsorship deduction was found, so unused ward allocation is available for salary advance."
        )
    elif can_borrow_ward_allocation and ward_existing_periodic > Decimal("0.00"):
        warnings.append(
            "Part of the ward sponsorship allocation remains unused and is included in salary advance capacity."
        )

    return {
        "is_eligible": bool(is_eligible and gross_salary > Decimal("0.00")),
        "obligation_type": obligation_type,
        "requested_periodic_deduction": str(requested),
        "requested_amount": str(requested_amount_value),
        "requested_installments": installment_count,
        "max_additional_allowed": str(max_additional_allowed),
        "remaining_capacity_after_request": str(remaining_after_request),
        "projected_take_home_pay": str(projected_take_home),
        "maximum_allowed_amount": str(max_request_capacity_for_installments),
        "already_committed_amount": str(committed_advance_amount),
        "available_to_request_amount": str(available_to_request_amount),
        "breakdown": {
            "gross_salary": str(gross_salary),
            "tax_reserve_percent": str(tax_reserve_pct),
            "tax_reserve_amount": str(tax_reserve_amount),
            "minimum_take_home_pay_percent": str(min_take_home_pct),
            "minimum_take_home_pay_amount": str(min_take_home_amount),
            "protected_take_home_floor": str(protected_take_home_floor),
            "maximum_ward_sponsorship_deduction_percent": str(max_ward_pct),
            "maximum_ward_sponsorship_deduction_amount": str(max_ward_amount),
            "maximum_salary_advance_deduction_percent": str(max_salary_advance_pct),
            "maximum_salary_advance_deduction_amount": str(max_salary_advance_amount),
            "existing_ward_sponsorship_deduction": str(ward_existing_outstanding),
            "existing_ward_sponsorship_deduction_periodic": str(ward_existing_periodic),
            "existing_salary_advance_deduction": str(salary_advance_existing),
            "existing_other_deduction": str(other_existing),
            "existing_total_periodic_deduction": str(total_existing),
            "max_total_obligation_capacity": str(max_total_obligation_capacity),
            "room_by_take_home": str(room_by_take_home),
            "room_by_category": str(available_by_category),
            "can_borrow_ward_allocation": can_borrow_ward_allocation,
            "projected_total_periodic_deduction": str(projected_total),
            "max_request_capacity_for_installments": str(max_request_capacity_for_installments),
            "already_committed_advance_amount": str(committed_advance_amount),
            "available_to_request_amount": str(available_to_request_amount),
            "ward_allocation_used_percent": str(ward_used_percent),
            "ward_allocation_available_percent": str(ward_remaining_percent),
            "maximum_salary_advance_capacity_percent": str(maximum_salary_advance_capacity_percent),
            "maximum_salary_advance_capacity_amount": str(maximum_salary_advance_capacity_amount),
        },
        "reasons": reasons,
        "warnings": warnings,
    }


def validate_employee_obligation_eligibility(
    *,
    employee,
    payroll_settings,
    obligation_type: str,
    requested_periodic_deduction: Decimal | None = None,
    requested_amount: Decimal | None = None,
    requested_installments: int | None = None,
    repayment_method: str | None = None,
    fixed_installment_amount: Decimal | None = None,
    exclude_source_type=None,
    exclude_source_id=None,
):
    evaluation = evaluate_employee_obligation_eligibility(
        employee=employee,
        payroll_settings=payroll_settings,
        obligation_type=obligation_type,
        requested_periodic_deduction=requested_periodic_deduction,
        requested_amount=requested_amount,
        requested_installments=requested_installments,
        repayment_method=repayment_method,
        fixed_installment_amount=fixed_installment_amount,
        exclude_source_type=exclude_source_type,
        exclude_source_id=exclude_source_id,
    )
    if evaluation["is_eligible"]:
        return evaluation

    reasons = evaluation.get("reasons") or ["Requested deduction is not eligible under current settings."]
    raise ValueError(" ".join(reasons))


def evaluate_deduction_limits(
    *,
    gross_pay: Decimal,
    existing_total_deductions: Decimal,
    proposed_deduction: Decimal,
    max_deduction_percent_of_gross: Decimal,
    min_net_pay_percent_of_gross: Decimal,
) -> DeductionLimitResult:
    """Evaluate deduction bounds based only on configured percentages and runtime payroll values."""

    gross = to_money(gross_pay)
    current_deductions = to_money(existing_total_deductions)
    proposed = max(Decimal("0.00"), to_money(proposed_deduction))

    max_deduction_amount = percent_of(gross, Decimal(str(max_deduction_percent_of_gross or "0")))
    min_net_pay_amount = percent_of(gross, Decimal(str(min_net_pay_percent_of_gross or "0")))

    room_by_deduction_cap = max(Decimal("0.00"), to_money(max_deduction_amount - current_deductions))
    room_by_net_floor = max(Decimal("0.00"), to_money(gross - current_deductions - min_net_pay_amount))

    allowed_amount = min(proposed, room_by_deduction_cap, room_by_net_floor)
    resulting_net_pay = to_money(gross - current_deductions - allowed_amount)
    if allowed_amount >= proposed:
        return DeductionLimitResult(
            is_allowed=True,
            allowed_amount=allowed_amount,
            max_deduction_amount=max_deduction_amount,
            min_net_pay_amount=min_net_pay_amount,
            resulting_net_pay=resulting_net_pay,
            reason=None,
        )

    reason = "exceeds_max_deduction_cap"
    if room_by_net_floor < room_by_deduction_cap:
        reason = "violates_min_net_pay"

    return DeductionLimitResult(
        is_allowed=False,
        allowed_amount=allowed_amount,
        max_deduction_amount=max_deduction_amount,
        min_net_pay_amount=min_net_pay_amount,
        resulting_net_pay=resulting_net_pay,
        reason=reason,
    )
