from __future__ import annotations

import calendar
from datetime import date
from decimal import Decimal
from decimal import ROUND_DOWN

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from authorization.runtime import user_has_permission

from hr.models import Employee
from accounting.models import (
    AccountingBankAccount,
    AccountingCashTransaction,
    AccountingPaymentMethod,
    AccountingTransactionType,
)
from accounting.models.settings import AccountingSettings

from .enums import (
    CalculationType,
    DeductionSourceType,
    Frequency,
    LineType,
    PaymentMethod,
    PaymentStatus,
    PayrollDeductionInstallmentStatus,
    PayrollDeductionScheduleStatus,
    PayrollStatus,
    PayType,
    SalaryAdvanceRepaymentMethod,
    SalaryAdvanceRepaymentStatus,
    SalaryAdvanceStatus,
    StaffWardSponsorshipStatus,
    TargetAmountSource,
)
from .models import (
    EmployeeCompensation,
    EmployeePayrollItem,
    PayrollDeductionInstallment,
    PayrollDeductionSchedule,
    PayrollCatalogItem,
    PayrollCatalogItemRule,
    PayrollEmployeeItem,
    PayrollLineItem,
    PayrollPayslipTemplate,
    PayrollPeriod,
    PayrollSettings,
    PaySchedule,
    PayrollRunRecord,
    SalaryAdvance,
    SalaryAdvancePayment,
    StaffWardSponsorship,
    StaffWardSponsorshipPolicy,
    StaffWardSponsorshipStudent,
    PayrollTableView,
)
from .obligation_services import calculate_equal_installment_amount, evaluate_deduction_limits, to_money
from .obligation_services import validate_employee_obligation_eligibility

CENT = Decimal("0.01")

LINE_TYPE_GENERATION_ORDER = {
    LineType.EARNING: 0,
    LineType.REIMBURSEMENT: 1,
    LineType.DEDUCTION: 2,
    LineType.TAX: 3,
    LineType.BENEFIT: 4,
}


def q_effective_end(start_date):
    return Q(effective_end_date__isnull=True) | Q(effective_end_date__gte=start_date)


def get_active_employee_compensation(employee, as_of_date=None):
    """Return the persisted compensation record effective on ``as_of_date`` (default: today)."""
    if not employee or not getattr(employee, "pk", None):
        return None
    as_of = as_of_date or timezone.now().date()
    return (
        EmployeeCompensation.objects.filter(
            employee=employee,
            is_active=True,
            effective_start_date__lte=as_of,
        )
        .filter(q_effective_end(as_of))
        .order_by("-effective_start_date", "-created_at")
        .first()
    )


def compute_compensation_annual_salary(compensation, *, employee=None) -> Decimal:
    """Derive annual pay from a compensation record and the employee pay schedule."""
    from payroll_v2.schedule_services import (
        annual_salary_from_period_basic,
        periods_per_year_for_schedule,
    )

    employee = employee or compensation.employee
    if compensation.pay_type == PayType.HOURLY:
        return Decimal("0.00")

    if compensation.pay_type == PayType.DAILY:
        period_amount = compensation.daily_rate or compensation.base_amount or Decimal("0.00")
    else:
        period_amount = compensation.base_amount or Decimal("0.00")

    schedule = None
    if employee is not None:
        from .schedule_services import get_employee_pay_schedule

        schedule = get_employee_pay_schedule(employee)

    return annual_salary_from_period_basic(
        period_amount,
        periods_per_year=periods_per_year_for_schedule(schedule),
    ).quantize(CENT)


def get_compensation_annual_salary(compensation, *, employee=None) -> Decimal:
    """Return stored annual salary for a compensation record, computing when unsaved."""
    if not compensation:
        return Decimal("0.00")
    if getattr(compensation, "pk", None):
        return Decimal(compensation.annual_salary or 0).quantize(CENT)
    return compute_compensation_annual_salary(compensation, employee=employee)


def refresh_employee_compensation_annual_salaries(employee, *, actor=None) -> int:
    """Recalculate stored annual salary on all compensation rows for an employee."""
    updated = 0
    for record in EmployeeCompensation.objects.filter(employee=employee):
        annual = compute_compensation_annual_salary(record, employee=employee)
        if record.annual_salary != annual:
            record.annual_salary = annual
            record.updated_by = actor
            record.save(update_fields=["annual_salary", "updated_by", "updated_at"])
            updated += 1
    active = get_active_employee_compensation(employee)
    if active:
        sync_employee_salary_mirror_from_compensation(employee, active)
    return updated


def get_employee_compensation_history(employee):
    if not employee or not getattr(employee, "pk", None):
        return EmployeeCompensation.objects.none()
    return EmployeeCompensation.objects.filter(employee=employee).order_by(
        "-effective_start_date",
        "-created_at",
    )


def compensation_has_valid_amount(compensation) -> bool:
    if not compensation:
        return False
    if compensation.pay_type == PayType.HOURLY:
        return bool(compensation.hourly_rate and compensation.hourly_rate > 0)
    if compensation.pay_type == PayType.DAILY:
        return bool(
            (compensation.daily_rate and compensation.daily_rate > 0)
            or (compensation.base_amount and compensation.base_amount > 0)
        )
    return bool(compensation.base_amount and compensation.base_amount > 0)


def _compensation_close_date(record, new_effective_start_date):
    from datetime import timedelta

    close_date = new_effective_start_date - timedelta(days=1)
    if close_date < record.effective_start_date:
        return record.effective_start_date
    return close_date


def close_open_compensation_records(*, employee, new_effective_start_date, actor=None, exclude_id=None):
    """End-date any open compensation records before a new one becomes current."""
    qs = EmployeeCompensation.objects.filter(
        employee=employee,
        is_active=True,
        effective_end_date__isnull=True,
    )
    if exclude_id:
        qs = qs.exclude(id=exclude_id)

    closed = []
    for record in qs:
        record.effective_end_date = _compensation_close_date(record, new_effective_start_date)
        record.updated_by = actor
        record.save(update_fields=["effective_end_date", "updated_by", "updated_at"])
        closed.append(record)
    return closed


@transaction.atomic
def create_employee_compensation_record(
    *,
    employee,
    pay_type,
    base_amount,
    hourly_rate=None,
    daily_rate=None,
    currency=None,
    effective_start_date,
    effective_end_date=None,
    notes="",
    actor=None,
) -> EmployeeCompensation:
    close_open_compensation_records(
        employee=employee,
        new_effective_start_date=effective_start_date,
        actor=actor,
    )

    if currency is None and employee.pay_schedule_id:
        currency = employee.pay_schedule.currency

    annual_salary = compute_compensation_annual_salary(
        EmployeeCompensation(
            employee=employee,
            pay_type=pay_type,
            base_amount=base_amount or Decimal("0.00"),
            hourly_rate=hourly_rate,
            daily_rate=daily_rate,
        ),
        employee=employee,
    )

    compensation = EmployeeCompensation.objects.create(
        employee=employee,
        pay_type=pay_type,
        base_amount=base_amount or Decimal("0.00"),
        hourly_rate=hourly_rate,
        daily_rate=daily_rate,
        annual_salary=annual_salary,
        currency=currency,
        effective_start_date=effective_start_date,
        effective_end_date=effective_end_date,
        is_active=True,
        notes=notes or "",
        created_by=actor,
        updated_by=actor,
    )

    if pay_type == PayType.HOURLY and hourly_rate is not None:
        employee.salary_type = Employee.SalaryType.HOURLY
        employee.hourly_rate = hourly_rate
        employee.annual_salary = Decimal("0.00")
        employee.save(update_fields=["salary_type", "hourly_rate", "annual_salary", "updated_at"])
    elif pay_type == PayType.SALARY and base_amount is not None:
        employee.salary_type = Employee.SalaryType.MONTHLY
        employee.basic_salary = base_amount
        employee.annual_salary = annual_salary
        employee.save(update_fields=["salary_type", "basic_salary", "annual_salary", "updated_at"])
    else:
        sync_employee_salary_mirror_from_compensation(employee, compensation)

    return compensation


def sync_employee_salary_mirror_from_compensation(employee, compensation) -> None:
    """Keep legacy employee salary columns aligned with the active compensation record."""
    if not compensation or not compensation.is_active:
        return
    active = get_active_employee_compensation(employee)
    if not active or active.id != compensation.id:
        return

    update_fields = ["updated_at"]
    if compensation.pay_type == PayType.HOURLY:
        employee.salary_type = Employee.SalaryType.HOURLY
        employee.hourly_rate = compensation.hourly_rate or Decimal("0.00")
        update_fields.extend(["salary_type", "hourly_rate"])
    elif compensation.pay_type == PayType.SALARY:
        employee.salary_type = Employee.SalaryType.MONTHLY
        employee.basic_salary = compensation.base_amount or Decimal("0.00")
        update_fields.extend(["salary_type", "basic_salary"])

    employee.annual_salary = compensation.annual_salary or Decimal("0.00")
    update_fields.append("annual_salary")
    employee.save(update_fields=update_fields)


@transaction.atomic
def update_employee_compensation_record(
    compensation: EmployeeCompensation,
    *,
    actor=None,
    **fields,
) -> EmployeeCompensation:
    employee = compensation.employee
    fields.pop("employee", None)
    for key, value in fields.items():
        if value is not None or key in {
            "hourly_rate",
            "daily_rate",
            "effective_end_date",
            "currency",
            "notes",
        }:
            setattr(compensation, key, value)

    compensation.annual_salary = compute_compensation_annual_salary(compensation, employee=employee)
    compensation.updated_by = actor
    compensation.save()
    sync_employee_salary_mirror_from_compensation(employee, compensation)
    return compensation


@transaction.atomic
def migrate_employee_salaries_to_compensation(*, actor=None) -> dict:
    """Create compensation records from legacy employee salary fields (one-time migration)."""
    created = 0
    skipped = 0
    today = timezone.now().date()

    for employee in Employee.objects.filter(employment_status=Employee.EmploymentStatus.ACTIVE):
        if EmployeeCompensation.objects.filter(employee=employee, is_active=True).exists():
            skipped += 1
            continue
        if not employee.pay_schedule_id:
            skipped += 1
            continue

        pay_type = PayType.HOURLY if employee.salary_type == Employee.SalaryType.HOURLY else PayType.SALARY
        base_amount = employee.basic_salary or Decimal("0.00")
        hourly_rate = employee.hourly_rate or Decimal("0.00")

        if pay_type == PayType.HOURLY:
            if hourly_rate <= 0:
                skipped += 1
                continue
            base_amount = Decimal("0.00")
        elif base_amount <= 0:
            skipped += 1
            continue

        effective_start = employee.hire_date or today
        create_employee_compensation_record(
            employee=employee,
            pay_type=pay_type,
            base_amount=base_amount,
            hourly_rate=hourly_rate if pay_type == PayType.HOURLY else None,
            currency=employee.pay_schedule.currency if employee.pay_schedule else None,
            effective_start_date=effective_start,
            notes="Migrated from employee salary fields",
            actor=actor,
        )
        created += 1

    return {"created": created, "skipped": skipped}


def resolve_employee_compensation(employee, start_date, end_date):
    record = (
        EmployeeCompensation.objects.filter(
            employee=employee,
            is_active=True,
            effective_start_date__lte=end_date,
        )
        .filter(q_effective_end(start_date))
        .order_by("-effective_start_date", "-created_at")
        .first()
    )
    if record:
        return record

    pay_type = PayType.HOURLY if employee.salary_type == Employee.SalaryType.HOURLY else PayType.SALARY
    base_amount = employee.basic_salary or Decimal("0.00")
    hourly_rate = employee.hourly_rate or Decimal("0.00")
    currency = None
    if employee.pay_schedule_id:
        currency = employee.pay_schedule.currency_id

    unsaved = EmployeeCompensation(
        employee=employee,
        pay_type=pay_type,
        base_amount=base_amount,
        hourly_rate=hourly_rate,
        currency_id=currency,
        effective_start_date=start_date,
        is_active=True,
    )
    unsaved.annual_salary = compute_compensation_annual_salary(unsaved, employee=employee)
    return unsaved


def persisted_compensation_or_none(compensation):
    if not compensation:
        return None

    compensation_id = getattr(compensation, "id", None)
    if not compensation_id:
        return None

    if not EmployeeCompensation.objects.filter(pk=compensation_id).exists():
        return None

    return compensation


def get_employee_base_amount(compensation, hours_worked=Decimal("0.00")):
    if not compensation:
        return Decimal("0.00")
    if compensation.pay_type == PayType.HOURLY:
        return ((compensation.hourly_rate or Decimal("0.00")) * hours_worked).quantize(CENT)
    if compensation.pay_type == PayType.DAILY:
        return (compensation.daily_rate or compensation.base_amount or Decimal("0.00")).quantize(CENT)
    return (compensation.base_amount or Decimal("0.00")).quantize(CENT)


def annualize_basic_salary(basic_salary, employee=None, compensation=None):
    """Resolve annual salary from compensation when available."""
    if compensation is not None:
        return get_compensation_annual_salary(compensation, employee=employee)
    if employee is not None:
        metadata = employee.get_current_payroll_metadata()
        if metadata.get("annual_salary") is not None:
            return Decimal(str(metadata["annual_salary"] or 0)).quantize(CENT)
    return (basic_salary * Decimal("12.00")).quantize(CENT)


def get_target_amount(source, *, basic_salary, gross_pay, taxable_income, annual_salary):
    mapping = {
        TargetAmountSource.BASIC_SALARY: basic_salary,
        TargetAmountSource.GROSS_PAY: gross_pay,
        TargetAmountSource.TAXABLE_INCOME: taxable_income,
        TargetAmountSource.ANNUAL_SALARY: annual_salary,
    }
    return mapping.get(source, gross_pay) or Decimal("0.00")


def get_bracket_target_amount(
    source,
    *,
    basic_salary,
    gross_pay,
    taxable_income,
    annual_salary,
    periods_per_year=None,
):
    """Salary basis for bracket min/max checks.

    Annual brackets use current gross pay annualized so they stay aligned with
    formulas such as ``(gross * 12 - threshold) / 12``.
    """
    if source == TargetAmountSource.ANNUAL_SALARY:
        pp = Decimal(str(periods_per_year or 12))
        if pp <= 0:
            pp = Decimal("12")
        return (Decimal(gross_pay or 0) * pp).quantize(CENT)
    return get_target_amount(
        source,
        basic_salary=basic_salary,
        gross_pay=gross_pay,
        taxable_income=taxable_income,
        annual_salary=annual_salary,
    )


def build_payroll_v2_formula_context(
    *,
    basic_salary,
    gross_pay,
    taxable_income,
    annual_salary,
    deductions=None,
    periods_per_year=None,
):
    """Map v2 payroll running totals to the shared formula evaluation context."""
    from payroll_v2.formula import build_amount_rule_context

    basic = Decimal(basic_salary or 0)
    taxable = Decimal(taxable_income or 0)
    allowances = max(Decimal("0.00"), taxable - basic).quantize(CENT)
    pp = Decimal(str(periods_per_year or 12))
    ctx = build_amount_rule_context(
        gross=gross_pay,
        basic=basic_salary,
        allowances=allowances,
        deductions=deductions or Decimal("0.00"),
        periods_per_year=periods_per_year,
        annual_salary=annual_salary,
    )
    ctx["taxable_gross"] = taxable.quantize(CENT)
    gross_d = Decimal(gross_pay or 0)
    if gross_d > 0 and pp > 0:
        ctx["annual"] = (gross_d * pp).quantize(CENT)
    return ctx


def _apply_line_to_running_payroll_state(
    *,
    line_type,
    is_taxable,
    amount,
    gross_pay,
    taxable_income,
    running_deductions,
):
    gross = gross_pay
    taxable = taxable_income
    deductions = running_deductions
    if line_type == LineType.EARNING:
        gross += amount
    if is_taxable:
        taxable += amount
    if line_type in (LineType.DEDUCTION, LineType.TAX, LineType.BENEFIT):
        deductions += amount
    return gross, taxable, deductions


def _assignment_generation_sort_key(assignment: EmployeePayrollItem):
    item = assignment.payroll_item
    return (
        LINE_TYPE_GENERATION_ORDER.get(item.line_type, 99),
        assignment.priority,
        item.priority,
        item.name or "",
    )


def _effective_catalog_rules(payroll_item, *, start_date, end_date):
    return sorted(
        [rule for rule in payroll_item.rules.all() if rule.is_effective_for(start_date, end_date)],
        key=lambda rule: (
            _payroll_v2_rule_min_amount_sort_key(rule),
            rule.priority,
            rule.name or "",
        ),
    )


def _create_catalog_rule_line_item(
    *,
    employee_item,
    payroll_item,
    rule,
    amount,
    target,
    generated_by,
):
    return PayrollLineItem.objects.create(
        payroll_employee_item=employee_item,
        payroll_item=payroll_item,
        payroll_item_rule=rule,
        line_type=payroll_item.line_type,
        name=payroll_item.name,
        code=payroll_item.code,
        amount=amount,
        calculation_type=rule.calculation_type,
        target_amount_source=rule.target_amount_source,
        is_taxable=payroll_item.is_taxable,
        is_recurring=True,
        frequency=Frequency.MONTHLY,
        source_type="PayrollItemRule",
        source_id=str(rule.id),
        metadata={
            "rule_name": rule.name,
            "target_amount": str(target),
        },
        created_by=generated_by,
        updated_by=generated_by,
    )


def _apply_catalog_item_to_employee(
    *,
    employee_item,
    payroll_item,
    assignment=None,
    basic_salary,
    gross_pay,
    taxable_income,
    annual_salary,
    running_deductions,
    periods_per_year,
    pay_period_start,
    pay_period_end,
    generated_by,
):
    """Generate line items from catalog rules or employee-specific calculation."""
    if assignment is not None and assignment.calculation_overridden:
        amount = calculate_employee_item_amount(
            assignment,
            basic_salary=basic_salary,
            gross_pay=gross_pay,
            taxable_income=taxable_income,
            annual_salary=annual_salary,
            running_deductions=running_deductions,
            periods_per_year=periods_per_year,
        )
        if amount == Decimal("0.00"):
            return gross_pay, taxable_income, running_deductions

        PayrollLineItem.objects.create(
            payroll_employee_item=employee_item,
            payroll_item=payroll_item,
            employee_payroll_item=assignment,
            line_type=payroll_item.line_type,
            name=assignment.get_name(),
            code=payroll_item.code,
            amount=amount,
            calculation_type=assignment.calculation_type,
            target_amount_source=assignment.target_amount_source,
            is_taxable=assignment.get_is_taxable(),
            is_recurring=assignment.is_recurring,
            frequency=assignment.frequency,
            source_type="EmployeePayrollItem",
            source_id=str(assignment.id),
            created_by=generated_by,
            updated_by=generated_by,
        )
        return _apply_line_to_running_payroll_state(
            line_type=payroll_item.line_type,
            is_taxable=assignment.get_is_taxable(),
            amount=amount,
            gross_pay=gross_pay,
            taxable_income=taxable_income,
            running_deductions=running_deductions,
        )

    matched_rules = _effective_catalog_rules(
        payroll_item,
        start_date=pay_period_start,
        end_date=pay_period_end,
    )
    matched_rule = _pick_matching_payroll_rule(
        matched_rules,
        basic_salary=basic_salary,
        gross_pay=gross_pay,
        taxable_income=taxable_income,
        annual_salary=annual_salary,
        periods_per_year=periods_per_year,
    )
    if matched_rule:
        amount = calculate_rule_amount_for_payroll(
            matched_rule,
            basic_salary=basic_salary,
            gross_pay=gross_pay,
            taxable_income=taxable_income,
            annual_salary=annual_salary,
            running_deductions=running_deductions,
            periods_per_year=periods_per_year,
        )
        if amount != Decimal("0.00"):
            target = get_target_amount(
                matched_rule.target_amount_source,
                basic_salary=basic_salary,
                gross_pay=gross_pay,
                taxable_income=taxable_income,
                annual_salary=annual_salary,
            )
            _create_catalog_rule_line_item(
                employee_item=employee_item,
                payroll_item=payroll_item,
                rule=matched_rule,
                amount=amount,
                target=target,
                generated_by=generated_by,
            )
            gross_pay, taxable_income, running_deductions = _apply_line_to_running_payroll_state(
                line_type=payroll_item.line_type,
                is_taxable=payroll_item.is_taxable,
                amount=amount,
                gross_pay=gross_pay,
                taxable_income=taxable_income,
                running_deductions=running_deductions,
            )
        return gross_pay, taxable_income, running_deductions

    if assignment is None:
        return gross_pay, taxable_income, running_deductions

    amount = calculate_employee_item_amount(
        assignment,
        basic_salary=basic_salary,
        gross_pay=gross_pay,
        taxable_income=taxable_income,
        annual_salary=annual_salary,
        running_deductions=running_deductions,
        periods_per_year=periods_per_year,
    )
    if amount == Decimal("0.00"):
        return gross_pay, taxable_income, running_deductions

    PayrollLineItem.objects.create(
        payroll_employee_item=employee_item,
        payroll_item=payroll_item,
        employee_payroll_item=assignment,
        line_type=payroll_item.line_type,
        name=assignment.get_name(),
        code=payroll_item.code,
        amount=amount,
        calculation_type=assignment.calculation_type,
        target_amount_source=assignment.target_amount_source,
        is_taxable=assignment.get_is_taxable(),
        is_recurring=assignment.is_recurring,
        frequency=assignment.frequency,
        source_type="EmployeePayrollItem",
        source_id=str(assignment.id),
        created_by=generated_by,
        updated_by=generated_by,
    )
    return _apply_line_to_running_payroll_state(
        line_type=payroll_item.line_type,
        is_taxable=assignment.get_is_taxable(),
        amount=amount,
        gross_pay=gross_pay,
        taxable_income=taxable_income,
        running_deductions=running_deductions,
    )


def _amount_to_pay_period(amount, target_amount_source, periods_per_year):
    """Convert annual-based rule amounts to the current pay period."""
    if target_amount_source != TargetAmountSource.ANNUAL_SALARY:
        return amount
    pp = Decimal(str(periods_per_year or 12))
    if pp <= 0:
        return amount
    return (amount / pp).quantize(CENT)


def calculate_rule_amount(rule, target_amount):
    target_amount = Decimal(target_amount or 0)
    min_amount = Decimal(rule.target_min_amount or 0)
    max_amount = Decimal(rule.target_max_amount or 0) if rule.target_max_amount is not None else Decimal(0)

    if rule.target_min_amount is not None or (rule.target_max_amount is not None and max_amount > 0):
        upper = target_amount
        if max_amount > 0:
            upper = min(target_amount, max_amount)
        base_amount = max(Decimal("0.00"), upper - min_amount)
    else:
        base_amount = target_amount

    if rule.calculation_limit is not None:
        base_amount = min(base_amount, rule.calculation_limit)

    calc = getattr(rule.calculation_type, "value", rule.calculation_type)
    calc = str(calc).strip().lower()
    if calc == CalculationType.PERCENTAGE:
        return (base_amount * (rule.value or Decimal("0.00")) / Decimal("100.00")).quantize(CENT)
    if calc == CalculationType.FLAT:
        return (rule.value or Decimal("0.00")).quantize(CENT)
    return Decimal("0.00")


def _target_amount_source_to_applies_to(source) -> str:
    if source == TargetAmountSource.BASIC_SALARY:
        return "basic"
    if source == TargetAmountSource.ANNUAL_SALARY:
        return "annual"
    if source == TargetAmountSource.TAXABLE_INCOME:
        return "taxable_gross"
    return "gross"


def _target_amount_source_to_target_salary_by(source) -> str:
    if source == TargetAmountSource.ANNUAL_SALARY:
        return "annual"
    return "per_period"


def calculate_rule_amount_for_payroll(
    rule,
    *,
    basic_salary,
    gross_pay,
    taxable_income,
    annual_salary,
    running_deductions=Decimal("0.00"),
    periods_per_year=None,
) -> Decimal:
    bracket_target = get_bracket_target_amount(
        rule.target_amount_source,
        basic_salary=basic_salary,
        gross_pay=gross_pay,
        taxable_income=taxable_income,
        annual_salary=annual_salary,
        periods_per_year=periods_per_year,
    )
    if not _rule_in_bracket(bracket_target, rule):
        return Decimal("0.00")

    if rule.calculation_type == CalculationType.FORMULA:
        from payroll_v2.formula import _evaluate_formula

        ctx = build_payroll_v2_formula_context(
            basic_salary=basic_salary,
            gross_pay=gross_pay,
            taxable_income=taxable_income,
            annual_salary=annual_salary,
            deductions=running_deductions,
            periods_per_year=periods_per_year,
        )
        amount = _evaluate_formula(getattr(rule, "formula", "") or "", ctx)
        if rule.calculation_limit is not None:
            amount = min(amount, rule.calculation_limit)
        return amount.quantize(CENT)

    calc_target = get_target_amount(
        rule.target_amount_source,
        basic_salary=basic_salary,
        gross_pay=gross_pay,
        taxable_income=taxable_income,
        annual_salary=annual_salary,
    )
    amount = calculate_rule_amount(rule, calc_target)
    return _amount_to_pay_period(amount, rule.target_amount_source, periods_per_year)


def get_payroll_v2_formula_guide() -> dict:
    from payroll_v2.formula import get_formula_guide

    return get_formula_guide()


def preview_catalog_item_formula(
    *,
    calculation_type,
    value,
    formula,
    target_amount_source,
    gross,
    basic,
    allowances=Decimal("0"),
    deductions=Decimal("0"),
    target_min_amount=None,
    target_max_amount=None,
    calculation_limit=None,
    periods_per_year=None,
    annual_salary=None,
    taxable_income=None,
) -> dict:
    from payroll_v2.formula import preview_formula_amount

    source = target_amount_source or TargetAmountSource.BASIC_SALARY
    basic_d = Decimal(str(basic))
    gross_d = Decimal(str(gross))
    taxable_d = Decimal(str(taxable_income)) if taxable_income is not None else None
    if taxable_d is not None:
        allowances_d = max(Decimal("0.00"), taxable_d - basic_d).quantize(CENT)
    else:
        allowances_d = Decimal(str(allowances or "0"))
    pp = Decimal(str(periods_per_year or 12))
    preview_annual = annual_salary
    if source == TargetAmountSource.ANNUAL_SALARY and pp > 0:
        preview_annual = (gross_d * pp).quantize(CENT)
    elif annual_salary is not None:
        preview_annual = Decimal(str(annual_salary))
    return preview_formula_amount(
        calculation_type=str(calculation_type or CalculationType.FORMULA),
        value=value or "0",
        formula=str(formula or ""),
        applies_to=_target_amount_source_to_applies_to(source),
        gross=gross_d,
        basic=basic_d,
        allowances=allowances_d,
        deductions=Decimal(str(deductions or "0")),
        target_salary_min=target_min_amount if target_min_amount is not None else "0",
        target_salary_max=target_max_amount if target_max_amount is not None else "0",
        target_salary_by=_target_amount_source_to_target_salary_by(source),
        salary_limit=calculation_limit,
        periods_per_year=periods_per_year,
        annual_salary=preview_annual,
    )


def _is_catch_all_rule(rule) -> bool:
    min_bound = Decimal(rule.target_min_amount or 0)
    max_bound = Decimal(rule.target_max_amount or 0) if rule.target_max_amount is not None else Decimal(0)
    return min_bound <= 0 and max_bound <= 0


def _rule_in_bracket(target_amount, rule) -> bool:
    """Return True when the target amount falls within the rule bracket bounds.

    Matches v1 semantics: 0 min = no lower bound, 0 max = no upper bound.
    """
    salary = Decimal(target_amount or 0)
    min_bound = Decimal(rule.target_min_amount or 0)
    max_bound = Decimal(rule.target_max_amount or 0) if rule.target_max_amount is not None else Decimal(0)
    if min_bound > 0 and salary < min_bound:
        return False
    if max_bound > 0 and salary > max_bound:
        return False
    return True


def _pick_matching_payroll_rule(
    rules,
    *,
    basic_salary,
    gross_pay,
    taxable_income,
    annual_salary,
    periods_per_year=None,
):
    """Pick the first bracket-matching rule, falling back to a catch-all rule."""
    if not rules:
        return None

    sorted_rules = sorted(
        rules,
        key=lambda rule: (
            _payroll_v2_rule_min_amount_sort_key(rule),
            getattr(rule, "priority", 100),
            str(getattr(rule, "name", "")),
        ),
    )
    catch_all = None
    for rule in sorted_rules:
        if _is_catch_all_rule(rule):
            catch_all = rule
            continue
        target = get_bracket_target_amount(
            rule.target_amount_source,
            basic_salary=basic_salary,
            gross_pay=gross_pay,
            taxable_income=taxable_income,
            annual_salary=annual_salary,
            periods_per_year=periods_per_year,
        )
        if _rule_in_bracket(target, rule):
            return rule
    return catch_all


def _payroll_v2_rule_min_amount_sort_key(rule):
    min_amount = rule.target_min_amount
    if min_amount is None:
        return Decimal("0")
    return min_amount


def preview_item_rules(
    *,
    rules,
    basic_salary,
    gross_pay=None,
    taxable_income=None,
    annual_salary=None,
    running_deductions=Decimal("0.00"),
    periods_per_year=None,
):
    """Preview bracket rules using the first matching rule (v1-compatible behavior)."""
    basic = Decimal(str(basic_salary or "0"))
    gross = Decimal(str(gross_pay if gross_pay is not None else basic_salary or "0"))
    taxable = Decimal(str(taxable_income if taxable_income is not None else gross))
    annual = Decimal(str(annual_salary if annual_salary is not None else basic * Decimal("12")))
    pp = Decimal(str(periods_per_year)) if periods_per_year is not None else None

    sorted_rules = sorted(
        rules,
        key=lambda rule: (
            _payroll_v2_rule_min_amount_sort_key(rule),
            getattr(rule, "priority", 100),
            str(getattr(rule, "id", "")),
        ),
    )
    matched_rule = _pick_matching_payroll_rule(
        sorted_rules,
        basic_salary=basic,
        gross_pay=gross,
        taxable_income=taxable,
        annual_salary=annual,
        periods_per_year=pp,
    )
    breakdown = []

    for rule in sorted_rules:
        bracket_target = get_bracket_target_amount(
            rule.target_amount_source,
            basic_salary=basic,
            gross_pay=gross,
            taxable_income=taxable,
            annual_salary=annual,
            periods_per_year=pp,
        )
        in_bracket = _rule_in_bracket(bracket_target, rule)
        amount = (
            calculate_rule_amount_for_payroll(
                rule,
                basic_salary=basic,
                gross_pay=gross,
                taxable_income=taxable,
                annual_salary=annual,
                running_deductions=running_deductions,
                periods_per_year=pp,
            )
            if in_bracket
            else Decimal("0.00")
        )

        target_source = getattr(rule, "target_amount_source", TargetAmountSource.BASIC_SALARY)
        applies_to = _target_amount_source_to_applies_to(target_source)
        target_salary_by = _target_amount_source_to_target_salary_by(target_source)

        breakdown.append(
            {
                "rule_id": str(getattr(rule, "id", "")),
                "calculation_type": rule.calculation_type,
                "applies_to": applies_to,
                "target_salary_min": str(rule.target_min_amount or "0"),
                "target_salary_max": str(rule.target_max_amount or "0"),
                "target_salary_by": target_salary_by,
                "matched": rule is matched_rule,
                "in_bracket": in_bracket,
                "amount": str(amount.quantize(CENT)),
            }
        )

    effective = Decimal("0.00")
    if matched_rule:
        effective = calculate_rule_amount_for_payroll(
            matched_rule,
            basic_salary=basic,
            gross_pay=gross,
            taxable_income=taxable,
            annual_salary=annual,
            running_deductions=running_deductions,
            periods_per_year=pp,
        )

    return {
        "amount": str(effective.quantize(CENT)),
        "matched": bool(matched_rule),
        "breakdown": breakdown,
    }


def _rule_field_decimal(value, default=None):
    if value is None or value == "":
        return default
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def generate_payroll_item_rule_name(data: dict) -> str:
    calc_type = data.get("calculation_type") or CalculationType.FLAT
    value = _rule_field_decimal(data.get("value"), Decimal("0"))
    formula = (data.get("formula") or "").strip()
    target_source = data.get("target_amount_source") or TargetAmountSource.BASIC_SALARY
    min_amt = _rule_field_decimal(data.get("target_min_amount"))
    max_amt = _rule_field_decimal(data.get("target_max_amount"))

    source_label = dict(TargetAmountSource.choices).get(target_source, str(target_source))

    if calc_type == CalculationType.FLAT:
        calc_label = f"Flat {value.quantize(CENT)}"
    elif calc_type == CalculationType.PERCENTAGE:
        calc_label = f"{value}%"
    else:
        snippet = formula[:40] + ("…" if len(formula) > 40 else "")
        calc_label = f"Formula {snippet}" if snippet else "Formula"

    min_num = min_amt if min_amt is not None else Decimal("0")
    max_num = max_amt if max_amt is not None else Decimal("0")
    if (min_amt is None or min_num <= 0) and (max_amt is None or max_num <= 0):
        bracket = "All amounts"
    elif min_amt is None or min_num <= 0:
        bracket = f"Up to {max_amt.quantize(CENT)}"
    elif max_amt is None or max_num <= 0:
        bracket = f"{min_amt.quantize(CENT)}+"
    else:
        bracket = f"{min_amt.quantize(CENT)} – {max_amt.quantize(CENT)}"

    return f"{calc_label} · {source_label} · {bracket}"[:120]


def build_preview_item_rule_objects(validated_items: list):
    objects = []
    for item in validated_items:
        objects.append(
            PayrollCatalogItemRule(
                name=generate_payroll_item_rule_name(item),
                calculation_type=item.get("calculation_type") or CalculationType.FLAT,
                value=item.get("value") or Decimal("0"),
                formula=item.get("formula") or "",
                target_amount_source=item.get("target_amount_source") or TargetAmountSource.BASIC_SALARY,
                target_min_amount=item.get("target_min_amount"),
                target_max_amount=item.get("target_max_amount"),
                calculation_limit=item.get("calculation_limit"),
                priority=item.get("priority") or 100,
                is_active=item.get("is_active", True),
            )
        )
    return objects


def calculate_employee_item_amount(
    item,
    *,
    basic_salary,
    gross_pay,
    taxable_income,
    annual_salary,
    running_deductions=Decimal("0.00"),
    periods_per_year=None,
):
    if item.calculation_type == CalculationType.FORMULA:
        from payroll_v2.formula import _evaluate_formula

        ctx = build_payroll_v2_formula_context(
            basic_salary=basic_salary,
            gross_pay=gross_pay,
            taxable_income=taxable_income,
            annual_salary=annual_salary,
            deductions=running_deductions,
            periods_per_year=periods_per_year,
        )
        amount = _evaluate_formula(item.formula or "", ctx)
        if item.calculation_limit is not None:
            amount = min(amount, item.calculation_limit)
        return amount.quantize(CENT)

    target = get_target_amount(
        item.target_amount_source,
        basic_salary=basic_salary,
        gross_pay=gross_pay,
        taxable_income=taxable_income,
        annual_salary=annual_salary,
    )
    base_amount = min(target, item.calculation_limit) if item.calculation_limit is not None else target

    if item.calculation_type == CalculationType.PERCENTAGE:
        amount = (base_amount * (item.value or Decimal("0.00")) / Decimal("100.00")).quantize(CENT)
    elif item.calculation_type == CalculationType.FLAT:
        amount = (item.value or Decimal("0.00")).quantize(CENT)
    else:
        return Decimal("0.00")
    return _amount_to_pay_period(amount, item.target_amount_source, periods_per_year)


def default_employee_payroll_item_calculation(*, payroll_item: PayrollCatalogItem) -> dict:
    return {
        "calculation_type": CalculationType.FLAT,
        "value": Decimal("0.0000"),
        "formula": "",
        "target_amount_source": TargetAmountSource.BASIC_SALARY,
        "calculation_limit": None,
        "calculation_overridden": False,
        "priority": payroll_item.priority,
    }


def catalog_item_has_effective_rules(payroll_item, *, start_date, end_date) -> bool:
    for rule in payroll_item.rules.all():
        if rule.is_effective_for(start_date, end_date):
            return True
    return False


@transaction.atomic
def revert_employee_payroll_item_calculation(assignment: EmployeePayrollItem, *, actor=None) -> EmployeePayrollItem:
    if not assignment.calculation_overridden:
        raise ValueError("This employee item is already using catalog calculation rules.")

    defaults = default_employee_payroll_item_calculation(payroll_item=assignment.payroll_item)
    for field, value in defaults.items():
        setattr(assignment, field, value)
    assignment.updated_by = actor
    assignment.save(
        update_fields=[
            "calculation_type",
            "value",
            "formula",
            "target_amount_source",
            "calculation_limit",
            "calculation_overridden",
            "priority",
            "updated_by",
            "updated_at",
        ]
    )
    return assignment


def _line_item_column_key(line: PayrollLineItem) -> str:
    if line.payroll_item_id:
        return f"item:{line.payroll_item_id}"
    code = (line.code or "").strip()
    if code:
        return f"code:{code.lower()}"
    return f"line:{line.id}"


def snapshot_table_view(table_view: PayrollTableView | None) -> dict:
    if table_view is None:
        return {}
    return {
        "id": str(table_view.id),
        "name": table_view.name,
        "columns": table_view.columns or [],
        "filters": table_view.filters or {},
        "sorting": table_view.sorting or [],
    }


def snapshot_payslip_template(template: PayrollPayslipTemplate | None) -> dict:
    if template is None:
        return {}
    return {
        "id": str(template.id),
        "name": template.name,
        "layout": template.layout or {},
    }


def validate_payroll_settings_configured() -> None:
    from payroll_v2.settings_services import get_tenant_payroll_settings

    settings = get_tenant_payroll_settings()
    if settings.transaction_type_id is None:
        raise ValueError("Configure a payroll transaction type in Payroll settings before continuing.")
    tx_type = settings.transaction_type
    if not tx_type.is_active:
        raise ValueError("The configured payroll transaction type is inactive.")
    if tx_type.transaction_category != "expense":
        raise ValueError("Payroll transaction type must be an expense type.")


def validate_payroll_disbursement_account(run: PayrollRunRecord) -> None:
    if not run.bank_account_id:
        raise ValueError("Select a disbursement bank account before submitting this payroll run.")

    bank_account = run.bank_account
    if bank_account.ledger_account_id is None:
        raise ValueError("The disbursement account must be linked to a ledger account.")

    if run.currency_id and bank_account.currency_id != run.currency_id:
        raise ValueError("Bank account currency must match the payroll run currency.")

    from accounting.services.posting import recalculate_bank_account_current_balance

    net = run.net_pay_total or Decimal("0.00")
    if net <= 0:
        return

    available_balance = recalculate_bank_account_current_balance(bank_account)
    if net > available_balance:
        raise ValueError(
            f"Insufficient balance in {bank_account.account_name}. "
            f"Available: {available_balance:,.2f}, payroll net pay: {net:,.2f}."
        )


@transaction.atomic
def create_payroll_v2_run(
    *,
    payroll_number: str,
    pay_schedule,
    pay_period_start=None,
    pay_period_end=None,
    payment_date=None,
    period_name: str | None = None,
    currency=None,
    bank_account=None,
    table_view=None,
    payslip_template=None,
    notes: str = "",
    payroll_type=None,
    created_by=None,
    updated_by=None,
) -> PayrollRunRecord:
    from payroll_v2.schedule_services import derive_next_period, get_pay_schedule

    if isinstance(pay_schedule, PaySchedule):
        schedule = (
            pay_schedule
            if hasattr(pay_schedule, "currency")
            else get_pay_schedule(pay_schedule.id)
        )
    else:
        schedule = get_pay_schedule(pay_schedule)

    if schedule is None:
        raise ValueError("Pay schedule not found. Choose an active schedule or create one in Payroll settings.")

    if not schedule.is_active:
        raise ValueError("Selected pay schedule is inactive.")

    derived = derive_next_period(schedule)
    start = pay_period_start or derived.start_date
    end = pay_period_end or derived.end_date
    paid_on = payment_date or derived.payment_date
    label = (period_name or derived.name).strip() or derived.name

    if start > end:
        raise ValueError("Pay period start must be on or before pay period end.")

    period, created = PayrollPeriod.objects.get_or_create(
        schedule=schedule,
        start_date=start,
        end_date=end,
        defaults={
            "name": label,
            "payment_date": paid_on,
            "created_by": created_by,
            "updated_by": updated_by,
        },
    )
    if not created:
        updates = []
        if period.name != label:
            period.name = label
            updates.append("name")
        if period.payment_date != paid_on:
            period.payment_date = paid_on
            updates.append("payment_date")
        if updates:
            if updated_by is not None:
                period.updated_by = updated_by
                updates.append("updated_by")
            updates.append("updated_at")
            period.save(update_fields=updates)

    resolved_currency = currency or schedule.currency
    run_kwargs = {
        "payroll_number": payroll_number,
        "pay_schedule": schedule,
        "payroll_period": period,
        "pay_period_start": start,
        "pay_period_end": end,
        "payment_date": paid_on,
        "currency": resolved_currency,
        "bank_account": bank_account,
        "table_view": table_view,
        "payslip_template": payslip_template,
        "notes": notes or "",
        "created_by": created_by,
        "updated_by": updated_by,
    }
    if payroll_type is not None:
        run_kwargs["payroll_type"] = payroll_type

    return PayrollRunRecord.objects.create(**run_kwargs)


@transaction.atomic
def generate_payroll(payroll_run, employees, generated_by=None, replace_existing=True, table_view=None):
    if not payroll_run.can_generate:
        raise ValueError("Payroll can only be generated while in draft/processing status.")

    selected_view = table_view or payroll_run.table_view
    if selected_view is None:
        selected_view = PayrollTableView.objects.filter(is_default=True, active=True).first()
    payroll_run.table_view = selected_view
    payroll_run.table_view_snapshot = snapshot_table_view(selected_view)

    template = payroll_run.payslip_template or PayrollPayslipTemplate.objects.filter(
        is_default=True, active=True
    ).first()
    payroll_run.payslip_template = template
    payroll_run.payslip_template_snapshot = snapshot_payslip_template(template)

    payroll_run.status = PayrollStatus.PROCESSING
    payroll_run.save(
        update_fields=[
            "status",
            "table_view",
            "table_view_snapshot",
            "payslip_template",
            "payslip_template_snapshot",
            "updated_at",
        ]
    )

    if replace_existing:
        payroll_run.employee_items.all().delete()

    standard_items = list(
        PayrollCatalogItem.objects.prefetch_related("rules")
        .filter(is_active=True)
        .order_by("priority", "name")
    )

    skipped_employees = []

    for employee in employees:
        compensation = resolve_employee_compensation(
            employee,
            payroll_run.pay_period_start,
            payroll_run.pay_period_end,
        )
        if not getattr(compensation, "id", None):
            skipped_employees.append(str(employee.id))
            continue
        if not compensation_has_valid_amount(compensation):
            skipped_employees.append(str(employee.id))
            continue

        basic_salary = get_employee_base_amount(compensation)
        annual_salary = annualize_basic_salary(basic_salary, employee, compensation=compensation)
        from payroll_v2.schedule_services import periods_per_year_for_schedule

        pay_schedule = employee.pay_schedule if employee.pay_schedule_id else payroll_run.pay_schedule
        periods_per_year = periods_per_year_for_schedule(pay_schedule)

        persisted_compensation = persisted_compensation_or_none(compensation)

        employee_item = PayrollEmployeeItem.objects.create(
            payroll=payroll_run,
            employee=employee,
            compensation=persisted_compensation,
            basic_salary=basic_salary,
            gross_pay=basic_salary,
            taxable_income=basic_salary,
            created_by=generated_by,
            updated_by=generated_by,
        )

        gross_pay = basic_salary
        taxable_income = basic_salary
        running_deductions = Decimal("0.00")

        if basic_salary > 0:
            PayrollLineItem.objects.create(
                payroll_employee_item=employee_item,
                line_type=LineType.EARNING,
                name="Basic Salary",
                code="BASIC_SALARY",
                amount=basic_salary,
                calculation_type=CalculationType.FLAT,
                target_amount_source=TargetAmountSource.BASIC_SALARY,
                is_taxable=True,
                is_recurring=True,
                frequency=Frequency.MONTHLY,
                source_type="EmployeeCompensation",
                source_id=str(getattr(compensation, "id", "") or ""),
                created_by=generated_by,
                updated_by=generated_by,
            )

        assignments = list(
            EmployeePayrollItem.objects.select_related("payroll_item")
            .prefetch_related("payroll_item__rules")
            .filter(employee=employee, is_active=True, payroll_item__is_active=True)
            .exclude(source_type=DeductionSourceType.SALARY_ADVANCE)
        )

        work_units = []
        for item in standard_items:
            rules = _effective_catalog_rules(
                item,
                start_date=payroll_run.pay_period_start,
                end_date=payroll_run.pay_period_end,
            )
            if not rules:
                continue
            work_units.append(
                {
                    "sort_key": (
                        LINE_TYPE_GENERATION_ORDER.get(item.line_type, 99),
                        item.priority,
                        item.name or "",
                    ),
                    "kind": "catalog",
                    "item": item,
                    "assignment": None,
                }
            )

        for assignment in assignments:
            if not assignment.is_effective_for(payroll_run.pay_period_start, payroll_run.pay_period_end):
                continue
            item = assignment.payroll_item
            if (
                _effective_catalog_rules(
                    item,
                    start_date=payroll_run.pay_period_start,
                    end_date=payroll_run.pay_period_end,
                )
                and not assignment.calculation_overridden
            ):
                continue
            work_units.append(
                {
                    "sort_key": _assignment_generation_sort_key(assignment),
                    "kind": "assignment",
                    "item": item,
                    "assignment": assignment,
                }
            )

        work_units.sort(key=lambda unit: unit["sort_key"])

        for unit in work_units:
            gross_pay, taxable_income, running_deductions = _apply_catalog_item_to_employee(
                employee_item=employee_item,
                payroll_item=unit["item"],
                assignment=unit["assignment"],
                basic_salary=basic_salary,
                gross_pay=gross_pay,
                taxable_income=taxable_income,
                annual_salary=annual_salary,
                running_deductions=running_deductions,
                periods_per_year=periods_per_year,
                pay_period_start=payroll_run.pay_period_start,
                pay_period_end=payroll_run.pay_period_end,
                generated_by=generated_by,
            )

        gross_pay, taxable_income, running_deductions = _apply_salary_advance_recurring_deductions(
            employee_item=employee_item,
            employee=employee,
            pay_period_start=payroll_run.pay_period_start,
            pay_period_end=payroll_run.pay_period_end,
            gross_pay=gross_pay,
            taxable_income=taxable_income,
            running_deductions=running_deductions,
            generated_by=generated_by,
        )

        installments = _installments_for_employee_in_period(
            employee=employee,
            payroll_period=payroll_run.payroll_period,
        )
        gross_pay, taxable_income, running_deductions = _create_installment_deduction_lines(
            employee_item=employee_item,
            installments=installments,
            gross_pay=gross_pay,
            taxable_income=taxable_income,
            running_deductions=running_deductions,
            generated_by=generated_by,
        )

        employee_item.recalculate_totals()

    payroll_run.recalculate_totals()
    payroll_run.status = PayrollStatus.DRAFT
    payroll_run.save(update_fields=["status", "updated_at"])
    payroll_run.generation_meta = {
        "skipped_employee_ids": skipped_employees,
        "skipped_count": len(skipped_employees),
    }
    return payroll_run


@transaction.atomic
def submit_payroll_for_approval(payroll_run, user=None):
    if payroll_run.status != PayrollStatus.DRAFT:
        raise ValueError("Only draft payroll runs can be submitted.")
    if not payroll_run.employee_items.exists():
        raise ValueError("Cannot submit a payroll run with no employee items.")
    _validate_run_obligation_deduction_limits(payroll_run)
    validate_payroll_settings_configured()
    validate_payroll_disbursement_account(payroll_run)
    payroll_run.status = PayrollStatus.PENDING_APPROVAL
    payroll_run.updated_by = user
    payroll_run.save(update_fields=["status", "updated_by", "updated_at"])
    return payroll_run


@transaction.atomic
def approve_payroll(payroll_run, user=None):
    if payroll_run.status != PayrollStatus.PENDING_APPROVAL:
        raise ValueError("Only pending payroll runs can be approved.")
    payroll_run.status = PayrollStatus.APPROVED
    payroll_run.approved_by = user
    payroll_run.approved_at = timezone.now()
    payroll_run.updated_by = user
    payroll_run.save(update_fields=["status", "approved_by", "approved_at", "updated_by", "updated_at"])
    return payroll_run


@transaction.atomic
def mark_payroll_paid(payroll_run, user=None):
    if payroll_run.status != PayrollStatus.APPROVED:
        raise ValueError("Only approved payroll runs can be marked paid.")
    validate_payroll_settings_configured()
    validate_payroll_disbursement_account(payroll_run)

    from .accounting_integration import post_payroll_v2_run_to_ledger

    batch = post_payroll_v2_run_to_ledger(payroll_run, actor=user)

    from employee_disbursements.services.records import create_payroll_disbursement_records

    create_payroll_disbursement_records(
        payroll_run,
        journal_entry=getattr(batch, "journal_entry", None),
        actor=user,
    )

    if payroll_run.payroll_period_id:
        period = payroll_run.payroll_period
        if not period.is_closed:
            period.is_closed = True
            if user is not None:
                period.updated_by = user
            period.save(update_fields=["is_closed", "updated_by", "updated_at"])

    payroll_run.status = PayrollStatus.PAID
    payroll_run.paid_at = timezone.now()
    payroll_run.updated_by = user
    payroll_run.save(update_fields=["status", "paid_at", "updated_by", "updated_at"])
    payroll_run.employee_items.update(payment_status=PaymentStatus.PAID)

    apply_deduction_installments_for_run(payroll_run, actor=user)
    apply_salary_advance_repayments_for_run(payroll_run, actor=user)

    from .paid_table_snapshot import capture_payroll_paid_table_snapshot

    capture_payroll_paid_table_snapshot(payroll_run)

    from .live_row_lifecycle import purge_paid_live_rows_if_enabled

    purge_paid_live_rows_if_enabled(payroll_run)
    return payroll_run


@transaction.atomic
def revert_payroll_to_draft(payroll_run, user=None):
    """Force a run back to draft regardless of current status."""
    if payroll_run.status == PayrollStatus.DRAFT:
        return payroll_run

    if payroll_run.status == PayrollStatus.PAID:
        from .accounting_integration import reverse_payroll_v2_run_posting

        reverse_payroll_v2_run_posting(payroll_run, actor=user)

        from employee_disbursements.enums import DisbursementSourceType
        from employee_disbursements.services.records import revert_disbursement_records_for_source

        revert_disbursement_records_for_source(
            DisbursementSourceType.PAYROLL,
            payroll_run.id,
            actor=user,
        )

        from .live_row_lifecycle import restore_payroll_live_rows_from_snapshot

        restore_payroll_live_rows_from_snapshot(payroll_run, actor=user)
        revert_deduction_installments_for_run(payroll_run, actor=user)
        revert_salary_advance_repayments_for_run(payroll_run, actor=user)

    payroll_run.status = PayrollStatus.DRAFT
    payroll_run.approved_by = None
    payroll_run.approved_at = None
    payroll_run.paid_at = None
    payroll_run.paid_table_snapshot = {}
    payroll_run.updated_by = user
    payroll_run.save(
        update_fields=[
            "status",
            "approved_by",
            "approved_at",
            "paid_at",
            "paid_table_snapshot",
            "updated_by",
            "updated_at",
        ],
    )

    if payroll_run.payroll_period_id:
        period = payroll_run.payroll_period
        if period.is_closed:
            period.is_closed = False
            if user is not None:
                period.updated_by = user
            period.save(update_fields=["is_closed", "updated_by", "updated_at"])

    if payroll_run.employee_items.exists():
        payroll_run.employee_items.update(payment_status=PaymentStatus.UNPAID)

    return payroll_run



def _period_window_for_schedule(*, start_period, end_period, requested_installments):
    if not start_period:
        raise ValueError("A start payroll period is required to generate a deduction schedule.")

    qs = PayrollPeriod.objects.filter(schedule_id=start_period.schedule_id, start_date__gte=start_period.start_date).order_by(
        "start_date"
    )

    if end_period and end_period.schedule_id == start_period.schedule_id:
        qs = qs.filter(start_date__lte=end_period.start_date)
    periods = list(qs)
    if not periods:
        raise ValueError("No payroll periods found for deduction schedule generation.")

    if requested_installments and requested_installments > 0:
        periods = periods[:requested_installments]
    return periods


def _is_probable_legacy_full_amount_equal_split_schedule(
    *,
    schedule: PayrollDeductionSchedule,
    advance: SalaryAdvance,
) -> bool:
    if advance.repayment_method != SalaryAdvanceRepaymentMethod.EQUAL_SPLIT:
        return False

    installments = list(
        schedule.installments.select_related("payroll_period").order_by("payroll_period__start_date", "id")
    )
    requested_installments = max(1, int(advance.number_of_installments or 1))
    if len(installments) <= 1:
        return False
    if any(installment.status == PayrollDeductionInstallmentStatus.APPLIED for installment in installments):
        return False

    # If this equal-split schedule has the wrong installment count, it needs rebuilding.
    if requested_installments > 1 and len(installments) != requested_installments:
        return True

    total_amount = to_money(schedule.total_amount)
    first_amount = to_money(installments[0].scheduled_amount)
    remaining_amount = to_money(
        sum((to_money(installment.scheduled_amount) for installment in installments[1:]), Decimal("0.00"))
    )
    if first_amount != total_amount:
        return False
    if remaining_amount != Decimal("0.00"):
        return False
    if requested_installments > 1 and to_money(schedule.scheduled_amount) != total_amount:
        return False
    return True


def _repair_legacy_equal_split_salary_advance_schedules(*, employee):
    schedules = list(
        PayrollDeductionSchedule.objects.select_related("start_period", "end_period").filter(
            employee=employee,
            source_type=DeductionSourceType.SALARY_ADVANCE,
            status__in=[
                PayrollDeductionScheduleStatus.PLANNED,
                PayrollDeductionScheduleStatus.PARTIALLY_APPLIED,
                PayrollDeductionScheduleStatus.DEFERRED,
                PayrollDeductionScheduleStatus.ADJUSTED,
            ],
        )
    )
    if not schedules:
        return

    source_ids = sorted({str(schedule.source_id) for schedule in schedules if schedule.source_id})
    advances_by_id = {
        str(advance.id): advance
        for advance in SalaryAdvance.objects.filter(id__in=source_ids)
    }

    for schedule in schedules:
        advance = advances_by_id.get(str(schedule.source_id))
        if not advance:
            continue
        if not _is_probable_legacy_full_amount_equal_split_schedule(schedule=schedule, advance=advance):
            continue

        create_or_replace_deduction_schedule(
            employee=schedule.employee,
            source_type=DeductionSourceType.SALARY_ADVANCE,
            source_id=advance.id,
            total_amount=schedule.total_amount,
            start_period=schedule.start_period,
            end_period=schedule.end_period,
            number_of_installments=max(1, int(advance.number_of_installments or 1)),
            fixed_installment_amount=None,
            actor=None,
        )


def _ensure_salary_advance_installment_for_period(*, employee, payroll_period):
    if not payroll_period:
        return

    schedules = list(
        PayrollDeductionSchedule.objects.select_related("start_period", "end_period").filter(
            employee=employee,
            source_type=DeductionSourceType.SALARY_ADVANCE,
            status__in=[
                PayrollDeductionScheduleStatus.PLANNED,
                PayrollDeductionScheduleStatus.PARTIALLY_APPLIED,
                PayrollDeductionScheduleStatus.DEFERRED,
                PayrollDeductionScheduleStatus.ADJUSTED,
            ],
        )
    )
    if not schedules:
        return

    advances_by_id = {
        str(advance.id): advance
        for advance in SalaryAdvance.objects.filter(id__in=[str(s.source_id) for s in schedules if s.source_id])
    }

    for schedule in schedules:
        advance = advances_by_id.get(str(schedule.source_id))
        if not advance:
            continue

        start_period = getattr(schedule, "start_period", None)
        start_period_id = getattr(schedule, "start_period_id", None) or getattr(start_period, "id", None)
        start_schedule_id = getattr(start_period, "schedule_id", None)
        current_schedule_id = getattr(payroll_period, "schedule_id", None)

        if not start_period_id or not start_schedule_id or current_schedule_id != start_schedule_id:
            continue
        payroll_start_date = getattr(payroll_period, "start_date", None)
        start_date = getattr(start_period, "start_date", None)
        if not payroll_start_date or not start_date or payroll_start_date < start_date:
            continue
        end_period = getattr(schedule, "end_period", None)
        end_period_id = getattr(schedule, "end_period_id", None) or getattr(end_period, "id", None)
        end_date = getattr(end_period, "start_date", None)
        if end_period_id and end_date and payroll_start_date > end_date:
            continue

        target_installments = max(1, int(advance.number_of_installments or 1))
        existing_installments_qs = schedule.installments.order_by("payroll_period__start_date", "id")
        existing_count = existing_installments_qs.count()
        if existing_count >= target_installments:
            continue
        if existing_installments_qs.filter(payroll_period=payroll_period).exists():
            continue

        applied_total = to_money(
            sum(
                (
                    installment.actual_amount
                    for installment in existing_installments_qs.filter(status=PayrollDeductionInstallmentStatus.APPLIED)
                ),
                Decimal("0.00"),
            )
        )
        planned_total = to_money(
            sum(
                (
                    installment.scheduled_amount
                    for installment in existing_installments_qs.exclude(status=PayrollDeductionInstallmentStatus.APPLIED)
                ),
                Decimal("0.00"),
            )
        )
        unallocated = max(Decimal("0.00"), to_money(schedule.total_amount) - applied_total - planned_total)
        if unallocated <= Decimal("0.00"):
            continue

        if (
            advance.repayment_method == SalaryAdvanceRepaymentMethod.FIXED_INSTALLMENT
            and to_money(advance.installment_amount) > Decimal("0.00")
        ):
            periodic_amount = to_money(advance.installment_amount)
        else:
            periodic_amount = calculate_equal_installment_amount(
                total_amount=to_money(schedule.total_amount),
                installments=target_installments,
            )

        remaining_slots = target_installments - existing_count
        if remaining_slots <= 1:
            next_amount = unallocated
        else:
            next_amount = min(periodic_amount, unallocated)

        if next_amount <= Decimal("0.00"):
            continue

        PayrollDeductionInstallment.objects.create(
            deduction_schedule=schedule,
            payroll_period=payroll_period,
            scheduled_amount=next_amount,
            actual_amount=Decimal("0.00"),
            status=PayrollDeductionInstallmentStatus.PLANNED,
            created_by=None,
            updated_by=None,
        )
        _refresh_deduction_schedule_snapshot(schedule)


def _get_or_create_system_deduction_item(*, code, name, priority=250):
    item, _ = PayrollCatalogItem.objects.get_or_create(
        code=code,
        defaults={
            "name": name,
            "line_type": LineType.DEDUCTION,
            "is_taxable": False,
            "priority": priority,
            "is_active": True,
            "description": f"System-managed deduction for {name}.",
        },
    )
    return item


def _reset_orphaned_applied_installments_for_period(*, employee, payroll_period):
    orphaned_installments = list(
        PayrollDeductionInstallment.objects.select_related("deduction_schedule").filter(
            deduction_schedule__employee=employee,
            deduction_schedule__status__in=[
                PayrollDeductionScheduleStatus.PLANNED,
                PayrollDeductionScheduleStatus.PARTIALLY_APPLIED,
                PayrollDeductionScheduleStatus.DEFERRED,
                PayrollDeductionScheduleStatus.ADJUSTED,
            ],
            payroll_period=payroll_period,
            status=PayrollDeductionInstallmentStatus.APPLIED,
            payroll_line__isnull=True,
        )
    )
    if not orphaned_installments:
        return

    touched_schedule_ids = set()
    for installment in orphaned_installments:
        installment.actual_amount = Decimal("0.00")
        installment.status = PayrollDeductionInstallmentStatus.PLANNED
        installment.applied_at = None
        installment.updated_by = None
        installment.save(
            update_fields=[
                "actual_amount",
                "status",
                "applied_at",
                "updated_by",
                "updated_at",
            ]
        )
        touched_schedule_ids.add(installment.deduction_schedule_id)

    for schedule in PayrollDeductionSchedule.objects.filter(id__in=touched_schedule_ids):
        _recompute_schedule_remaining_and_status(schedule, actor=None)


def _installments_for_employee_in_period(*, employee, payroll_period):
    if not payroll_period:
        return PayrollDeductionInstallment.objects.none()

    # Self-heal for deleted payroll runs: APPLIED installments may be left without
    # payroll_line (SET_NULL), which would otherwise hide them from future runs.
    _reset_orphaned_applied_installments_for_period(employee=employee, payroll_period=payroll_period)

    # Safety net: normalize legacy salary-advance schedules created with full principal
    # as the first installment for equal-split repayment.
    _repair_legacy_equal_split_salary_advance_schedules(employee=employee)
    _ensure_salary_advance_installment_for_period(employee=employee, payroll_period=payroll_period)

    return PayrollDeductionInstallment.objects.select_related("deduction_schedule").filter(
        deduction_schedule__employee=employee,
        deduction_schedule__source_type=DeductionSourceType.STAFF_WARD_SPONSORSHIP,
        deduction_schedule__status__in=[
            PayrollDeductionScheduleStatus.PLANNED,
            PayrollDeductionScheduleStatus.PARTIALLY_APPLIED,
            PayrollDeductionScheduleStatus.DEFERRED,
            PayrollDeductionScheduleStatus.ADJUSTED,
        ],
        payroll_period=payroll_period,
        status__in=[
            PayrollDeductionInstallmentStatus.PLANNED,
            PayrollDeductionInstallmentStatus.DEFERRED,
            PayrollDeductionInstallmentStatus.ADJUSTED,
        ],
    )


def _create_installment_deduction_lines(
    *,
    employee_item,
    installments,
    gross_pay,
    taxable_income,
    running_deductions,
    generated_by,
):
    sponsorship_item = _get_or_create_system_deduction_item(
        code="STAFF_WARD_SPONSORSHIP_DED",
        name="Staff Ward Sponsorship",
        priority=260,
    )
    advance_item = _get_or_create_system_deduction_item(
        code="SALARY_ADVANCE_DED",
        name="Salary Advance",
        priority=270,
    )

    installments_list = list(installments)
    salary_advance_source_ids = sorted(
        {
            str(installment.deduction_schedule.source_id)
            for installment in installments_list
            if installment.deduction_schedule.source_type == DeductionSourceType.SALARY_ADVANCE
            and installment.deduction_schedule.source_id
        }
    )
    salary_advances_by_id = {
        str(advance.id): advance
        for advance in SalaryAdvance.objects.filter(id__in=salary_advance_source_ids)
    }

    for installment in installments_list:
        amount = to_money(installment.scheduled_amount)
        if amount <= Decimal("0.00"):
            continue

        source_type = installment.deduction_schedule.source_type
        if source_type == DeductionSourceType.SALARY_ADVANCE:
            advance = salary_advances_by_id.get(str(installment.deduction_schedule.source_id))
            if (
                advance
                and advance.repayment_method == SalaryAdvanceRepaymentMethod.EQUAL_SPLIT
                and int(advance.number_of_installments or 1) > 1
            ):
                requested_installments = max(1, int(advance.number_of_installments or 1))
                schedule = installment.deduction_schedule
                schedule_installments_count = schedule.installments.count()
                expected_equal_split_amount = calculate_equal_installment_amount(
                    total_amount=to_money(schedule.total_amount),
                    installments=requested_installments,
                )
                if (
                    amount > expected_equal_split_amount
                    and (
                        schedule_installments_count != requested_installments
                        or amount == to_money(schedule.total_amount)
                    )
                ):
                    remaining_amount = to_money(schedule.remaining_amount)
                    amount = min(expected_equal_split_amount, remaining_amount) if remaining_amount > Decimal("0.00") else expected_equal_split_amount

        payroll_item = sponsorship_item if source_type == DeductionSourceType.STAFF_WARD_SPONSORSHIP else advance_item

        PayrollLineItem.objects.create(
            payroll_employee_item=employee_item,
            payroll_item=payroll_item,
            line_type=LineType.DEDUCTION,
            name=payroll_item.name,
            code=payroll_item.code,
            amount=amount,
            calculation_type=CalculationType.FLAT,
            target_amount_source=TargetAmountSource.GROSS_PAY,
            is_taxable=False,
            is_recurring=True,
            frequency=Frequency.MONTHLY,
            source_type="PayrollDeductionInstallment",
            source_id=str(installment.id),
            metadata={
                "deduction_schedule_id": str(installment.deduction_schedule_id),
                "deduction_source_type": source_type,
                "deduction_source_id": installment.deduction_schedule.source_id,
            },
            created_by=generated_by,
            updated_by=generated_by,
        )

        gross_pay, taxable_income, running_deductions = _apply_line_to_running_payroll_state(
            line_type=LineType.DEDUCTION,
            is_taxable=False,
            amount=amount,
            gross_pay=gross_pay,
            taxable_income=taxable_income,
            running_deductions=running_deductions,
        )

    return gross_pay, taxable_income, running_deductions


def _apply_salary_advance_recurring_deductions(
    *,
    employee_item,
    employee,
    pay_period_start,
    pay_period_end,
    gross_pay,
    taxable_income,
    running_deductions,
    generated_by,
):
    advance_item = _get_or_create_system_deduction_item(
        code="SALARY_ADVANCE_DED",
        name="Salary Advance",
        priority=270,
    )

    assignments = list(
        EmployeePayrollItem.objects.filter(
            employee=employee,
            is_active=True,
            source_type=DeductionSourceType.SALARY_ADVANCE,
            payroll_item__is_active=True,
        )
        .select_related("payroll_item")
        .order_by("priority", "id")
    )
    if not assignments:
        return gross_pay, taxable_income, running_deductions

    source_ids = sorted({assignment.source_id for assignment in assignments if assignment.source_id})
    advances_by_id = {
        str(advance.id): advance
        for advance in SalaryAdvance.objects.filter(id__in=source_ids)
    }

    for assignment in assignments:
        if not assignment.is_effective_for(pay_period_start, pay_period_end):
            continue

        advance = advances_by_id.get(str(assignment.source_id))
        if not advance:
            continue
        if advance.status != SalaryAdvanceStatus.COMPLETED:
            continue

        remaining_balance = to_money(advance.remaining_balance)
        if remaining_balance <= Decimal("0.00"):
            assignment.is_active = False
            assignment.end_date = assignment.end_date or pay_period_end
            assignment.updated_by = generated_by
            assignment.save(update_fields=["is_active", "end_date", "updated_by", "updated_at"])
            continue

        scheduled_amount = to_money(assignment.value)
        if scheduled_amount <= Decimal("0.00"):
            continue
        amount = min(scheduled_amount, remaining_balance)
        if amount <= Decimal("0.00"):
            continue

        PayrollLineItem.objects.create(
            payroll_employee_item=employee_item,
            payroll_item=advance_item,
            employee_payroll_item=assignment,
            line_type=LineType.DEDUCTION,
            name=assignment.get_name() or advance_item.name,
            code=advance_item.code,
            amount=amount,
            calculation_type=CalculationType.FLAT,
            target_amount_source=TargetAmountSource.GROSS_PAY,
            is_taxable=False,
            is_recurring=True,
            frequency=assignment.frequency,
            source_type="SalaryAdvance",
            source_id=str(advance.id),
            metadata={
                "deduction_source_type": DeductionSourceType.SALARY_ADVANCE,
                "salary_advance_id": str(advance.id),
                "employee_payroll_item_id": str(assignment.id),
                "scheduled_amount": str(scheduled_amount),
                "remaining_before": str(remaining_balance),
            },
            created_by=generated_by,
            updated_by=generated_by,
        )

        gross_pay, taxable_income, running_deductions = _apply_line_to_running_payroll_state(
            line_type=LineType.DEDUCTION,
            is_taxable=False,
            amount=amount,
            gross_pay=gross_pay,
            taxable_income=taxable_income,
            running_deductions=running_deductions,
        )

    return gross_pay, taxable_income, running_deductions


def _active_policy_for_date(*, as_of_date):
    return (
        StaffWardSponsorshipPolicy.objects.filter(is_active=True, effective_from__lte=as_of_date)
        .filter(Q(effective_to__isnull=True) | Q(effective_to__gte=as_of_date))
        .order_by("-effective_from", "-created_at")
        .first()
    )


def get_run_obligation_deduction_violations(payroll_run: PayrollRunRecord):
    policy = _active_policy_for_date(as_of_date=payroll_run.pay_period_start)
    if policy is None:
        return {"policy": None, "violations": []}

    policy_percent = Decimal(str(policy.max_payroll_deduction_percent_of_gross or "0"))
    violations = []

    for item in payroll_run.employee_items.prefetch_related("employee", "line_items").all():
        gross = to_money(item.gross_pay)
        all_deductions = to_money(item.total_deductions)
        installment_lines = [
            line
            for line in item.line_items.all()
            if line.source_type in ["PayrollDeductionInstallment", "SalaryAdvance"]
        ]
        if not installment_lines:
            continue

        voluntary_total = to_money(sum((line.amount for line in installment_lines), Decimal("0.00")))
        base_deductions = to_money(all_deductions - voluntary_total)
        limit_result = evaluate_deduction_limits(
            gross_pay=gross,
            existing_total_deductions=base_deductions,
            proposed_deduction=voluntary_total,
            max_deduction_percent_of_gross=policy.max_payroll_deduction_percent_of_gross,
            min_net_pay_percent_of_gross=policy.min_net_pay_percent_of_gross,
        )

        reasons = []
        if not limit_result.is_allowed:
            if getattr(limit_result, "exceeds_max_deduction", False):
                reasons.append(
                    {
                        "code": "exceeds_max_total_deduction",
                        "message": (
                            "Total deductions exceed policy maximum "
                            f"({policy.max_payroll_deduction_percent_of_gross}% of gross)."
                        ),
                    }
                )
            if getattr(limit_result, "below_min_net_pay", False):
                reasons.append(
                    {
                        "code": "below_min_net_pay",
                        "message": (
                            "Projected net pay falls below policy minimum "
                            f"({policy.min_net_pay_percent_of_gross}% of gross)."
                        ),
                    }
                )
            if not reasons:
                reasons.append(
                    {
                        "code": "deduction_policy_violation",
                        "message": "Projected deductions violate payroll policy limits.",
                    }
                )

        sponsorship_total = to_money(
            sum(
                (
                    line.amount
                    for line in installment_lines
                    if (line.metadata or {}).get("deduction_source_type") == DeductionSourceType.STAFF_WARD_SPONSORSHIP
                ),
                Decimal("0.00"),
            )
        )
        sponsorship_cap = to_money((gross * policy_percent) / Decimal("100"))
        if sponsorship_total > sponsorship_cap:
            reasons.append(
                {
                    "code": "sponsorship_exceeds_cap",
                    "message": "Sponsorship recovery exceeds allowed cap for this period.",
                }
            )

        if reasons:
            employee_name = ""
            if item.employee_id and item.employee:
                employee_name = item.employee.get_full_name() or getattr(item.employee, "id_number", "") or ""

            violations.append(
                {
                    "employee_id": str(item.employee_id),
                    "employee_name": employee_name,
                    "gross_pay": str(gross),
                    "base_deductions": str(base_deductions),
                    "proposed_obligation_deduction": str(voluntary_total),
                    "resulting_total_deductions": str(
                        getattr(limit_result, "resulting_total_deductions", Decimal("0.00"))
                    ),
                    "resulting_net_pay": str(getattr(limit_result, "resulting_net_pay", Decimal("0.00"))),
                    "max_allowed_total_deductions": str(
                        getattr(limit_result, "max_allowed_deductions", Decimal("0.00"))
                    ),
                    "min_required_net_pay": str(getattr(limit_result, "min_required_net_pay", Decimal("0.00"))),
                    "sponsorship_deduction_total": str(sponsorship_total),
                    "sponsorship_cap": str(sponsorship_cap),
                    "reasons": reasons,
                }
            )

    return {
        "policy": {
            "id": str(getattr(policy, "id", "")),
            "name": getattr(policy, "name", ""),
            "max_payroll_deduction_percent_of_gross": str(
                getattr(policy, "max_payroll_deduction_percent_of_gross", Decimal("0"))
            ),
            "min_net_pay_percent_of_gross": str(
                getattr(policy, "min_net_pay_percent_of_gross", Decimal("0"))
            ),
            "effective_from": str(getattr(policy, "effective_from", "")),
            "effective_to": (
                str(getattr(policy, "effective_to")) if getattr(policy, "effective_to", None) else None
            ),
        },
        "violations": violations,
    }


def _validate_run_obligation_deduction_limits(payroll_run: PayrollRunRecord):
    violations_payload = get_run_obligation_deduction_violations(payroll_run)
    violations = violations_payload.get("violations", [])
    if violations:
        deduped = sorted({str(item.get("employee_id")) for item in violations if item.get("employee_id")})
        raise ValueError(
            "Payroll run has deduction policy violations. "
            f"Employees affected: {', '.join(deduped)}"
        )


def _build_deduction_schedule_snapshot(schedule: PayrollDeductionSchedule):
    installments_payload = []
    installments = schedule.installments.select_related("payroll_period").order_by("payroll_period__start_date", "id")
    for installment in installments:
        period = installment.payroll_period
        installments_payload.append(
            {
                "id": str(installment.id),
                "payroll_period": {
                    "id": str(period.id),
                    "start_date": str(period.start_date),
                    "end_date": str(period.end_date),
                },
                "scheduled_amount": str(to_money(installment.scheduled_amount)),
                "actual_amount": str(to_money(installment.actual_amount)),
                "status": installment.status,
                "payroll_line_id": str(installment.payroll_line_id) if installment.payroll_line_id else None,
                "applied_at": installment.applied_at.isoformat() if installment.applied_at else None,
            }
        )

    return {
        "version": 1,
        "schedule": {
            "id": str(schedule.id),
            "employee_id": str(schedule.employee_id),
            "source_type": schedule.source_type,
            "source_id": str(schedule.source_id),
            "start_period_id": str(schedule.start_period_id) if schedule.start_period_id else None,
            "end_period_id": str(schedule.end_period_id) if schedule.end_period_id else None,
            "total_amount": str(to_money(schedule.total_amount)),
            "remaining_amount": str(to_money(schedule.remaining_amount)),
            "scheduled_amount": str(to_money(schedule.scheduled_amount)),
            "status": schedule.status,
        },
        "installments": installments_payload,
    }


def _refresh_deduction_schedule_snapshot(schedule: PayrollDeductionSchedule):
    schedule.schedule_snapshot = _build_deduction_schedule_snapshot(schedule)
    schedule.save(update_fields=["schedule_snapshot", "updated_at"])


def _final_payment_date_for_schedule(*, schedule: PayrollDeductionSchedule):
    last_installment = (
        schedule.installments.select_related("payroll_period")
        .order_by("payroll_period__start_date", "id")
        .last()
    )
    if not last_installment:
        return None
    payroll_period = getattr(last_installment, "payroll_period", None)
    if payroll_period is None:
        return None
    return getattr(payroll_period, "payment_date", None) or getattr(payroll_period, "end_date", None)


def _sync_employee_deduction_item_end_date_from_schedule(*, schedule: PayrollDeductionSchedule, actor=None):
    final_payment_date = _final_payment_date_for_schedule(schedule=schedule)
    if final_payment_date is None:
        return

    assignment = (
        EmployeePayrollItem.objects.filter(
            employee=schedule.employee,
            source_type=schedule.source_type,
            source_id=str(schedule.source_id),
            is_active=True,
        )
        .order_by("-updated_at")
        .first()
    )
    if assignment is None:
        return
    if assignment.end_date == final_payment_date:
        return

    assignment.end_date = final_payment_date
    assignment.updated_by = actor
    assignment.save(update_fields=["end_date", "updated_by", "updated_at"])


def _json_amount(value: Decimal) -> float:
    return float(to_money(value))


def _build_staff_ward_student_allocation(*, sponsorship: StaffWardSponsorship, monthly_deduction: Decimal | None = None):
    sponsorship_students = getattr(sponsorship, "sponsorship_students", None)
    if sponsorship_students is None:
        return []

    if hasattr(sponsorship_students, "select_related"):
        sponsorship_rows = list(sponsorship_students.select_related("student").order_by("created_at", "id"))
    elif hasattr(sponsorship_students, "all"):
        sponsorship_rows = list(sponsorship_students.all())
    else:
        sponsorship_rows = list(sponsorship_students)
    if not sponsorship_rows:
        return []

    total_sponsored = to_money(
        sponsorship.total_sponsored_amount
        or sum((row.eligible_fee_total for row in sponsorship_rows), Decimal("0.00"))
    )
    if total_sponsored <= Decimal("0.00"):
        return []

    monthly = to_money(monthly_deduction if monthly_deduction is not None else sponsorship.payroll_recovery_amount)
    if monthly < Decimal("0.00"):
        monthly = Decimal("0.00")

    existing_allocation = getattr(sponsorship, "student_allocation", None) or []
    existing = {
        str(entry.get("id_number") or "").strip(): entry
        for entry in existing_allocation
        if isinstance(entry, dict)
    }

    allocations = []
    running_monthly = Decimal("0.00")
    running_percent = Decimal("0.0000")

    for index, row in enumerate(sponsorship_rows):
        student = getattr(row, "student", None)
        id_number = str(
            getattr(student, "id_number", "")
            or getattr(row, "student_id_number", "")
            or ""
        ).strip()
        sponsored_amount = to_money(row.eligible_fee_total or Decimal("0.00"))
        last_row = index == len(sponsorship_rows) - 1

        if last_row:
            allocation_percent = max(Decimal("0.0000"), Decimal("100.0000") - running_percent)
            monthly_amount = max(Decimal("0.00"), to_money(monthly - running_monthly))
        else:
            allocation_percent = ((sponsored_amount / total_sponsored) * Decimal("100")).quantize(
                Decimal("0.0001")
            )
            monthly_amount = to_money((monthly * allocation_percent) / Decimal("100"))
            running_percent += allocation_percent
            running_monthly = to_money(running_monthly + monthly_amount)

        previous = existing.get(id_number, {})
        prior_paid = to_money(Decimal(str(previous.get("total_paid") or "0")))
        total_paid = min(sponsored_amount, max(Decimal("0.00"), prior_paid))
        remaining_balance = max(Decimal("0.00"), to_money(sponsored_amount - total_paid))

        allocations.append(
            {
                "id_number": id_number,
                "sponsored_amount": _json_amount(sponsored_amount),
                "allocation_percentage": float(allocation_percent),
                "monthly_allocation_amount": _json_amount(monthly_amount),
                "total_paid": _json_amount(total_paid),
                "remaining_sponsored_balance": _json_amount(remaining_balance),
            }
        )

    return allocations


def _ward_sponsorship_tuition_tx_type() -> AccountingTransactionType:
    tx_type = AccountingTransactionType.objects.filter(code__iexact="TUITION").first()
    if tx_type is not None:
        return tx_type

    return AccountingTransactionType.objects.create(
        code="TUITION",
        name="Tuition Payment",
        transaction_category="income",
        description="Auto-generated tuition payment from ward sponsorship payroll deduction.",
        is_active=True,
    )


def _resolve_student_allocation_amounts(*, allocations: list[dict], deduction_amount: Decimal):
    planned_total = max(Decimal("0.00"), to_money(deduction_amount))
    if planned_total <= Decimal("0.00"):
        return [], Decimal("0.00")

    normalized = []
    for entry in allocations:
        id_number = str(entry.get("id_number") or "").strip()
        pct = Decimal(str(entry.get("allocation_percentage") or "0"))
        if pct < Decimal("0"):
            pct = Decimal("0")
        remaining = max(
            Decimal("0.00"),
            to_money(Decimal(str(entry.get("remaining_sponsored_balance") or "0"))),
        )
        normalized.append(
            {
                "entry": entry,
                "id_number": id_number,
                "percentage": pct,
                "remaining": remaining,
                "allocated": Decimal("0.00"),
            }
        )

    total_remaining_capacity = to_money(sum((row["remaining"] for row in normalized), Decimal("0.00")))
    distributable = min(planned_total, total_remaining_capacity)
    if distributable <= Decimal("0.00"):
        return normalized, Decimal("0.00")

    remaining_to_allocate = distributable
    for idx, row in enumerate(normalized):
        is_last = idx == len(normalized) - 1
        if is_last:
            target = remaining_to_allocate
        else:
            target = to_money((distributable * row["percentage"]) / Decimal("100"))

        allocation = min(row["remaining"], remaining_to_allocate, max(Decimal("0.00"), target))
        row["allocated"] = to_money(allocation)
        remaining_to_allocate = to_money(remaining_to_allocate - row["allocated"])

    if remaining_to_allocate > Decimal("0.00"):
        for row in normalized:
            if remaining_to_allocate <= Decimal("0.00"):
                break
            headroom = max(Decimal("0.00"), to_money(row["remaining"] - row["allocated"]))
            if headroom <= Decimal("0.00"):
                continue
            fill = min(headroom, remaining_to_allocate)
            row["allocated"] = to_money(row["allocated"] + fill)
            remaining_to_allocate = to_money(remaining_to_allocate - fill)

    return normalized, distributable


def _upsert_ward_sponsorship_tuition_transactions_for_installment(
    *,
    payroll_run: PayrollRunRecord,
    installment: PayrollDeductionInstallment,
    actor=None,
):
    schedule = getattr(installment, "deduction_schedule", None)
    if schedule is None:
        return
    if getattr(schedule, "source_type", None) != DeductionSourceType.STAFF_WARD_SPONSORSHIP:
        return

    sponsorship = (
        StaffWardSponsorship.objects.select_related("academic_year", "employee")
        .prefetch_related("sponsorship_students__student")
        .filter(id=schedule.source_id)
        .first()
    )
    if sponsorship is None or sponsorship.academic_year_id is None:
        return

    if not sponsorship.student_allocation:
        sponsorship.student_allocation = _build_staff_ward_student_allocation(
            sponsorship=sponsorship,
            monthly_deduction=to_money(installment.scheduled_amount or Decimal("0.00")),
        )

    allocations = [row for row in (sponsorship.student_allocation or []) if isinstance(row, dict)]
    if not allocations:
        return

    resolved, distributable = _resolve_student_allocation_amounts(
        allocations=allocations,
        deduction_amount=to_money(installment.actual_amount or Decimal("0.00")),
    )
    if distributable <= Decimal("0.00"):
        return

    students_by_id_number = {
        str(row.student.id_number or "").strip(): row.student
        for row in sponsorship.sponsorship_students.all()
        if getattr(row, "student", None) is not None
    }

    tx_type = _ward_sponsorship_tuition_tx_type()
    payment_method = _salary_advance_repayment_payment_method(PaymentMethod.OTHER)
    bank_account = _salary_advance_repayment_bank_account()
    actor_name = None
    if actor is not None:
        actor_name = (
            (getattr(actor, "get_full_name", lambda: "")() or "").strip()
            or (getattr(actor, "username", "") or "").strip()
            or str(getattr(actor, "id", ""))
        )

    from accounting.services.payment_allocation import recompute_student_year_payments

    for row in resolved:
        amount = row["allocated"]
        if amount <= Decimal("0.00"):
            continue

        id_number = row["id_number"]
        student = students_by_id_number.get(id_number)
        if student is None:
            continue

        source_reference = (
            f"ward-sponsorship:{sponsorship.id}|run:{payroll_run.id}|"
            f"installment:{installment.id}|student:{id_number}"
        )

        reference_number = (
            f"WSP-{str(sponsorship.id)[:6]}-{str(payroll_run.id)[:6]}-"
            f"{str(installment.id)[:6]}-{id_number}"
        )[:100]

        tx_defaults = {
            "bank_account": bank_account,
            "transaction_date": payroll_run.payment_date,
            "reference_number": reference_number,
            "transaction_type": tx_type,
            "payment_method": payment_method,
            "ledger_account": tx_type.default_ledger_account,
            "amount": amount,
            "currency": bank_account.currency,
            "exchange_rate": Decimal("1"),
            "base_amount": amount,
            "payer_payee": sponsorship.employee.get_full_name() if sponsorship.employee_id else "",
            "description": (
                f"Ward Sponsorship Tuition Allocation - {id_number} - "
                f"{sponsorship.employee.get_full_name() if sponsorship.employee_id else sponsorship.employee_id}"
            ),
            "notes": "Auto-created from payroll ward sponsorship deduction.",
            "status": AccountingCashTransaction.TransactionStatus.COMPLETED,
            "approved_by": actor_name,
            "approved_at": timezone.now(),
            "completed_by": actor_name,
            "completed_at": timezone.now(),
            "source_reference": source_reference,
            "student": student,
            "updated_by": actor,
        }

        existing_tx = AccountingCashTransaction.objects.filter(source_reference=source_reference).first()
        if existing_tx is None:
            AccountingCashTransaction.objects.create(created_by=actor, **tx_defaults)
        else:
            for field, value in tx_defaults.items():
                setattr(existing_tx, field, value)
            existing_tx.save(
                update_fields=[
                    "bank_account",
                    "transaction_date",
                    "reference_number",
                    "transaction_type",
                    "payment_method",
                    "ledger_account",
                    "amount",
                    "currency",
                    "exchange_rate",
                    "base_amount",
                    "payer_payee",
                    "description",
                    "notes",
                    "status",
                    "approved_by",
                    "approved_at",
                    "completed_by",
                    "completed_at",
                    "student",
                    "updated_by",
                    "updated_at",
                ]
            )

        row["entry"]["total_paid"] = _json_amount(
            to_money(Decimal(str(row["entry"].get("total_paid") or "0")) + amount)
        )
        row["entry"]["remaining_sponsored_balance"] = _json_amount(
            max(Decimal("0.00"), to_money(Decimal(str(row["entry"].get("remaining_sponsored_balance") or "0")) - amount))
        )

        recompute_student_year_payments(student, sponsorship.academic_year)

    sponsorship.student_allocation = allocations
    sponsorship.updated_by = actor
    sponsorship.save(update_fields=["student_allocation", "updated_by", "updated_at"])


def _recompute_schedule_remaining_and_status(schedule: PayrollDeductionSchedule, *, actor=None):
    applied_total = to_money(
        sum(
            (
                installment.actual_amount
                for installment in schedule.installments.filter(status=PayrollDeductionInstallmentStatus.APPLIED)
            ),
            Decimal("0.00"),
        )
    )
    remaining = max(Decimal("0.00"), to_money(schedule.total_amount - applied_total))

    if remaining <= Decimal("0.00"):
        schedule_status = PayrollDeductionScheduleStatus.COMPLETED
    elif applied_total > Decimal("0.00"):
        schedule_status = PayrollDeductionScheduleStatus.PARTIALLY_APPLIED
    else:
        schedule_status = PayrollDeductionScheduleStatus.PLANNED

    schedule.remaining_amount = remaining
    schedule.status = schedule_status
    schedule.updated_by = actor
    schedule.save(update_fields=["remaining_amount", "status", "updated_by", "updated_at"])
    _refresh_deduction_schedule_snapshot(schedule)
    _sync_employee_deduction_item_end_date_from_schedule(schedule=schedule, actor=actor)

    if schedule.source_type == DeductionSourceType.STAFF_WARD_SPONSORSHIP and schedule.source_id:
        sponsorship = StaffWardSponsorship.objects.filter(id=schedule.source_id).first()
        if sponsorship is not None:
            _sync_staff_ward_repayment_progress(sponsorship=sponsorship, actor=actor)


def apply_deduction_installments_for_run(payroll_run: PayrollRunRecord, *, actor=None):
    lines = PayrollLineItem.objects.filter(
        payroll_employee_item__payroll=payroll_run,
        source_type="PayrollDeductionInstallment",
    )
    if not lines.exists():
        return

    installment_ids = [line.source_id for line in lines if line.source_id]
    installments_by_id = {
        str(installment.id): installment
        for installment in PayrollDeductionInstallment.objects.select_related("deduction_schedule").filter(id__in=installment_ids)
    }
    touched_schedule_ids = set()
    now = timezone.now()

    for line in lines:
        installment = installments_by_id.get(str(line.source_id))
        if installment is None:
            continue
        installment.actual_amount = to_money(line.amount)
        installment.status = PayrollDeductionInstallmentStatus.APPLIED
        installment.payroll_line = line
        installment.applied_at = now
        installment.updated_by = actor
        installment.save(
            update_fields=[
                "actual_amount",
                "status",
                "payroll_line",
                "applied_at",
                "updated_by",
                "updated_at",
            ]
        )
        _upsert_ward_sponsorship_tuition_transactions_for_installment(
            payroll_run=payroll_run,
            installment=installment,
            actor=actor,
        )
        touched_schedule_ids.add(installment.deduction_schedule_id)

    for schedule in PayrollDeductionSchedule.objects.filter(id__in=touched_schedule_ids):
        _recompute_schedule_remaining_and_status(schedule, actor=actor)


def revert_deduction_installments_for_run(payroll_run: PayrollRunRecord, *, actor=None):
    lines = PayrollLineItem.objects.filter(
        payroll_employee_item__payroll=payroll_run,
        source_type="PayrollDeductionInstallment",
    )
    if not lines.exists():
        return

    installment_ids = [line.source_id for line in lines if line.source_id]
    installments = PayrollDeductionInstallment.objects.select_related("deduction_schedule").filter(id__in=installment_ids)
    touched_schedule_ids = set()

    for installment in installments:
        installment.actual_amount = Decimal("0.00")
        installment.status = PayrollDeductionInstallmentStatus.PLANNED
        installment.payroll_line = None
        installment.applied_at = None
        installment.updated_by = actor
        installment.save(
            update_fields=[
                "actual_amount",
                "status",
                "payroll_line",
                "applied_at",
                "updated_by",
                "updated_at",
            ]
        )
        touched_schedule_ids.add(installment.deduction_schedule_id)

    for schedule in PayrollDeductionSchedule.objects.filter(id__in=touched_schedule_ids):
        _recompute_schedule_remaining_and_status(schedule, actor=actor)


def _expected_salary_advance_end_date(*, start_period: PayrollPeriod, installments: int):
    periods = _period_window_for_schedule(
        start_period=start_period,
        end_period=None,
        requested_installments=max(1, int(installments or 1)),
    )
    if not periods:
        return start_period.end_date
    return periods[-1].end_date


def _ensure_salary_advance_employee_deduction_item(*, advance: SalaryAdvance, periodic_amount: Decimal, actor=None):
    deduction_item = _get_or_create_system_deduction_item(
        code="SALARY_ADVANCE_DED",
        name="Salary Advance",
        priority=270,
    )

    active_schedule = _salary_advance_open_schedules(advance=advance).order_by("-created_at").first()
    expected_end_date = (
        _final_payment_date_for_schedule(schedule=active_schedule)
        if active_schedule is not None
        else _expected_salary_advance_end_date(
            start_period=advance.repayment_start_period,
            installments=max(1, int(advance.number_of_installments or 1)),
        )
    )

    assignment = (
        EmployeePayrollItem.objects.filter(
            employee=advance.employee,
            source_type=DeductionSourceType.SALARY_ADVANCE,
            source_id=str(advance.id),
        )
        .order_by("-updated_at")
        .first()
    )

    payload = {
        "payroll_item": deduction_item,
        "name_override": "Salary Advance Repayment",
        "calculation_type": CalculationType.FLAT,
        "value": to_money(periodic_amount),
        "formula": "",
        "target_amount_source": TargetAmountSource.GROSS_PAY,
        "calculation_limit": None,
        "is_taxable": False,
        "is_recurring": True,
        "frequency": Frequency.MONTHLY,
        "start_date": advance.repayment_start_period.start_date,
        "end_date": expected_end_date,
        "is_active": True,
        "priority": 270,
        "source_type": DeductionSourceType.SALARY_ADVANCE,
        "source_id": str(advance.id),
        "calculation_overridden": True,
        "notes": (advance.notes or "").strip(),
    }

    if assignment is None:
        assignment = EmployeePayrollItem.objects.create(
            employee=advance.employee,
            created_by=actor,
            updated_by=actor,
            **payload,
        )
    else:
        for key, value in payload.items():
            setattr(assignment, key, value)
        assignment.updated_by = actor
        assignment.save(
            update_fields=[
                "payroll_item",
                "name_override",
                "calculation_type",
                "value",
                "formula",
                "target_amount_source",
                "calculation_limit",
                "is_taxable",
                "is_recurring",
                "frequency",
                "start_date",
                "end_date",
                "is_active",
                "priority",
                "source_type",
                "source_id",
                "calculation_overridden",
                "notes",
                "updated_by",
                "updated_at",
            ]
        )
    return assignment


def _salary_advance_open_schedules(*, advance: SalaryAdvance):
    return PayrollDeductionSchedule.objects.filter(
        employee=advance.employee,
        source_type=DeductionSourceType.SALARY_ADVANCE,
        source_id=str(advance.id),
    ).exclude(status=PayrollDeductionScheduleStatus.CANCELLED)


def _staff_ward_sponsorship_open_schedules(*, sponsorship: StaffWardSponsorship):
    return PayrollDeductionSchedule.objects.filter(
        employee=sponsorship.employee,
        source_type=DeductionSourceType.STAFF_WARD_SPONSORSHIP,
        source_id=str(sponsorship.id),
    ).exclude(status=PayrollDeductionScheduleStatus.CANCELLED)


def _staff_ward_sponsorship_period_start(*, sponsorship: StaffWardSponsorship):
    if getattr(sponsorship, "start_period_id", None):
        return sponsorship.start_period

    from payroll_v2.schedule_services import derive_next_period, get_employee_pay_schedule

    schedule = get_employee_pay_schedule(sponsorship.employee)
    if schedule is None:
        raise ValueError("Employee does not have an active pay schedule. Set a start period before activating sponsorship.")

    derived = derive_next_period(schedule)
    period, _ = PayrollPeriod.objects.get_or_create(
        schedule=schedule,
        start_date=derived.start_date,
        end_date=derived.end_date,
        defaults={
            "name": derived.name,
            "payment_date": derived.payment_date,
        },
    )
    return period


def _staff_ward_repayment_month_starts(*, start_date: date, end_date: date):
    if start_date > end_date:
        return []

    month_cursor = date(start_date.year, start_date.month, 1)
    month_end = date(end_date.year, end_date.month, 1)
    months = []
    while month_cursor <= month_end:
        months.append(month_cursor)
        if month_cursor.month == 12:
            month_cursor = date(month_cursor.year + 1, 1, 1)
        else:
            month_cursor = date(month_cursor.year, month_cursor.month + 1, 1)
    return months


def _build_staff_ward_repayment_schedule(*, total_amount: Decimal, start_date: date, end_date: date):
    total = to_money(total_amount)
    if total <= Decimal("0.00"):
        return {
            "months_remaining": 0,
            "monthly_deduction": Decimal("0.00"),
            "rows": [],
        }

    month_starts = _staff_ward_repayment_month_starts(start_date=start_date, end_date=end_date)
    if not month_starts:
        return {
            "months_remaining": 0,
            "monthly_deduction": Decimal("0.00"),
            "rows": [],
        }

    months_remaining = len(month_starts)
    if months_remaining == 1:
        base_amount = total
    else:
        base_amount = (total / Decimal(str(months_remaining))).quantize(CENT, rounding=ROUND_DOWN)

    rows = []
    remaining = total
    for idx, month_start in enumerate(month_starts, start=1):
        if idx == months_remaining:
            deduction_amount = remaining
        else:
            deduction_amount = min(base_amount, remaining)

        remaining = to_money(remaining - deduction_amount)
        max_day = calendar.monthrange(month_start.year, month_start.month)[1]
        payment_day = min(start_date.day, max_day)
        repayment_date = date(month_start.year, month_start.month, payment_day)

        rows.append(
            {
                "installment_number": idx,
                "month_label": month_start.strftime("%B %Y"),
                "repayment_date": repayment_date.isoformat(),
                "scheduled_amount": str(to_money(deduction_amount)),
                "actual_paid_amount": "0.00",
                "remaining_balance": str(to_money(remaining)),
                "status": "planned",
            }
        )

    monthly_deduction = to_money(base_amount if months_remaining > 1 else total)
    return {
        "months_remaining": months_remaining,
        "monthly_deduction": monthly_deduction,
        "rows": rows,
    }


def _sync_staff_ward_repayment_progress(*, sponsorship: StaffWardSponsorship, actor=None):
    if not getattr(sponsorship, "pk", None):
        return

    schedule = (
        PayrollDeductionSchedule.objects.filter(
            employee=sponsorship.employee,
            source_type=DeductionSourceType.STAFF_WARD_SPONSORSHIP,
            source_id=str(sponsorship.id),
        )
        .exclude(status=PayrollDeductionScheduleStatus.CANCELLED)
        .order_by("-created_at")
        .first()
    )

    total_amount = to_money(sponsorship.total_sponsored_amount or Decimal("0.00"))
    paid_amount = Decimal("0.00")
    remaining_amount = total_amount

    if schedule is not None:
        remaining_amount = to_money(schedule.remaining_amount)
        paid_amount = max(Decimal("0.00"), to_money(total_amount - remaining_amount))

    progress_percent = Decimal("0.00")
    if total_amount > Decimal("0.00"):
        progress_percent = ((paid_amount / total_amount) * Decimal("100")).quantize(CENT)

    repayment_schedule = list(sponsorship.repayment_schedule or [])
    if schedule is not None and repayment_schedule:
        installments = list(schedule.installments.order_by("payroll_period__start_date", "id"))
        for idx, row in enumerate(repayment_schedule):
            if idx >= len(installments):
                break
            installment = installments[idx]
            row["actual_paid_amount"] = str(to_money(installment.actual_amount or Decimal("0.00")))
            row["status"] = installment.status
        # recompute row-level running remaining from actual paid values
        running = total_amount
        for row in repayment_schedule:
            paid_row = to_money(Decimal(str(row.get("actual_paid_amount") or "0.00")))
            running = max(Decimal("0.00"), to_money(running - paid_row))
            row["remaining_balance"] = str(running)

    sponsorship.repayment_paid_amount = to_money(paid_amount)
    sponsorship.repayment_remaining_balance = to_money(remaining_amount)
    sponsorship.repayment_progress_percent = to_money(progress_percent)
    sponsorship.repayment_schedule = repayment_schedule
    sponsorship.updated_by = actor
    sponsorship.save(
        update_fields=[
            "repayment_schedule",
            "repayment_paid_amount",
            "repayment_remaining_balance",
            "repayment_progress_percent",
            "updated_by",
            "updated_at",
        ]
    )


def _ensure_unique_active_or_completed_sponsorship_students_for_year(*, sponsorship: StaffWardSponsorship):
    if not sponsorship.academic_year_id:
        return

    sponsorship_students = getattr(sponsorship, "sponsorship_students", None)
    if sponsorship_students is None:
        return

    if hasattr(sponsorship_students, "values_list"):
        student_ids = list(sponsorship_students.values_list("student_id", flat=True))
    else:
        if hasattr(sponsorship_students, "select_related"):
            sponsorship_rows = list(sponsorship_students.select_related("student"))
        elif hasattr(sponsorship_students, "all"):
            sponsorship_rows = list(sponsorship_students.all())
        else:
            sponsorship_rows = list(sponsorship_students)

        student_ids = []
        for row in sponsorship_rows:
            student_id = getattr(row, "student_id", None)
            if student_id is None:
                student = getattr(row, "student", None)
                student_id = getattr(student, "id", None)
            if student_id:
                student_ids.append(student_id)

    if not student_ids:
        return

    conflicting_rows = (
        StaffWardSponsorshipStudent.objects.select_related("student")
        .filter(
            student_id__in=student_ids,
            sponsorship__academic_year_id=sponsorship.academic_year_id,
            sponsorship__status__in=[
                StaffWardSponsorshipStatus.ACTIVE,
                StaffWardSponsorshipStatus.COMPLETED,
            ],
        )
        .exclude(sponsorship_id=sponsorship.id)
    )
    if not conflicting_rows.exists():
        return

    conflicting_labels = []
    seen_students = set()
    for row in conflicting_rows:
        if row.student_id in seen_students:
            continue
        seen_students.add(row.student_id)
        student = getattr(row, "student", None)
        label = (
            getattr(student, "id_number", None)
            or (student.get_full_name() if student and hasattr(student, "get_full_name") else None)
            or str(row.student_id)
        )
        conflicting_labels.append(str(label))

    conflicts_text = ", ".join(conflicting_labels)
    raise ValueError(
        "One or more selected students already has a Ward Sponsorship for this academic year "
        f"and cannot be sponsored again: {conflicts_text}."
    )


def _ensure_staff_ward_sponsorship_employee_deduction_item(
    *,
    sponsorship: StaffWardSponsorship,
    periodic_amount: Decimal,
    actor=None,
):
    deduction_item = _get_or_create_system_deduction_item(
        code="STAFF_WARD_SPONSORSHIP_DED",
        name="Staff Ward Sponsorship",
        priority=260,
    )

    assignment = (
        EmployeePayrollItem.objects.filter(
            employee=sponsorship.employee,
            source_type=DeductionSourceType.STAFF_WARD_SPONSORSHIP,
            source_id=str(sponsorship.id),
        )
        .order_by("-updated_at")
        .first()
    )

    repayment_schedule = list(sponsorship.repayment_schedule or [])
    schedule_end_date = None
    if repayment_schedule:
        try:
            repayment_schedule.sort(key=lambda row: row.get("installment_number", 0))
            last_row_date = repayment_schedule[-1].get("repayment_date")
            if last_row_date:
                schedule_end_date = date.fromisoformat(str(last_row_date))
        except Exception:
            schedule_end_date = None

    fallback_end_date = (
        getattr(sponsorship.end_period, "payment_date", None)
        if sponsorship.end_period_id
        else getattr(sponsorship.start_period, "payment_date", None)
    )

    payload = {
        "payroll_item": deduction_item,
        "name_override": "Ward Sponsorship Deduction",
        "calculation_type": CalculationType.FLAT,
        "value": to_money(periodic_amount),
        "formula": "",
        "target_amount_source": TargetAmountSource.GROSS_PAY,
        "calculation_limit": None,
        "is_taxable": False,
        "is_recurring": True,
        "frequency": Frequency.MONTHLY,
        "start_date": sponsorship.start_period.start_date,
        "end_date": schedule_end_date or fallback_end_date or (sponsorship.end_period.end_date if sponsorship.end_period_id else sponsorship.start_period.end_date),
        "is_active": True,
        "priority": 260,
        "source_type": DeductionSourceType.STAFF_WARD_SPONSORSHIP,
        "source_id": str(sponsorship.id),
        "calculation_overridden": True,
        "notes": (sponsorship.review_notes or "").strip(),
    }

    if assignment is None:
        assignment = EmployeePayrollItem.objects.create(
            employee=sponsorship.employee,
            created_by=actor,
            updated_by=actor,
            **payload,
        )
    else:
        for key, value in payload.items():
            setattr(assignment, key, value)
        assignment.updated_by = actor
        assignment.save(
            update_fields=[
                "payroll_item",
                "name_override",
                "calculation_type",
                "value",
                "formula",
                "target_amount_source",
                "calculation_limit",
                "is_taxable",
                "is_recurring",
                "frequency",
                "start_date",
                "end_date",
                "is_active",
                "priority",
                "source_type",
                "source_id",
                "calculation_overridden",
                "notes",
                "updated_by",
                "updated_at",
            ]
        )

    return assignment


def _staff_ward_sponsorship_has_financial_processing(sponsorship: StaffWardSponsorship) -> bool:
    has_deduction_schedule = PayrollDeductionSchedule.objects.filter(
        employee=sponsorship.employee,
        source_type=DeductionSourceType.STAFF_WARD_SPONSORSHIP,
        source_id=str(sponsorship.id),
    ).exists()
    if has_deduction_schedule:
        return True

    source_prefix = f"ward-sponsorship:{sponsorship.id}|"
    has_cash_transactions = AccountingCashTransaction.objects.filter(
        source_reference__istartswith=source_prefix
    ).exists()
    if has_cash_transactions:
        return True

    return False


def ensure_staff_ward_sponsorship_can_be_deleted(
    sponsorship: StaffWardSponsorship,
    *,
    self_service: bool = False,
):
    if self_service and sponsorship.status not in {
        StaffWardSponsorshipStatus.DRAFT,
        StaffWardSponsorshipStatus.PENDING,
    }:
        raise ValueError("Only draft or pending ward sponsorship requests can be deleted.")

    if sponsorship.status in {StaffWardSponsorshipStatus.ACTIVE, StaffWardSponsorshipStatus.COMPLETED}:
        raise ValueError("Finalized sponsorships cannot be deleted because payroll history must be preserved.")
    if sponsorship.status == StaffWardSponsorshipStatus.CANCELLED:
        raise ValueError("Cancelled sponsorships cannot be deleted because lifecycle history must be preserved.")
    if _staff_ward_sponsorship_has_financial_processing(sponsorship):
        raise ValueError("This ward sponsorship can no longer be deleted because payroll or finance processing has already started.")


def _deactivate_salary_advance_employee_deduction_item(*, advance: SalaryAdvance, end_date=None, actor=None):
    update_kwargs = {
        "is_active": False,
        "updated_by": actor,
    }
    if end_date is not None:
        update_kwargs["end_date"] = end_date
    EmployeePayrollItem.objects.filter(
        employee=advance.employee,
        source_type=DeductionSourceType.SALARY_ADVANCE,
        source_id=str(advance.id),
        is_active=True,
    ).update(**update_kwargs)


def _set_salary_advance_repayment_status(*, advance: SalaryAdvance):
    paid = to_money(advance.amount_paid)
    remaining = to_money(advance.remaining_balance)
    if remaining <= Decimal("0.00"):
        advance.repayment_status = SalaryAdvanceRepaymentStatus.PAID
    elif paid > Decimal("0.00"):
        advance.repayment_status = SalaryAdvanceRepaymentStatus.IN_PROGRESS
    else:
        advance.repayment_status = SalaryAdvanceRepaymentStatus.NOT_STARTED


def _reschedule_salary_advance_future_installments(*, advance: SalaryAdvance, actor=None):
    schedule = (
        _salary_advance_open_schedules(advance=advance)
        .order_by("-created_at")
        .first()
    )
    if schedule is None:
        return

    future_installments = list(
        schedule.installments.exclude(status__in=[
            PayrollDeductionInstallmentStatus.APPLIED,
            PayrollDeductionInstallmentStatus.CANCELLED,
        ]).order_by("payroll_period__start_date", "id")
    )

    remaining_total = to_money(advance.remaining_balance)
    if remaining_total <= Decimal("0.00") or not future_installments:
        for installment in future_installments:
            installment.scheduled_amount = Decimal("0.00")
            installment.status = PayrollDeductionInstallmentStatus.CANCELLED
            installment.adjustment_reason = "Stopped after full repayment."
            installment.updated_by = actor
            installment.save(update_fields=[
                "scheduled_amount",
                "status",
                "adjustment_reason",
                "updated_by",
                "updated_at",
            ])
        schedule.remaining_amount = Decimal("0.00")
        schedule.scheduled_amount = Decimal("0.00")
        schedule.status = PayrollDeductionScheduleStatus.COMPLETED
        schedule.updated_by = actor
        schedule.save(update_fields=["remaining_amount", "scheduled_amount", "status", "updated_by", "updated_at"])
        _refresh_deduction_schedule_snapshot(schedule)
        return

    if advance.repayment_method == SalaryAdvanceRepaymentMethod.FIXED_INSTALLMENT and to_money(advance.installment_amount) > Decimal("0.00"):
        base_amount = to_money(advance.installment_amount)
    else:
        base_amount = calculate_equal_installment_amount(
            total_amount=remaining_total,
            installments=max(1, len(future_installments)),
        )

    remaining = remaining_total
    for installment in future_installments:
        if remaining <= Decimal("0.00"):
            installment.scheduled_amount = Decimal("0.00")
            installment.status = PayrollDeductionInstallmentStatus.CANCELLED
            installment.adjustment_reason = "Shortened after early repayment."
            installment.updated_by = actor
            installment.save(update_fields=[
                "scheduled_amount",
                "status",
                "adjustment_reason",
                "updated_by",
                "updated_at",
            ])
            continue

        current = min(base_amount, remaining)
        current = to_money(current)
        installment.scheduled_amount = current
        if installment.status == PayrollDeductionInstallmentStatus.CANCELLED:
            installment.status = PayrollDeductionInstallmentStatus.PLANNED
            installment.adjustment_reason = ""
            installment.updated_by = actor
            installment.save(update_fields=[
                "scheduled_amount",
                "status",
                "adjustment_reason",
                "updated_by",
                "updated_at",
            ])
        else:
            installment.updated_by = actor
            installment.save(update_fields=["scheduled_amount", "updated_by", "updated_at"])

        remaining = max(Decimal("0.00"), to_money(remaining - current))

    schedule.remaining_amount = remaining_total
    schedule.scheduled_amount = to_money(future_installments[0].scheduled_amount)
    schedule.status = (
        PayrollDeductionScheduleStatus.PARTIALLY_APPLIED
        if to_money(advance.amount_paid) > Decimal("0.00")
        else PayrollDeductionScheduleStatus.PLANNED
    )
    schedule.updated_by = actor
    schedule.save(update_fields=["remaining_amount", "scheduled_amount", "status", "updated_by", "updated_at"])
    _refresh_deduction_schedule_snapshot(schedule)


def _salary_advance_has_financial_processing(advance: SalaryAdvance) -> bool:
    has_deduction_schedule = PayrollDeductionSchedule.objects.filter(
        employee=advance.employee,
        source_type=DeductionSourceType.SALARY_ADVANCE,
        source_id=str(advance.id),
    ).exists()
    if has_deduction_schedule:
        return True

    has_repayment_rows = SalaryAdvancePayment.objects.filter(salary_advance=advance).exists()
    if has_repayment_rows:
        return True

    has_cash_transactions = AccountingCashTransaction.objects.filter(
        source_reference=f"salary-advance:{advance.id}"
    ).exists()
    if has_cash_transactions:
        return True

    return False


def ensure_salary_advance_can_be_deleted(
    advance: SalaryAdvance,
    *,
    self_service: bool = False,
):
    if self_service and advance.status not in {SalaryAdvanceStatus.DRAFT, SalaryAdvanceStatus.SUBMITTED}:
        raise ValueError("Only draft or pending salary advance requests can be deleted.")

    if advance.status == SalaryAdvanceStatus.COMPLETED or advance.completed_at is not None:
        raise ValueError("Completed salary advances cannot be deleted because payroll history must be preserved.")
    if advance.cancelled_at is not None:
        raise ValueError("Cancelled salary advances cannot be deleted because lifecycle history must be preserved.")
    if _salary_advance_has_financial_processing(advance):
        raise ValueError("This salary advance can no longer be deleted because payroll or finance processing has already started.")


@transaction.atomic
def complete_salary_advance(advance: SalaryAdvance, user=None):
    if advance.status != SalaryAdvanceStatus.APPROVED:
        raise ValueError("Only approved salary advances can be completed.")
    if not advance.repayment_start_period_id:
        raise ValueError("Repayment start period is required to complete a salary advance.")

    principal = to_money(advance.approved_amount or advance.amount)
    if principal <= Decimal("0.00"):
        raise ValueError("Approved amount must be greater than zero.")

    fixed_amount = None
    if (
        advance.repayment_method == SalaryAdvanceRepaymentMethod.FIXED_INSTALLMENT
        and advance.installment_amount
        and advance.installment_amount > 0
    ):
        fixed_amount = advance.installment_amount

    schedule = create_or_replace_deduction_schedule(
        employee=advance.employee,
        source_type=DeductionSourceType.SALARY_ADVANCE,
        source_id=advance.id,
        total_amount=principal,
        start_period=advance.repayment_start_period,
        number_of_installments=max(1, int(advance.number_of_installments or 1)),
        fixed_installment_amount=fixed_amount,
        actor=user,
    )

    periodic_amount = (
        to_money(advance.installment_amount)
        if fixed_amount is not None and to_money(advance.installment_amount) > Decimal("0.00")
        else to_money(schedule.scheduled_amount)
    )
    _ensure_salary_advance_employee_deduction_item(
        advance=advance,
        periodic_amount=periodic_amount,
        actor=user,
    )

    advance.approved_amount = principal
    advance.amount_paid = to_money(advance.amount_paid)
    advance.remaining_balance = max(Decimal("0.00"), to_money(principal - advance.amount_paid))
    _set_salary_advance_repayment_status(advance=advance)
    advance.status = SalaryAdvanceStatus.COMPLETED
    advance.completed_by = user
    advance.completed_at = timezone.now()
    if not advance.installment_amount or advance.installment_amount <= 0:
        advance.installment_amount = schedule.scheduled_amount
    advance.updated_by = user
    advance.save(update_fields=[
        "approved_amount",
        "amount_paid",
        "remaining_balance",
        "repayment_status",
        "status",
        "completed_by",
        "completed_at",
        "installment_amount",
        "updated_by",
        "updated_at",
    ])
    return advance


@transaction.atomic
def cancel_salary_advance(advance: SalaryAdvance, *, reason, user=None):
    note = (reason or "").strip()
    if not note:
        raise ValueError("Cancellation reason is required.")
    if advance.status != SalaryAdvanceStatus.COMPLETED:
        raise ValueError("Only completed salary advances can be cancelled.")
    if to_money(advance.amount_paid) > Decimal("0.00"):
        raise ValueError(
            "This salary advance already has repayment activity. Use early repayment/refund handling instead of cancellation."
        )

    for schedule in _salary_advance_open_schedules(advance=advance):
        schedule.installments.exclude(status=PayrollDeductionInstallmentStatus.APPLIED).update(
            status=PayrollDeductionInstallmentStatus.CANCELLED,
            adjustment_reason=note,
            updated_by=user,
        )
        schedule.status = PayrollDeductionScheduleStatus.CANCELLED
        schedule.scheduled_amount = Decimal("0.00")
        schedule.remaining_amount = Decimal("0.00")
        schedule.updated_by = user
        schedule.save(update_fields=["status", "scheduled_amount", "remaining_amount", "updated_by", "updated_at"])
        _refresh_deduction_schedule_snapshot(schedule)

    _deactivate_salary_advance_employee_deduction_item(
        advance=advance,
        end_date=advance.repayment_start_period.end_date if advance.repayment_start_period_id else None,
        actor=user,
    )

    advance.status = SalaryAdvanceStatus.CANCELLED
    advance.cancelled_by = user
    advance.cancelled_at = timezone.now()
    advance.cancellation_reason = note
    advance.remaining_balance = Decimal("0.00")
    advance.updated_by = user
    advance.save(update_fields=[
        "status",
        "cancelled_by",
        "cancelled_at",
        "cancellation_reason",
        "remaining_balance",
        "updated_by",
        "updated_at",
    ])
    return advance


@transaction.atomic
def record_salary_advance_payment(
    advance: SalaryAdvance,
    *,
    amount,
    payment_date,
    payment_method=PaymentMethod.OTHER,
    reference="",
    notes="",
    user=None,
):
    if advance.status != SalaryAdvanceStatus.COMPLETED:
        raise ValueError("Only completed salary advances can accept repayments.")

    payment_amount = to_money(amount)
    if payment_amount <= Decimal("0.00"):
        raise ValueError("Payment amount must be greater than zero.")

    remaining_before = to_money(advance.remaining_balance)
    if remaining_before <= Decimal("0.00"):
        raise ValueError("This salary advance is already fully repaid.")
    if payment_amount > remaining_before:
        raise ValueError("Early repayment cannot exceed the remaining balance.")

    payment = SalaryAdvancePayment.objects.create(
        salary_advance=advance,
        payment_date=payment_date,
        amount=payment_amount,
        payment_method=payment_method,
        reference=(reference or "").strip(),
        notes=(notes or "").strip(),
        created_by=user,
        updated_by=user,
    )

    advance.amount_paid = to_money(advance.amount_paid) + payment_amount
    advance.remaining_balance = max(Decimal("0.00"), to_money(remaining_before - payment_amount))
    _set_salary_advance_repayment_status(advance=advance)
    advance.updated_by = user
    advance.save(update_fields=["amount_paid", "remaining_balance", "repayment_status", "updated_by", "updated_at"])

    if advance.remaining_balance <= Decimal("0.00"):
        _deactivate_salary_advance_employee_deduction_item(advance=advance, actor=user)
    _reschedule_salary_advance_future_installments(advance=advance, actor=user)

    return payment


def _salary_advance_repayment_tx_type() -> AccountingTransactionType:
    tx_type = (
        AccountingTransactionType.objects.filter(
            code__iexact="SALARY_ADVANCE_REPAYMENT",
            transaction_category="income",
            is_active=True,
        )
        .order_by("name")
        .first()
    )
    if tx_type is not None:
        return tx_type

    return AccountingTransactionType.objects.create(
        code="SALARY_ADVANCE_REPAYMENT",
        name="Salary Advance Repayment",
        transaction_category="income",
        description="Finance transaction for early salary advance repayments.",
        is_system_managed=True,
        is_active=True,
    )


def _salary_advance_repayment_payment_method(payment_method: str | None) -> AccountingPaymentMethod:
    method_map = {
        PaymentMethod.CASH: "CASH",
        PaymentMethod.CHECK: "CHECK",
        PaymentMethod.BANK_TRANSFER: "BANK",
        PaymentMethod.MOBILE_MONEY: "MOMO",
    }
    target_code = method_map.get(payment_method or PaymentMethod.OTHER, "OTHER")
    resolved = AccountingPaymentMethod.objects.filter(code__iexact=target_code, is_active=True).first()
    if resolved is not None:
        return resolved

    fallback = AccountingPaymentMethod.objects.filter(code__iexact="OTHER", is_active=True).first()
    if fallback is not None:
        return fallback

    return AccountingPaymentMethod.objects.create(
        code="OTHER",
        name="Other",
        description="Fallback payment method for salary advance repayments.",
        is_active=True,
    )


def _salary_advance_repayment_bank_account() -> AccountingBankAccount:
    settings = AccountingSettings.objects.select_related("default_expense_bank_account").order_by("created_at").first()
    if settings and settings.default_expense_bank_account_id:
        return settings.default_expense_bank_account
    fallback = AccountingBankAccount.objects.filter(status=AccountingBankAccount.AccountStatus.ACTIVE).order_by("created_at").first()
    if fallback is not None:
        return fallback
    raise ValueError("No active bank account is configured for salary advance early repayments.")


def _ensure_finance_user(user):
    if not user_has_permission(user, "payroll.process"):
        raise ValueError("Only finance users can request early repayments.")


@transaction.atomic
def request_salary_advance_early_repayment(
    advance: SalaryAdvance,
    *,
    amount,
    payment_date,
    payment_method=PaymentMethod.OTHER,
    reference="",
    notes="",
    user=None,
):
    _ensure_finance_user(user)

    if advance.status != SalaryAdvanceStatus.COMPLETED:
        raise ValueError("Only completed salary advances can accept repayments.")

    payment_date = payment_date or timezone.now().date()

    payment_amount = to_money(amount)
    if payment_amount <= Decimal("0.00"):
        raise ValueError("Payment amount must be greater than zero.")

    remaining_before = to_money(advance.remaining_balance)
    if remaining_before <= Decimal("0.00"):
        raise ValueError("This salary advance is already fully repaid.")
    if payment_amount > remaining_before:
        raise ValueError("Early repayment cannot exceed the remaining balance.")

    accounting_settings = AccountingSettings.objects.select_related("salary_advance_repayment_ledger_account").order_by("created_at").first()
    if not accounting_settings or not accounting_settings.salary_advance_repayment_ledger_account_id:
        raise ValueError("Configure Early salary repayment GL account in Accounting settings before recording early repayments.")

    bank_account = _salary_advance_repayment_bank_account()
    if not bank_account.currency_id:
        raise ValueError("Selected bank account has no currency configured.")

    tx_type = _salary_advance_repayment_tx_type()
    payment_method_obj = _salary_advance_repayment_payment_method(payment_method)

    tx = AccountingCashTransaction.objects.create(
        bank_account=bank_account,
        transaction_date=payment_date,
        reference_number=f"SAR-{str(advance.id)[:8]}-{timezone.now().strftime('%H%M%S')}",
        transaction_type=tx_type,
        payment_method=payment_method_obj,
        ledger_account=accounting_settings.salary_advance_repayment_ledger_account,
        amount=payment_amount,
        currency=bank_account.currency,
        exchange_rate=Decimal("1"),
        base_amount=payment_amount,
        payer_payee=advance.employee.get_full_name() if advance.employee_id else "",
        description=f"Salary Advance Repayment - {advance.employee.get_full_name() if advance.employee_id else advance.employee_id}",
        notes=(notes or "").strip(),
        status=AccountingCashTransaction.TransactionStatus.PENDING,
        source_reference=f"salary-advance:{advance.id}",
        created_by=user,
        updated_by=user,
    )

    return {
        "salary_advance": str(advance.id),
        "finance_transaction_id": str(tx.id),
        "finance_transaction_reference": tx.reference_number,
        "finance_transaction_status": tx.status,
        "amount": payment_amount,
        "payment_date": payment_date,
    }


@transaction.atomic
def apply_salary_advance_repayment_from_finance_transaction(
    finance_transaction: AccountingCashTransaction,
    *,
    actor=None,
):
    if finance_transaction.status != AccountingCashTransaction.TransactionStatus.COMPLETED:
        return None

    source_reference = (finance_transaction.source_reference or "").strip()
    prefix = "salary-advance:"
    if not source_reference.lower().startswith(prefix):
        return None

    advance_id = source_reference[len(prefix):].strip()
    if not advance_id:
        return None

    advance = SalaryAdvance.objects.select_for_update().filter(id=advance_id).first()
    if advance is None or advance.status != SalaryAdvanceStatus.COMPLETED:
        return None

    existing = SalaryAdvancePayment.objects.filter(finance_transaction=finance_transaction).first()
    if existing is not None:
        return existing

    payment_amount = to_money(finance_transaction.amount)
    remaining_before = to_money(advance.remaining_balance)
    if remaining_before <= Decimal("0.00"):
        return None

    if payment_amount > remaining_before:
        payment_amount = remaining_before

    payment = SalaryAdvancePayment.objects.create(
        salary_advance=advance,
        finance_transaction=finance_transaction,
        payment_date=finance_transaction.transaction_date,
        amount=payment_amount,
        payment_method=PaymentMethod.OTHER,
        reference=(finance_transaction.reference_number or "").strip(),
        notes=(finance_transaction.notes or "").strip(),
        created_by=actor,
        updated_by=actor,
    )

    advance.amount_paid = to_money(advance.amount_paid) + payment_amount
    advance.remaining_balance = max(Decimal("0.00"), to_money(remaining_before - payment_amount))
    _set_salary_advance_repayment_status(advance=advance)
    advance.updated_by = actor
    advance.save(update_fields=["amount_paid", "remaining_balance", "repayment_status", "updated_by", "updated_at"])

    if advance.remaining_balance <= Decimal("0.00"):
        _deactivate_salary_advance_employee_deduction_item(advance=advance, actor=actor)
    _reschedule_salary_advance_future_installments(advance=advance, actor=actor)

    return payment


def apply_salary_advance_repayments_for_run(payroll_run: PayrollRunRecord, *, actor=None):
    lines = PayrollLineItem.objects.filter(
        payroll_employee_item__payroll=payroll_run,
        source_type="SalaryAdvance",
    )
    if not lines.exists():
        return

    source_ids = sorted({line.source_id for line in lines if line.source_id})
    advances_by_id = {
        str(advance.id): advance
        for advance in SalaryAdvance.objects.filter(id__in=source_ids)
    }

    for line in lines:
        advance = advances_by_id.get(str(line.source_id))
        if not advance:
            continue

        remaining = to_money(advance.remaining_balance)
        if remaining <= Decimal("0.00"):
            continue

        applied_amount = min(to_money(line.amount), remaining)
        if applied_amount <= Decimal("0.00"):
            continue

        advance.amount_paid = to_money(advance.amount_paid) + applied_amount
        advance.remaining_balance = max(Decimal("0.00"), remaining - applied_amount)
        _set_salary_advance_repayment_status(advance=advance)
        if advance.remaining_balance <= Decimal("0.00"):
            _deactivate_salary_advance_employee_deduction_item(
                advance=advance,
                end_date=payroll_run.pay_period_end,
                actor=actor,
            )

        advance.updated_by = actor
        advance.save(update_fields=["amount_paid", "remaining_balance", "repayment_status", "updated_by", "updated_at"])

        _reschedule_salary_advance_future_installments(advance=advance, actor=actor)


def revert_salary_advance_repayments_for_run(payroll_run: PayrollRunRecord, *, actor=None):
    lines = PayrollLineItem.objects.filter(
        payroll_employee_item__payroll=payroll_run,
        source_type="SalaryAdvance",
    )
    if not lines.exists():
        return

    source_ids = sorted({line.source_id for line in lines if line.source_id})
    advances_by_id = {
        str(advance.id): advance
        for advance in SalaryAdvance.objects.filter(id__in=source_ids)
    }

    for line in lines:
        advance = advances_by_id.get(str(line.source_id))
        if not advance:
            continue

        amount = to_money(line.amount)
        if amount <= Decimal("0.00"):
            continue

        advance.amount_paid = max(Decimal("0.00"), to_money(advance.amount_paid) - amount)
        advance.remaining_balance = min(to_money(advance.approved_amount), to_money(advance.remaining_balance) + amount)
        _set_salary_advance_repayment_status(advance=advance)
        advance.updated_by = actor
        advance.save(update_fields=["amount_paid", "remaining_balance", "repayment_status", "updated_by", "updated_at"])

        if advance.status == SalaryAdvanceStatus.COMPLETED and advance.remaining_balance > Decimal("0.00"):
            EmployeePayrollItem.objects.filter(
                employee=advance.employee,
                source_type=DeductionSourceType.SALARY_ADVANCE,
                source_id=str(advance.id),
            ).update(is_active=True, updated_by=actor)

        _reschedule_salary_advance_future_installments(advance=advance, actor=actor)


@transaction.atomic
def adjust_deduction_installment(*, installment: PayrollDeductionInstallment, amount, reason="", actor=None):
    new_amount = to_money(amount)
    if new_amount < Decimal("0.00"):
        raise ValueError("Adjusted amount cannot be negative.")

    installment.scheduled_amount = new_amount
    installment.status = PayrollDeductionInstallmentStatus.ADJUSTED
    installment.adjustment_reason = (reason or "").strip()
    installment.updated_by = actor
    installment.save(update_fields=["scheduled_amount", "status", "adjustment_reason", "updated_by", "updated_at"])

    schedule = installment.deduction_schedule
    schedule.scheduled_amount = new_amount
    schedule.status = PayrollDeductionScheduleStatus.ADJUSTED
    schedule.updated_by = actor
    schedule.save(update_fields=["scheduled_amount", "status", "updated_by", "updated_at"])
    _recompute_schedule_remaining_and_status(schedule, actor=actor)
    return installment


@transaction.atomic
def defer_deduction_installment(*, installment: PayrollDeductionInstallment, reason="", actor=None):
    installment.status = PayrollDeductionInstallmentStatus.DEFERRED
    installment.adjustment_reason = (reason or "").strip()
    installment.updated_by = actor
    installment.save(update_fields=["status", "adjustment_reason", "updated_by", "updated_at"])

    schedule = installment.deduction_schedule
    schedule.status = PayrollDeductionScheduleStatus.DEFERRED
    schedule.updated_by = actor
    schedule.save(update_fields=["status", "updated_by", "updated_at"])
    _refresh_deduction_schedule_snapshot(schedule)
    return installment


@transaction.atomic
def auto_adjust_deduction_installment(*, installment: PayrollDeductionInstallment, max_allowed_amount, reason="", actor=None):
    allowed = to_money(max_allowed_amount)
    current = to_money(installment.scheduled_amount)
    adjusted = min(current, max(Decimal("0.00"), allowed))
    return adjust_deduction_installment(
        installment=installment,
        amount=adjusted,
        reason=reason or "Auto-adjusted to payroll policy limit.",
        actor=actor,
    )


@transaction.atomic
def create_or_replace_deduction_schedule(
    *,
    employee,
    source_type,
    source_id,
    total_amount,
    start_period,
    end_period=None,
    number_of_installments=1,
    fixed_installment_amount=None,
    actor=None,
):
    amount_total = to_money(total_amount)
    if amount_total <= Decimal("0.00"):
        raise ValueError("Schedule total amount must be greater than zero.")

    periods = _period_window_for_schedule(
        start_period=start_period,
        end_period=end_period,
        requested_installments=number_of_installments,
    )
    if not periods:
        raise ValueError("At least one payroll period is required for schedule generation.")

    previous_schedules = PayrollDeductionSchedule.objects.filter(
        source_type=source_type,
        source_id=str(source_id),
        status__in=[
            PayrollDeductionScheduleStatus.PLANNED,
            PayrollDeductionScheduleStatus.PARTIALLY_APPLIED,
            PayrollDeductionScheduleStatus.DEFERRED,
            PayrollDeductionScheduleStatus.ADJUSTED,
        ],
    )
    previous_schedule_ids = list(previous_schedules.values_list("id", flat=True))
    previous_schedules.update(
        status=PayrollDeductionScheduleStatus.CANCELLED,
        updated_by=actor,
    )
    for previous in PayrollDeductionSchedule.objects.filter(id__in=previous_schedule_ids):
        _refresh_deduction_schedule_snapshot(previous)

    requested_installments = max(1, int(number_of_installments or 1))

    if fixed_installment_amount is not None and Decimal(str(fixed_installment_amount or "0")) > 0:
        installment_amount = to_money(fixed_installment_amount)
    else:
        installment_amount = calculate_equal_installment_amount(total_amount=amount_total, installments=requested_installments)

    schedule = PayrollDeductionSchedule.objects.create(
        employee=employee,
        source_type=source_type,
        source_id=str(source_id),
        start_period=periods[0],
        end_period=periods[-1],
        total_amount=amount_total,
        remaining_amount=amount_total,
        scheduled_amount=installment_amount,
        status=PayrollDeductionScheduleStatus.PLANNED,
        created_by=actor,
        updated_by=actor,
    )

    remaining = amount_total
    for idx, period in enumerate(periods, start=1):
        current = installment_amount
        should_close_out_here = len(periods) >= requested_installments and idx == len(periods)
        if should_close_out_here:
            current = remaining
        current = min(current, remaining)
        PayrollDeductionInstallment.objects.create(
            deduction_schedule=schedule,
            payroll_period=period,
            scheduled_amount=current,
            actual_amount=Decimal("0.00"),
            status=PayrollDeductionInstallmentStatus.PLANNED,
            created_by=actor,
            updated_by=actor,
        )
        remaining = to_money(remaining - current)

    _refresh_deduction_schedule_snapshot(schedule)

    return schedule


@transaction.atomic
def submit_staff_ward_sponsorship_for_approval(sponsorship: StaffWardSponsorship, user=None):
    if sponsorship.status != StaffWardSponsorshipStatus.DRAFT:
        raise ValueError("Only draft sponsorships can be submitted.")
    if not sponsorship.sponsorship_students.exists():
        raise ValueError("Cannot submit a sponsorship without sponsored students.")
    _ensure_unique_active_or_completed_sponsorship_students_for_year(sponsorship=sponsorship)

    from .settings_services import get_tenant_payroll_settings

    settings = get_tenant_payroll_settings(user=user)
    sponsored_total = to_money(
        sum((row.eligible_fee_total for row in sponsorship.sponsorship_students.all()), Decimal("0.00"))
    )
    if sponsored_total <= Decimal("0.00"):
        raise ValueError("Sponsorship total must be greater than zero.")

    start_period = getattr(sponsorship, "start_period", None) or _staff_ward_sponsorship_period_start(sponsorship=sponsorship)
    if not sponsorship.academic_year_id or not sponsorship.academic_year or not sponsorship.academic_year.end_date:
        raise ValueError("Academic year end date is required to build the repayment schedule.")

    repayment_plan = _build_staff_ward_repayment_schedule(
        total_amount=sponsored_total,
        start_date=start_period.start_date,
        end_date=sponsorship.academic_year.end_date,
    )
    if repayment_plan["months_remaining"] <= 0:
        raise ValueError("No repayment months remain in this academic year.")

    requested_periodic = to_money(
        sponsorship.payroll_recovery_amount or repayment_plan["monthly_deduction"] or sponsored_total
    )
    if requested_periodic <= Decimal("0.00"):
        requested_periodic = sponsored_total
    validate_employee_obligation_eligibility(
        employee=sponsorship.employee,
        payroll_settings=settings,
        obligation_type=DeductionSourceType.STAFF_WARD_SPONSORSHIP,
        requested_periodic_deduction=requested_periodic,
        exclude_source_type=DeductionSourceType.STAFF_WARD_SPONSORSHIP,
        exclude_source_id=sponsorship.id,
    )

    sponsorship.start_period = start_period
    sponsorship.total_sponsored_amount = sponsored_total
    sponsorship.payroll_recovery_amount = to_money(repayment_plan["monthly_deduction"])
    sponsorship.repayment_schedule = repayment_plan["rows"]
    sponsorship.student_allocation = _build_staff_ward_student_allocation(
        sponsorship=sponsorship,
        monthly_deduction=sponsorship.payroll_recovery_amount,
    )
    sponsorship.repayment_paid_amount = Decimal("0.00")
    sponsorship.repayment_remaining_balance = sponsored_total
    sponsorship.repayment_progress_percent = Decimal("0.00")
    sponsorship.status = StaffWardSponsorshipStatus.PENDING
    sponsorship.updated_by = user
    sponsorship.save(
        update_fields=[
            "start_period",
            "total_sponsored_amount",
            "payroll_recovery_amount",
            "repayment_schedule",
            "student_allocation",
            "repayment_paid_amount",
            "repayment_remaining_balance",
            "repayment_progress_percent",
            "status",
            "updated_by",
            "updated_at",
        ]
    )
    return sponsorship


@transaction.atomic
def approve_staff_ward_sponsorship(sponsorship: StaffWardSponsorship, user=None):
    if sponsorship.status != StaffWardSponsorshipStatus.PENDING:
        raise ValueError("Only pending sponsorships can be approved.")
    _ensure_unique_active_or_completed_sponsorship_students_for_year(sponsorship=sponsorship)

    employee_total = to_money(
        sum((row.employee_responsibility_amount for row in sponsorship.sponsorship_students.all()), Decimal("0.00"))
    )
    school_total = to_money(
        sum((row.school_covered_amount for row in sponsorship.sponsorship_students.all()), Decimal("0.00"))
    )
    sponsored_total = to_money(
        sum((row.eligible_fee_total for row in sponsorship.sponsorship_students.all()), Decimal("0.00"))
    )
    if sponsored_total <= Decimal("0.00"):
        raise ValueError("Sponsorship total must be greater than zero.")

    start_period = getattr(sponsorship, "start_period", None) or _staff_ward_sponsorship_period_start(sponsorship=sponsorship)
    if not sponsorship.academic_year_id or not sponsorship.academic_year or not sponsorship.academic_year.end_date:
        raise ValueError("Academic year end date is required to build the repayment schedule.")
    repayment_plan = _build_staff_ward_repayment_schedule(
        total_amount=sponsored_total,
        start_date=start_period.start_date,
        end_date=sponsorship.academic_year.end_date,
    )
    if repayment_plan["months_remaining"] <= 0:
        raise ValueError("No repayment months remain in this academic year.")

    from .settings_services import get_tenant_payroll_settings

    settings = get_tenant_payroll_settings(user=user)
    requested_periodic = to_money(sponsorship.payroll_recovery_amount or repayment_plan["monthly_deduction"] or sponsored_total)
    if requested_periodic <= Decimal("0.00"):
        requested_periodic = sponsored_total
    validate_employee_obligation_eligibility(
        employee=sponsorship.employee,
        payroll_settings=settings,
        obligation_type=DeductionSourceType.STAFF_WARD_SPONSORSHIP,
        requested_periodic_deduction=requested_periodic,
        exclude_source_type=DeductionSourceType.STAFF_WARD_SPONSORSHIP,
        exclude_source_id=sponsorship.id,
    )

    sponsorship.start_period = start_period
    sponsorship.total_sponsored_amount = sponsored_total
    sponsorship.school_contribution_amount = school_total
    sponsorship.employee_contribution_amount = employee_total
    sponsorship.payroll_recovery_amount = to_money(repayment_plan["monthly_deduction"])
    sponsorship.repayment_schedule = repayment_plan["rows"]
    sponsorship.student_allocation = _build_staff_ward_student_allocation(
        sponsorship=sponsorship,
        monthly_deduction=sponsorship.payroll_recovery_amount,
    )
    sponsorship.repayment_paid_amount = Decimal("0.00")
    sponsorship.repayment_remaining_balance = sponsored_total
    sponsorship.repayment_progress_percent = Decimal("0.00")
    sponsorship.status = StaffWardSponsorshipStatus.APPROVED
    sponsorship.approved_by = user
    sponsorship.approved_at = timezone.now()
    sponsorship.updated_by = user
    sponsorship.save(
        update_fields=[
            "total_sponsored_amount",
            "school_contribution_amount",
            "employee_contribution_amount",
            "payroll_recovery_amount",
            "repayment_schedule",
            "student_allocation",
            "repayment_paid_amount",
            "repayment_remaining_balance",
            "repayment_progress_percent",
            "status",
            "approved_by",
            "approved_at",
            "updated_by",
            "updated_at",
        ]
    )
    return sponsorship


@transaction.atomic
def complete_staff_ward_sponsorship(sponsorship: StaffWardSponsorship, user=None):
    if sponsorship.status != StaffWardSponsorshipStatus.APPROVED:
        raise ValueError("Only approved sponsorships can be finalized.")
    _ensure_unique_active_or_completed_sponsorship_students_for_year(sponsorship=sponsorship)

    employee_total = to_money(
        sum((row.employee_responsibility_amount for row in sponsorship.sponsorship_students.all()), Decimal("0.00"))
    )
    school_total = to_money(
        sum((row.school_covered_amount for row in sponsorship.sponsorship_students.all()), Decimal("0.00"))
    )
    sponsored_total = to_money(
        sum((row.eligible_fee_total for row in sponsorship.sponsorship_students.all()), Decimal("0.00"))
    )
    if sponsored_total <= Decimal("0.00"):
        raise ValueError("Sponsorship total must be greater than zero.")

    sponsorship.start_period = sponsorship.start_period or _staff_ward_sponsorship_period_start(sponsorship=sponsorship)
    if not sponsorship.academic_year_id or not sponsorship.academic_year or not sponsorship.academic_year.end_date:
        raise ValueError("Academic year end date is required to generate the sponsorship repayment schedule.")

    repayment_plan = _build_staff_ward_repayment_schedule(
        total_amount=sponsored_total,
        start_date=sponsorship.start_period.start_date,
        end_date=sponsorship.academic_year.end_date,
    )
    if repayment_plan["months_remaining"] <= 0:
        raise ValueError("No repayment months remain in the selected academic year for sponsorship recovery.")

    eligible_periods = list(
        PayrollPeriod.objects.filter(
            schedule_id=sponsorship.start_period.schedule_id,
            start_date__gte=sponsorship.start_period.start_date,
            start_date__lte=sponsorship.academic_year.end_date,
        ).order_by("start_date")
    )
    if not eligible_periods:
        raise ValueError("No eligible payroll periods remain in the selected academic year for sponsorship recovery.")

    period_count = min(len(eligible_periods), repayment_plan["months_remaining"])
    sponsorship.end_period = eligible_periods[period_count - 1]

    schedule = create_or_replace_deduction_schedule(
        employee=sponsorship.employee,
        source_type=DeductionSourceType.STAFF_WARD_SPONSORSHIP,
        source_id=sponsorship.id,
        total_amount=sponsored_total,
        start_period=sponsorship.start_period,
        end_period=sponsorship.end_period,
        number_of_installments=period_count,
        fixed_installment_amount=repayment_plan["monthly_deduction"],
        actor=user,
    )

    periodic_amount = to_money(schedule.scheduled_amount)
    _ensure_staff_ward_sponsorship_employee_deduction_item(
        sponsorship=sponsorship,
        periodic_amount=periodic_amount,
        actor=user,
    )

    sponsorship.total_sponsored_amount = sponsored_total
    sponsorship.school_contribution_amount = school_total
    sponsorship.employee_contribution_amount = employee_total
    sponsorship.payroll_recovery_amount = periodic_amount
    sponsorship.repayment_schedule = repayment_plan["rows"]
    sponsorship.student_allocation = _build_staff_ward_student_allocation(
        sponsorship=sponsorship,
        monthly_deduction=periodic_amount,
    )
    sponsorship.repayment_paid_amount = Decimal("0.00")
    sponsorship.repayment_remaining_balance = sponsored_total
    sponsorship.repayment_progress_percent = Decimal("0.00")
    sponsorship.status = StaffWardSponsorshipStatus.ACTIVE
    sponsorship.completed_at = timezone.now()
    sponsorship.updated_by = user
    sponsorship.save(
        update_fields=[
            "start_period",
            "end_period",
            "total_sponsored_amount",
            "school_contribution_amount",
            "employee_contribution_amount",
            "payroll_recovery_amount",
            "repayment_schedule",
            "student_allocation",
            "repayment_paid_amount",
            "repayment_remaining_balance",
            "repayment_progress_percent",
            "status",
            "completed_at",
            "updated_by",
            "updated_at",
        ]
    )
    _sync_staff_ward_repayment_progress(sponsorship=sponsorship, actor=user)
    return sponsorship


@transaction.atomic
def cancel_staff_ward_sponsorship(sponsorship: StaffWardSponsorship, *, reason, user=None):
    note = (reason or "").strip()
    if not note:
        raise ValueError("Cancellation reason is required.")
    if sponsorship.status not in {StaffWardSponsorshipStatus.APPROVED, StaffWardSponsorshipStatus.ACTIVE}:
        raise ValueError("Only approved or active sponsorships can be cancelled.")

    if _staff_ward_sponsorship_open_schedules(sponsorship=sponsorship).filter(
        installments__status=PayrollDeductionInstallmentStatus.APPLIED
    ).exists():
        raise ValueError("This sponsorship already has payroll deduction activity. Use reversal handling instead of cancellation.")

    for schedule in _staff_ward_sponsorship_open_schedules(sponsorship=sponsorship):
        schedule.installments.exclude(status=PayrollDeductionInstallmentStatus.APPLIED).update(
            status=PayrollDeductionInstallmentStatus.CANCELLED,
            adjustment_reason=note,
            updated_by=user,
        )
        schedule.status = PayrollDeductionScheduleStatus.CANCELLED
        schedule.scheduled_amount = Decimal("0.00")
        schedule.remaining_amount = Decimal("0.00")
        schedule.updated_by = user
        schedule.save(update_fields=["status", "scheduled_amount", "remaining_amount", "updated_by", "updated_at"])
        _refresh_deduction_schedule_snapshot(schedule)

    EmployeePayrollItem.objects.filter(
        employee=sponsorship.employee,
        source_type=DeductionSourceType.STAFF_WARD_SPONSORSHIP,
        source_id=str(sponsorship.id),
        is_active=True,
    ).update(is_active=False, updated_by=user)

    sponsorship.status = StaffWardSponsorshipStatus.CANCELLED
    sponsorship.rejection_reason = note
    sponsorship.completed_at = timezone.now()
    sponsorship.updated_by = user
    sponsorship.save(update_fields=["status", "rejection_reason", "completed_at", "updated_by", "updated_at"])
    return sponsorship


@transaction.atomic
def reject_staff_ward_sponsorship(sponsorship: StaffWardSponsorship, *, reason, user=None):
    if sponsorship.status not in [StaffWardSponsorshipStatus.PENDING, StaffWardSponsorshipStatus.DRAFT]:
        raise ValueError("Only draft or pending sponsorships can be rejected.")
    sponsorship.status = StaffWardSponsorshipStatus.REJECTED
    sponsorship.rejection_reason = (reason or "").strip()
    sponsorship.updated_by = user
    sponsorship.save(update_fields=["status", "rejection_reason", "updated_by", "updated_at"])
    return sponsorship


@transaction.atomic
def submit_salary_advance_for_approval(advance: SalaryAdvance, user=None):
    if advance.status != SalaryAdvanceStatus.DRAFT:
        raise ValueError("Only draft salary advances can be submitted.")

    from .settings_services import get_tenant_payroll_settings

    settings = get_tenant_payroll_settings(user=user)
    requested_periodic = _salary_advance_periodic_deduction(advance)
    validate_employee_obligation_eligibility(
        employee=advance.employee,
        payroll_settings=settings,
        obligation_type=DeductionSourceType.SALARY_ADVANCE,
        requested_periodic_deduction=requested_periodic,
        requested_amount=to_money(advance.amount),
        requested_installments=max(1, int(advance.number_of_installments or 1)),
        repayment_method=advance.repayment_method,
        fixed_installment_amount=to_money(advance.installment_amount),
        exclude_source_type=DeductionSourceType.SALARY_ADVANCE,
        exclude_source_id=advance.id,
    )

    advance.status = SalaryAdvanceStatus.SUBMITTED
    advance.updated_by = user
    advance.save(update_fields=["status", "updated_by", "updated_at"])
    return advance


def _salary_advance_periodic_deduction(advance: SalaryAdvance) -> Decimal:
    principal = to_money(advance.approved_amount or advance.amount)
    installments = max(1, int(advance.number_of_installments or 1))
    fixed_amount = to_money(advance.installment_amount)
    if (
        advance.repayment_method == SalaryAdvanceRepaymentMethod.FIXED_INSTALLMENT
        and fixed_amount > Decimal("0.00")
    ):
        return fixed_amount
    return to_money(principal / Decimal(str(installments)))


@transaction.atomic
def approve_salary_advance(advance: SalaryAdvance, user=None):
    if advance.status != SalaryAdvanceStatus.SUBMITTED:
        raise ValueError("Only submitted salary advances can be approved.")

    principal = to_money(advance.approved_amount or advance.amount)
    if principal <= Decimal("0.00"):
        raise ValueError("Approved amount must be greater than zero.")

    from .settings_services import get_tenant_payroll_settings

    settings = get_tenant_payroll_settings(user=user)
    requested_periodic = _salary_advance_periodic_deduction(advance)
    validate_employee_obligation_eligibility(
        employee=advance.employee,
        payroll_settings=settings,
        obligation_type=DeductionSourceType.SALARY_ADVANCE,
        requested_periodic_deduction=requested_periodic,
        requested_amount=to_money(advance.amount),
        requested_installments=max(1, int(advance.number_of_installments or 1)),
        repayment_method=advance.repayment_method,
        fixed_installment_amount=to_money(advance.installment_amount),
        exclude_source_type=DeductionSourceType.SALARY_ADVANCE,
        exclude_source_id=advance.id,
    )

    advance.approved_amount = principal
    advance.remaining_balance = principal
    advance.amount_paid = Decimal("0.00")
    advance.repayment_status = SalaryAdvanceRepaymentStatus.NOT_STARTED
    advance.status = SalaryAdvanceStatus.APPROVED
    advance.approved_by = user
    advance.approved_at = timezone.now()
    advance.updated_by = user
    advance.save(
        update_fields=[
            "approved_amount",
            "amount_paid",
            "remaining_balance",
            "repayment_status",
            "status",
            "approved_by",
            "approved_at",
            "updated_by",
            "updated_at",
        ]
    )
    return advance


@transaction.atomic
def reject_salary_advance(advance: SalaryAdvance, *, reason, user=None):
    if advance.status not in [SalaryAdvanceStatus.DRAFT, SalaryAdvanceStatus.SUBMITTED]:
        raise ValueError("Only draft or submitted salary advances can be rejected.")
    advance.status = SalaryAdvanceStatus.REJECTED
    note = (reason or "").strip()
    if note:
        advance.notes = f"{advance.notes}\nRejection: {note}".strip()
    advance.updated_by = user
    advance.save(update_fields=["status", "notes", "updated_by", "updated_at"])
    return advance


def resolve_payroll_v2_employee_scope(
    *,
    scope: str,
    employee_ids: list[str] | None = None,
    department_id: str | None = None,
    position_id: str | None = None,
):
    normalized_scope = (scope or "all").strip().lower()
    if normalized_scope not in {"all", "selected", "department", "position"}:
        raise ValueError("Invalid scope. Use all, selected, department, or position.")

    employees = Employee.objects.filter(
        employment_status=Employee.EmploymentStatus.ACTIVE,
    ).select_related("department", "position")

    if normalized_scope == "selected":
        identifiers = [str(value).strip() for value in (employee_ids or []) if str(value).strip()]
        if not identifiers:
            raise ValueError("Provide at least one employee id or id_number for selected scope.")
        employees = employees.filter(Q(id__in=identifiers) | Q(id_number__in=identifiers))
    elif normalized_scope == "department":
        if not department_id:
            raise ValueError("department_id is required for department scope.")
        employees = employees.filter(department_id=department_id)
    elif normalized_scope == "position":
        if not position_id:
            raise ValueError("position_id is required for position scope.")
        employees = employees.filter(position_id=position_id)

    return normalized_scope, employees.order_by("id_number", "id")


@transaction.atomic
def sync_payroll_catalog_item_to_employees(
    *,
    payroll_item: PayrollCatalogItem,
    scope: str,
    employee_ids: list[str] | None = None,
    department_id: str | None = None,
    position_id: str | None = None,
    actor=None,
):
    normalized_scope, employees = resolve_payroll_v2_employee_scope(
        scope=scope,
        employee_ids=employee_ids,
        department_id=department_id,
        position_id=position_id,
    )
    employee_list = list(employees)
    if not employee_list:
        return {
            "scope": normalized_scope,
            "payroll_item_id": str(payroll_item.id),
            "payroll_item_name": payroll_item.name,
            "targeted": 0,
            "created": 0,
            "reactivated": 0,
            "already_assigned": 0,
        }

    employee_ids_list = [employee.id for employee in employee_list]
    existing_assignments = {
        assignment.employee_id: assignment
        for assignment in EmployeePayrollItem.objects.filter(
            payroll_item=payroll_item,
            employee_id__in=employee_ids_list,
        )
    }

    created = 0
    reactivated = 0
    already_assigned = 0
    to_create: list[EmployeePayrollItem] = []

    for employee in employee_list:
        existing = existing_assignments.get(employee.id)
        if existing:
            if existing.is_active:
                already_assigned += 1
                continue
            existing.is_active = True
            existing.updated_by = actor
            existing.save(update_fields=["is_active", "updated_by", "updated_at"])
            reactivated += 1
            continue

        to_create.append(
            EmployeePayrollItem(
                employee=employee,
                payroll_item=payroll_item,
                calculation_type=CalculationType.FLAT,
                value=Decimal("0.0000"),
                target_amount_source=TargetAmountSource.BASIC_SALARY,
                is_recurring=False,
                frequency=Frequency.ONE_TIME,
                is_active=True,
                priority=payroll_item.priority,
                created_by=actor,
                updated_by=actor,
            )
        )

    if to_create:
        EmployeePayrollItem.objects.bulk_create(to_create)
        created = len(to_create)

    return {
        "scope": normalized_scope,
        "payroll_item_id": str(payroll_item.id),
        "payroll_item_name": payroll_item.name,
        "targeted": len(employee_list),
        "created": created,
        "reactivated": reactivated,
        "already_assigned": already_assigned,
    }


@transaction.atomic
def remove_payroll_catalog_item_from_employees(
    *,
    payroll_item: PayrollCatalogItem,
    scope: str,
    employee_ids: list[str] | None = None,
    department_id: str | None = None,
    position_id: str | None = None,
    actor=None,
):
    normalized_scope, employees = resolve_payroll_v2_employee_scope(
        scope=scope,
        employee_ids=employee_ids,
        department_id=department_id,
        position_id=position_id,
    )
    employee_ids_list = list(employees.values_list("id", flat=True))
    assignments = list(
        EmployeePayrollItem.objects.filter(
            payroll_item=payroll_item,
            employee_id__in=employee_ids_list,
        )
    )

    if not assignments:
        return {
            "scope": normalized_scope,
            "payroll_item_id": str(payroll_item.id),
            "payroll_item_name": payroll_item.name,
            "targeted": len(employee_ids_list),
            "removed": 0,
            "deactivated": 0,
        }

    assignment_ids = [assignment.id for assignment in assignments]
    used_assignment_ids = set(
        PayrollLineItem.objects.filter(
            employee_payroll_item_id__in=assignment_ids,
        ).values_list("employee_payroll_item_id", flat=True).distinct()
    )

    removed = 0
    deactivated = 0
    for assignment in assignments:
        if assignment.id in used_assignment_ids:
            if assignment.is_active:
                assignment.is_active = False
                assignment.updated_by = actor
                assignment.save(update_fields=["is_active", "updated_by", "updated_at"])
                deactivated += 1
            continue
        assignment.delete()
        removed += 1

    return {
        "scope": normalized_scope,
        "payroll_item_id": str(payroll_item.id),
        "payroll_item_name": payroll_item.name,
        "targeted": len(employee_ids_list),
        "removed": removed,
        "deactivated": deactivated,
    }
