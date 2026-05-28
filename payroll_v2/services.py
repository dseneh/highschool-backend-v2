from __future__ import annotations

from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from hr.models import Employee

from .enums import CalculationType, Frequency, LineType, PaymentStatus, PayrollStatus, PayType, TargetAmountSource
from .models import (
    EmployeeCompensation,
    EmployeePayrollItem,
    PayrollCatalogItem,
    PayrollCatalogItemRule,
    PayrollEmployeeItem,
    PayrollLineItem,
    PayrollPayslipTemplate,
    PayrollPeriod,
    PaySchedule,
    PayrollRunRecord,
    PayrollTableView,
)

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
    from payroll_v2.models import PayrollSettings

    settings = PayrollSettings.objects.select_related("transaction_type").first()
    if settings is None or settings.transaction_type_id is None:
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

        employee_item = PayrollEmployeeItem.objects.create(
            payroll=payroll_run,
            employee=employee,
            compensation=compensation if getattr(compensation, "id", None) else None,
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

    post_payroll_v2_run_to_ledger(payroll_run, actor=user)

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
    return payroll_run


@transaction.atomic
def revert_payroll_to_draft(payroll_run, user=None):
    """Force a run back to draft regardless of current status."""
    if payroll_run.status == PayrollStatus.DRAFT:
        return payroll_run

    if payroll_run.status == PayrollStatus.PAID:
        from .accounting_integration import reverse_payroll_v2_run_posting

        reverse_payroll_v2_run_posting(payroll_run, actor=user)

    payroll_run.status = PayrollStatus.DRAFT
    payroll_run.approved_by = None
    payroll_run.approved_at = None
    payroll_run.paid_at = None
    payroll_run.updated_by = user
    payroll_run.save(
        update_fields=["status", "approved_by", "approved_at", "paid_at", "updated_by", "updated_at"],
    )

    if payroll_run.payroll_period_id:
        period = payroll_run.payroll_period
        if period.is_closed:
            period.is_closed = False
            if user is not None:
                period.updated_by = user
            period.save(update_fields=["is_closed", "updated_by", "updated_at"])

    payroll_run.employee_items.update(payment_status=PaymentStatus.UNPAID)
    return payroll_run


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
