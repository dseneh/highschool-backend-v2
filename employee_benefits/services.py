from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from hr.models import Employee
from payroll_v2.enums import CalculationType, TargetAmountSource
from payroll_v2.services import (
    calculate_employee_item_amount,
    calculate_rule_amount_for_payroll,
    get_active_employee_compensation,
    get_compensation_annual_salary,
    resolve_payroll_v2_employee_scope,
)

from .enums import BenefitRequestStatus
from .models import (
    BenefitRequest,
    BenefitRequestLine,
    BenefitType,
    BenefitTypeRule,
    EmployeeBenefit,
)

CENT = Decimal("0.01")


def generate_benefit_type_rule_name(data: dict) -> str:
    calc = data.get("calculation_type", CalculationType.FLAT)
    if calc == CalculationType.FORMULA:
        formula = (data.get("formula") or "").strip()
        return formula[:80] if formula else "Formula rule"
    value = data.get("value", Decimal("0"))
    if calc == CalculationType.PERCENTAGE:
        return f"{value}%"
    return f"Flat {value}"


def _employee_salary_context(employee, as_of_date):
    compensation = get_active_employee_compensation(employee, as_of_date=as_of_date)
    basic = Decimal(compensation.base_amount or 0) if compensation else Decimal("0.00")
    annual = get_compensation_annual_salary(compensation, employee=employee) if compensation else Decimal("0.00")
    return {
        "basic_salary": basic,
        "gross_pay": basic,
        "taxable_income": basic,
        "annual_salary": annual,
    }


def _pick_matching_benefit_rule(rules, *, basic_salary, gross_pay, taxable_income, annual_salary):
    from payroll_v2.services import _pick_matching_payroll_rule

    return _pick_matching_payroll_rule(
        rules,
        basic_salary=basic_salary,
        gross_pay=gross_pay,
        taxable_income=taxable_income,
        annual_salary=annual_salary,
    )


def calculate_benefit_amount_for_employee(
    *,
    benefit_type: BenefitType,
    employee: Employee,
    employee_benefit: EmployeeBenefit | None,
    period_start,
    period_end,
) -> Decimal:
    ctx = _employee_salary_context(employee, period_end)
    as_of = period_end

    if employee_benefit and employee_benefit.calculation_overridden:
        return calculate_employee_item_amount(
            employee_benefit,
            basic_salary=ctx["basic_salary"],
            gross_pay=ctx["gross_pay"],
            taxable_income=ctx["taxable_income"],
            annual_salary=ctx["annual_salary"],
        )

    effective_rules = [
        rule
        for rule in benefit_type.rules.filter(is_active=True)
        if rule.is_effective_for(period_start, period_end)
    ]
    if effective_rules:
        rule = _pick_matching_benefit_rule(
            effective_rules,
            basic_salary=ctx["basic_salary"],
            gross_pay=ctx["gross_pay"],
            taxable_income=ctx["taxable_income"],
            annual_salary=ctx["annual_salary"],
        )
        if rule:
            return calculate_rule_amount_for_payroll(
                rule,
                basic_salary=ctx["basic_salary"],
                gross_pay=ctx["gross_pay"],
                taxable_income=ctx["taxable_income"],
                annual_salary=ctx["annual_salary"],
            )

    if employee_benefit:
        return calculate_employee_item_amount(
            employee_benefit,
            basic_salary=ctx["basic_salary"],
            gross_pay=ctx["gross_pay"],
            taxable_income=ctx["taxable_income"],
            annual_salary=ctx["annual_salary"],
        )

    return Decimal("0.00")


def default_employee_benefit_calculation(*, benefit_type: BenefitType) -> dict:
    return {
        "calculation_type": CalculationType.FLAT,
        "value": Decimal("0.0000"),
        "formula": "",
        "target_amount_source": TargetAmountSource.BASIC_SALARY,
        "calculation_limit": None,
        "calculation_overridden": False,
    }


@transaction.atomic
def revert_employee_benefit_calculation(assignment: EmployeeBenefit, *, actor=None) -> EmployeeBenefit:
    if not assignment.calculation_overridden:
        raise ValueError("This employee benefit is already using catalog calculation rules.")

    defaults = default_employee_benefit_calculation(benefit_type=assignment.benefit_type)
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
            "updated_by",
            "updated_at",
        ]
    )
    return assignment


def validate_benefit_request_period(*, benefit_type: BenefitType, period_start, period_end, exclude_id=None):
    from .settings_services import get_tenant_benefit_settings

    settings = get_tenant_benefit_settings()
    max_period_days = settings.max_period_days or 30
    min_gap_days = settings.min_days_between_requests or 1

    if period_end < period_start:
        raise ValueError("Period end must be on or after period start.")

    period_length = (period_end - period_start).days + 1
    if period_length > max_period_days:
        raise ValueError(
            f"Benefit request period cannot exceed {max_period_days} days "
            f"(selected period is {period_length} days)."
        )

    active_statuses = [
        BenefitRequestStatus.DRAFT,
        BenefitRequestStatus.PENDING_APPROVAL,
        BenefitRequestStatus.APPROVED,
    ]
    qs = BenefitRequest.objects.filter(
        benefit_type=benefit_type,
        status__in=active_statuses,
    )
    if exclude_id:
        qs = qs.exclude(id=exclude_id)
    if qs.exists():
        raise ValueError(
            f"There is already an active request for {benefit_type.name}. "
            "Complete or cancel it before creating another."
        )

    last_paid = (
        BenefitRequest.objects.filter(
            benefit_type=benefit_type,
            status=BenefitRequestStatus.PAID,
        )
        .order_by("-period_end")
        .first()
    )
    if last_paid:
        min_start = last_paid.period_end + timedelta(days=min_gap_days)
        if period_start < min_start:
            raise ValueError(
                f"Period must start on or after {min_start} "
                f"({min_gap_days} day{'s' if min_gap_days != 1 else ''} after the last paid request)."
            )


def generate_benefit_request_number() -> str:
    today = timezone.now().date()
    prefix = f"EB-{today.strftime('%Y%m%d')}"
    count = BenefitRequest.objects.filter(request_number__startswith=prefix).count()
    return f"{prefix}-{count + 1:03d}"


@transaction.atomic
def generate_benefit_request(
    benefit_request: BenefitRequest,
    *,
    employee_ids: list[str] | None = None,
    actor=None,
):
    if benefit_request.status not in (BenefitRequestStatus.DRAFT,):
        raise ValueError("Only draft requests can be generated.")

    benefit_type = benefit_request.benefit_type
    period_start = benefit_request.period_start
    period_end = benefit_request.period_end

    if employee_ids:
        employees = Employee.objects.filter(id__in=employee_ids, active=True)
    elif benefit_type.rules.filter(is_active=True).exists():
        employees = Employee.objects.filter(active=True)
    else:
        assignment_employee_ids = EmployeeBenefit.objects.filter(
            benefit_type=benefit_type,
            is_active=True,
        ).values_list("employee_id", flat=True)
        employees = Employee.objects.filter(id__in=assignment_employee_ids, active=True)

    existing_lines = {
        line.employee_id: line
        for line in benefit_request.lines.select_related("employee_benefit").all()
    }

    assignment_map = {
        eb.employee_id: eb
        for eb in EmployeeBenefit.objects.filter(
            benefit_type=benefit_type,
            is_active=True,
            employee__in=employees,
        )
    }

    for employee in employees:
        employee_benefit = assignment_map.get(employee.id)
        if not employee_benefit and not benefit_type.rules.filter(is_active=True).exists():
            continue
        if employee_benefit and not employee_benefit.is_effective_for(period_start, period_end):
            continue

        computed = calculate_benefit_amount_for_employee(
            benefit_type=benefit_type,
            employee=employee,
            employee_benefit=employee_benefit,
            period_start=period_start,
            period_end=period_end,
        )

        existing = existing_lines.get(employee.id)
        if existing:
            if not existing.amount_overridden:
                existing.computed_amount = computed
                existing.final_amount = computed
            else:
                existing.computed_amount = computed
            existing.employee_benefit = employee_benefit
            existing.updated_by = actor
            existing.save(
                update_fields=[
                    "computed_amount",
                    "final_amount",
                    "employee_benefit",
                    "updated_by",
                    "updated_at",
                ]
            )
        else:
            BenefitRequestLine.objects.create(
                request=benefit_request,
                employee=employee,
                employee_benefit=employee_benefit,
                computed_amount=computed,
                final_amount=computed,
                created_by=actor,
                updated_by=actor,
            )

    benefit_request.recalculate_totals()
    return benefit_request


@transaction.atomic
def sync_benefit_type_to_employees(
    *,
    benefit_type: BenefitType,
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
            "benefit_type_id": str(benefit_type.id),
            "benefit_type_name": benefit_type.name,
            "targeted": 0,
            "created": 0,
            "reactivated": 0,
            "already_assigned": 0,
        }

    employee_ids_list = [employee.id for employee in employee_list]
    existing = {
        a.employee_id: a
        for a in EmployeeBenefit.objects.filter(
            benefit_type=benefit_type,
            employee_id__in=employee_ids_list,
        )
    }

    created = reactivated = already_assigned = 0
    to_create = []

    for employee in employee_list:
        assignment = existing.get(employee.id)
        if assignment:
            if assignment.is_active:
                already_assigned += 1
            else:
                assignment.is_active = True
                assignment.updated_by = actor
                assignment.save(update_fields=["is_active", "updated_by", "updated_at"])
                reactivated += 1
        else:
            to_create.append(
                EmployeeBenefit(
                    employee=employee,
                    benefit_type=benefit_type,
                    created_by=actor,
                    updated_by=actor,
                )
            )

    if to_create:
        EmployeeBenefit.objects.bulk_create(to_create)
        created = len(to_create)

    return {
        "scope": normalized_scope,
        "benefit_type_id": str(benefit_type.id),
        "benefit_type_name": benefit_type.name,
        "targeted": len(employee_list),
        "created": created,
        "reactivated": reactivated,
        "already_assigned": already_assigned,
    }


@transaction.atomic
def remove_benefit_type_from_employees(
    *,
    benefit_type: BenefitType,
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
    removed = deactivated = 0

    for employee in employee_list:
        assignment = EmployeeBenefit.objects.filter(
            benefit_type=benefit_type,
            employee=employee,
        ).first()
        if not assignment:
            continue
        has_lines = BenefitRequestLine.objects.filter(employee_benefit=assignment).exists()
        if has_lines:
            assignment.is_active = False
            assignment.updated_by = actor
            assignment.save(update_fields=["is_active", "updated_by", "updated_at"])
            deactivated += 1
        else:
            assignment.delete()
            removed += 1

    return {
        "scope": normalized_scope,
        "benefit_type_id": str(benefit_type.id),
        "removed": removed,
        "deactivated": deactivated,
    }


def validate_benefit_settings_configured():
    from .settings_services import get_tenant_benefit_settings

    settings = get_tenant_benefit_settings()
    if not settings.transaction_type_id:
        raise ValueError("Employee benefit settings: expense transaction type is not configured.")


def validate_benefit_disbursement_account(benefit_request: BenefitRequest):
    from accounting.services.settings_services import bank_accounts_missing_ledger_message

    if not benefit_request.bank_account_id:
        raise ValueError("Benefit request must have a disbursement bank account.")
    bank = benefit_request.bank_account
    if bank.ledger_account_id is None:
        raise ValueError(bank_accounts_missing_ledger_message([bank]))
    if benefit_request.currency_id and bank.currency_id != benefit_request.currency_id:
        raise ValueError("Bank account currency must match the request currency.")


@transaction.atomic
def submit_benefit_request_for_approval(benefit_request: BenefitRequest, user=None):
    if benefit_request.status != BenefitRequestStatus.DRAFT:
        raise ValueError("Only draft requests can be submitted.")
    if not benefit_request.lines.exists():
        raise ValueError("Cannot submit a request with no employee lines.")
    validate_benefit_settings_configured()
    validate_benefit_disbursement_account(benefit_request)
    benefit_request.status = BenefitRequestStatus.PENDING_APPROVAL
    benefit_request.updated_by = user
    benefit_request.save(update_fields=["status", "updated_by", "updated_at"])
    return benefit_request


@transaction.atomic
def approve_benefit_request(benefit_request: BenefitRequest, user=None):
    if benefit_request.status != BenefitRequestStatus.PENDING_APPROVAL:
        raise ValueError("Only pending requests can be approved.")
    benefit_request.status = BenefitRequestStatus.APPROVED
    benefit_request.approved_by = user
    benefit_request.approved_at = timezone.now()
    benefit_request.updated_by = user
    benefit_request.save(
        update_fields=["status", "approved_by", "approved_at", "updated_by", "updated_at"]
    )
    return benefit_request


@transaction.atomic
def mark_benefit_request_paid(benefit_request: BenefitRequest, user=None):
    if benefit_request.status != BenefitRequestStatus.APPROVED:
        raise ValueError("Only approved requests can be marked paid.")
    validate_benefit_settings_configured()
    validate_benefit_disbursement_account(benefit_request)

    from .accounting_integration import post_benefit_request_to_ledger

    journal_entry = post_benefit_request_to_ledger(benefit_request, actor=user)

    from employee_disbursements.services.records import create_benefit_disbursement_records

    create_benefit_disbursement_records(
        benefit_request,
        journal_entry=journal_entry,
        actor=user,
    )

    benefit_request.status = BenefitRequestStatus.PAID
    benefit_request.paid_at = timezone.now()
    benefit_request.updated_by = user
    benefit_request.save(update_fields=["status", "paid_at", "updated_by", "updated_at"])

    from .paid_table_snapshot import capture_benefit_paid_table_snapshot

    capture_benefit_paid_table_snapshot(benefit_request)

    from .live_row_lifecycle import purge_paid_live_rows_if_enabled

    purge_paid_live_rows_if_enabled(benefit_request)
    return benefit_request


@transaction.atomic
def revert_benefit_request_to_draft(benefit_request: BenefitRequest, user=None):
    if benefit_request.status == BenefitRequestStatus.DRAFT:
        return benefit_request

    if benefit_request.status == BenefitRequestStatus.PAID:
        from .accounting_integration import reverse_benefit_request_posting

        reverse_benefit_request_posting(benefit_request, actor=user)

        from employee_disbursements.enums import DisbursementSourceType
        from employee_disbursements.services.records import revert_disbursement_records_for_source

        revert_disbursement_records_for_source(
            DisbursementSourceType.BENEFIT,
            benefit_request.id,
            actor=user,
        )

        from .live_row_lifecycle import restore_benefit_lines_from_snapshot

        restore_benefit_lines_from_snapshot(benefit_request, actor=user)

    benefit_request.status = BenefitRequestStatus.DRAFT
    benefit_request.approved_by = None
    benefit_request.approved_at = None
    benefit_request.paid_at = None
    benefit_request.paid_table_snapshot = {}
    benefit_request.updated_by = user
    benefit_request.save(
        update_fields=[
            "status",
            "approved_by",
            "approved_at",
            "paid_at",
            "paid_table_snapshot",
            "updated_by",
            "updated_at",
        ]
    )
    return benefit_request


@transaction.atomic
def cancel_benefit_request(benefit_request: BenefitRequest, user=None):
    if benefit_request.status == BenefitRequestStatus.PAID:
        raise ValueError("Paid requests cannot be cancelled. Revert to draft first.")
    benefit_request.status = BenefitRequestStatus.CANCELLED
    benefit_request.updated_by = user
    benefit_request.save(update_fields=["status", "updated_by", "updated_at"])
    return benefit_request
