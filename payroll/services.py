"""Payroll business logic — period derivation, tax application, payslip generation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Iterable

from django.db import transaction
from django.utils import timezone

from .models import (
    EmployeeTaxRuleOverride,
    PayrollItem,
    PayrollPeriod,
    PayrollRun,
    Payslip,
    PaySchedule,
    TaxRule,
)

ZERO = Decimal("0.00")


# ---------------------------------------------------------------------------
# Period derivation
# ---------------------------------------------------------------------------


@dataclass
class DerivedPeriod:
    name: str
    start_date: date
    end_date: date
    payment_date: date


def _add_months(d: date, months: int) -> date:
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    last_day = (date(year + (month // 12), (month % 12) + 1, 1) - timedelta(days=1)).day
    return date(year, month, min(d.day, last_day))


def _format_period_name(schedule: PaySchedule, start: date, end: date) -> str:
    if schedule.frequency == PaySchedule.Frequency.MONTHLY:
        return f"{schedule.name} – {start.strftime('%b %Y')}"
    return f"{schedule.name} – {start.strftime('%b %d')} to {end.strftime('%b %d, %Y')}"


def derive_next_period(schedule: PaySchedule) -> DerivedPeriod:
    """Compute the next period (start, end, payment_date, auto name) for a schedule.

    Walks forward from the latest existing period (or anchor) by one
    cadence step. Always returns a fresh, non-persisted result.
    """
    last = (
        PayrollPeriod.objects.filter(schedule=schedule)
        .order_by("-end_date")
        .first()
    )

    if last:
        cursor_start = last.end_date + timedelta(days=1)
    else:
        cursor_start = schedule.anchor_date

    if schedule.frequency == PaySchedule.Frequency.MONTHLY:
        end = _add_months(cursor_start, 1) - timedelta(days=1)
    elif schedule.frequency == PaySchedule.Frequency.BIWEEKLY:
        end = cursor_start + timedelta(days=13)
    else:  # WEEKLY
        end = cursor_start + timedelta(days=6)

    payment_date = end + timedelta(days=schedule.payment_day_offset or 0)

    return DerivedPeriod(
        name=_format_period_name(schedule, cursor_start, end),
        start_date=cursor_start,
        end_date=end,
        payment_date=payment_date,
    )


# ---------------------------------------------------------------------------
# Tax evaluation
# ---------------------------------------------------------------------------


_FORMULA_BUILTINS = {"min": min, "max": max, "abs": abs, "Decimal": Decimal}

FORMULA_GUIDE = {
    "variables": ["gross", "basic", "allowances", "deductions", "taxable_gross"],
    "helpers": ["min", "max", "abs", "Decimal"],
    "templates": [
        {"label": "10% of gross", "formula": "gross * Decimal('0.10')"},
        {"label": "5% of basic capped at 500", "formula": "min(basic * Decimal('0.05'), Decimal('500'))"},
        {"label": "Fixed 150", "formula": "Decimal('150')"},
        {"label": "Taxable gross floor", "formula": "max(taxable_gross, Decimal('0'))"},
    ],
}


def _evaluate_formula(formula: str, ctx: dict) -> Decimal:
    """Evaluate a tax formula in a restricted namespace.

    Only allows the variables in ``ctx`` plus a small set of safe builtins.
    No imports, no attribute access on hidden globals.
    """
    if not formula or not formula.strip():
        return ZERO
    safe_globals = {"__builtins__": {}}
    safe_globals.update(_FORMULA_BUILTINS)
    safe_locals = {k: v for k, v in ctx.items()}
    result = eval(formula, safe_globals, safe_locals)  # noqa: S307 - intentional sandbox
    return Decimal(str(result))


def get_formula_guide() -> dict:
    return FORMULA_GUIDE


def preview_formula_amount(
    *,
    calculation_type: str,
    value: Decimal | str | int | float | None,
    formula: str,
    applies_to: str,
    gross: Decimal,
    basic: Decimal,
    allowances: Decimal,
    deductions: Decimal,
) -> dict:
    taxable_gross = gross
    ctx = {
        "gross": Decimal(gross or 0),
        "basic": Decimal(basic or 0),
        "allowances": Decimal(allowances or 0),
        "deductions": Decimal(deductions or 0),
        "taxable_gross": Decimal(taxable_gross or 0),
    }

    if applies_to == "basic":
        base = ctx["basic"]
    elif applies_to == "taxable_gross":
        base = ctx["taxable_gross"]
    else:
        base = ctx["gross"]

    if calculation_type == "flat":
        amount = Decimal(value or 0)
    elif calculation_type == "percentage":
        amount = (base * Decimal(value or 0)) / Decimal("100")
    else:
        amount = _evaluate_formula(formula, ctx)

    amount = amount.quantize(Decimal("0.01"))
    return {
        "amount": str(amount),
        "base": str(base.quantize(Decimal("0.01"))),
        "context": {k: str(v.quantize(Decimal("0.01"))) for k, v in ctx.items()},
    }


def _base_for_rule(rule: TaxRule, ctx: dict) -> Decimal:
    if rule.applies_to == TaxRule.AppliesTo.GROSS:
        return ctx["gross"]
    if rule.applies_to == TaxRule.AppliesTo.BASIC:
        return ctx["basic"]
    return ctx["taxable_gross"]


def apply_tax_rules(
    *,
    rules: Iterable[TaxRule],
    gross: Decimal,
    basic: Decimal,
    allowances: Decimal,
    deductions: Decimal,
    on_date: date,
    overrides: dict | None = None,
) -> tuple[Decimal, list[dict]]:
    """Evaluate the given tax rules and return ``(total, breakdown)``.

    ``overrides`` is an optional ``{rule_id: EmployeeTaxRuleOverride}`` map. When
    present and active, an override replaces the corresponding rule fields for
    this evaluation only.
    """
    taxable_gross = gross  # MVP: every allowance is taxable; can refine later
    ctx = {
        "gross": gross,
        "basic": basic,
        "allowances": allowances,
        "deductions": deductions,
        "taxable_gross": taxable_gross,
    }

    overrides = overrides or {}
    total = ZERO
    breakdown: list[dict] = []
    for rule in sorted(rules, key=lambda r: r.priority):
        if not rule.applies_on(on_date):
            continue
        ov = overrides.get(rule.id)
        if ov is not None and not ov.is_active:
            ov = None
        calc = (ov.calculation_type if ov and ov.calculation_type else rule.calculation_type)
        applies_to = (ov.applies_to if ov and ov.applies_to else rule.applies_to)
        value = ov.value if ov and ov.value is not None else rule.value
        formula = (ov.formula if ov and ov.formula else rule.formula)
        if applies_to == TaxRule.AppliesTo.GROSS:
            base = ctx["gross"]
        elif applies_to == TaxRule.AppliesTo.BASIC:
            base = ctx["basic"]
        else:
            base = ctx["taxable_gross"]
        if calc == TaxRule.CalculationType.FLAT:
            amount = Decimal(value or 0)
        elif calc == TaxRule.CalculationType.PERCENTAGE:
            amount = (Decimal(base) * Decimal(value or 0)) / Decimal("100")
        else:  # FORMULA
            amount = _evaluate_formula(formula, ctx)
        amount = amount.quantize(Decimal("0.01"))
        total += amount
        breakdown.append(
            {
                "rule_id": str(rule.id),
                "name": rule.name,
                "calculation_type": calc,
                "applies_to": applies_to,
                "base": str(base),
                "amount": str(amount),
                "overridden": bool(ov),
            }
        )
    return total.quantize(Decimal("0.01")), breakdown


# ---------------------------------------------------------------------------
# Payslip generation
# ---------------------------------------------------------------------------


def _quantize(value: Decimal) -> Decimal:
    return Decimal(value or 0).quantize(Decimal("0.01"))


def _resolve_item_amount(item: PayrollItem, *, basic: Decimal, gross: Decimal) -> Decimal:
    """Compute an item's effective amount based on its calculation type.

    For PERCENTAGE/FORMULA, ``basic`` and ``gross`` provide the base context.
    Falls back to the stored ``amount`` for legacy rows without a calc_type.
    """
    calc = getattr(item, "calculation_type", None) or PayrollItem.CalculationType.FLAT
    if calc == PayrollItem.CalculationType.FLAT:
        # Prefer explicit value, fallback to legacy amount column
        if item.value:
            return _quantize(Decimal(item.value))
        return _quantize(Decimal(item.amount or 0))
    base = basic if item.applies_to == PayrollItem.AppliesTo.BASIC else gross
    if calc == PayrollItem.CalculationType.PERCENTAGE:
        return _quantize((Decimal(base) * Decimal(item.value or 0)) / Decimal("100"))
    # FORMULA
    ctx = {
        "gross": Decimal(gross or 0),
        "basic": Decimal(basic or 0),
        "allowances": ZERO,
        "deductions": ZERO,
        "taxable_gross": Decimal(gross or 0),
    }
    return _quantize(_evaluate_formula(item.formula, ctx))


def _build_payslip_payload(employee, run: PayrollRun) -> dict:
    """Compute a fresh payslip payload for ``employee`` against ``run``."""
    period = run.period
    schedule = period.schedule
    on_date = period.end_date

    basic = _quantize(employee.basic_salary or 0)

    items = [
        item
        for item in employee.payroll_items.all()
        if item.applies_on(on_date)
    ]
    # Estimate gross with FLAT/percentage-of-basic only first (to feed formula items).
    pre_gross = basic
    resolved: list[tuple[PayrollItem, Decimal]] = []
    for it in items:
        amt = _resolve_item_amount(it, basic=basic, gross=pre_gross)
        resolved.append((it, amt))

    allowance_total = _quantize(
        sum((amt for it, amt in resolved if it.item_type == PayrollItem.ItemType.ALLOWANCE), ZERO)
    )
    deduction_total = _quantize(
        sum((amt for it, amt in resolved if it.item_type == PayrollItem.ItemType.DEDUCTION), ZERO)
    )

    overtime_hours = ZERO  # editable in DRAFT
    overtime_pay = _quantize(
        Decimal(employee.hourly_rate or 0) * overtime_hours * Decimal(schedule.overtime_multiplier or 0)
    )

    gross = _quantize(basic + allowance_total + overtime_pay)

    rules = list(employee.tax_rules.all()) or list(TaxRule.objects.filter(is_active=True))
    overrides = {
        ov.rule_id: ov
        for ov in EmployeeTaxRuleOverride.objects.filter(
            employee=employee, is_active=True
        )
    }
    tax, tax_breakdown = apply_tax_rules(
        rules=rules,
        gross=gross,
        basic=basic,
        allowances=allowance_total,
        deductions=deduction_total,
        on_date=on_date,
        overrides=overrides,
    )

    net = _quantize(gross - tax - deduction_total)

    return {
        "currency": schedule.currency,
        "basic_salary": basic,
        "overtime_hours": overtime_hours,
        "overtime_pay": overtime_pay,
        "unpaid_leave_days": ZERO,
        "allowances": allowance_total,
        "deductions": deduction_total,
        "tax": tax,
        "gross_pay": gross,
        "net_pay": net,
        "breakdown": {
            "allowances": [
                {"id": str(it.id), "name": it.name, "amount": str(amt)}
                for it, amt in resolved
                if it.item_type == PayrollItem.ItemType.ALLOWANCE
            ],
            "deductions": [
                {"id": str(it.id), "name": it.name, "amount": str(amt)}
                for it, amt in resolved
                if it.item_type == PayrollItem.ItemType.DEDUCTION
            ],
            "tax": tax_breakdown,
        },
    }


@transaction.atomic
def generate_payslips(run: PayrollRun, *, regenerate: bool = False) -> list[Payslip]:
    """Generate payslips for all payroll-ready employees on the given run.

    Idempotency: if payslips already exist for this run, raises unless
    ``regenerate=True`` AND the run is still DRAFT.
    """
    from hr.models import Employee  # local import to avoid app-loading cycles

    if run.status != PayrollRun.Status.DRAFT:
        raise ValueError("Payslips can only be generated for runs in DRAFT status.")

    existing = list(run.payslips.all())
    if existing:
        if not regenerate:
            raise ValueError(
                "This run already has payslips. Pass regenerate=True to recreate them.",
            )
        run.payslips.all().delete()

    employees = (
        Employee.objects.filter(employment_status=Employee.EmploymentStatus.ACTIVE)
        .prefetch_related("payroll_items", "tax_rules")
    )

    payslips: list[Payslip] = []
    for employee in employees:
        readiness = employee.payroll_readiness()
        if not readiness["ready"]:
            continue
        payload = _build_payslip_payload(employee, run)
        payslips.append(
            Payslip.objects.create(
                payroll_run=run,
                employee=employee,
                generated_at=timezone.now(),
                **payload,
            )
        )
    return payslips


@transaction.atomic
def recalculate_payslip(payslip: Payslip) -> Payslip:
    """Re-snapshot a single payslip from current employee data.

    Only allowed when the parent run is still DRAFT.
    """
    if payslip.payroll_run.status != PayrollRun.Status.DRAFT:
        raise ValueError("Payslips can only be recalculated while the run is in DRAFT.")

    payload = _build_payslip_payload(payslip.employee, payslip.payroll_run)
    overtime_hours = payslip.overtime_hours or ZERO
    unpaid_leave_days = payslip.unpaid_leave_days or ZERO

    # Preserve user-edited overtime_hours and unpaid_leave_days; recompute deltas.
    schedule = payslip.payroll_run.period.schedule
    employee = payslip.employee
    overtime_pay = _quantize(
        Decimal(employee.hourly_rate or 0)
        * Decimal(overtime_hours)
        * Decimal(schedule.overtime_multiplier or 0)
    )
    leave_deduction = ZERO
    if unpaid_leave_days and employee.salary_type == "monthly":
        # Pro-rata: subtract (basic / 22) per unpaid day. 22 = working days proxy.
        leave_deduction = _quantize(
            (Decimal(employee.basic_salary or 0) / Decimal("22")) * Decimal(unpaid_leave_days)
        )

    basic = _quantize(Decimal(employee.basic_salary or 0) - leave_deduction)
    gross = _quantize(basic + payload["allowances"] + overtime_pay)

    rules = list(employee.tax_rules.all()) or list(TaxRule.objects.filter(is_active=True))
    overrides = {
        ov.rule_id: ov
        for ov in EmployeeTaxRuleOverride.objects.filter(
            employee=employee, is_active=True
        )
    }
    tax, tax_breakdown = apply_tax_rules(
        rules=rules,
        gross=gross,
        basic=basic,
        allowances=payload["allowances"],
        deductions=payload["deductions"],
        on_date=payslip.payroll_run.period.end_date,
        overrides=overrides,
    )
    net = _quantize(gross - tax - payload["deductions"])

    payslip.basic_salary = basic
    payslip.overtime_hours = overtime_hours
    payslip.overtime_pay = overtime_pay
    payslip.unpaid_leave_days = unpaid_leave_days
    payslip.allowances = payload["allowances"]
    payslip.deductions = payload["deductions"]
    payslip.tax = tax
    payslip.gross_pay = gross
    payslip.net_pay = net
    payslip.breakdown = {
        **payload["breakdown"],
        "tax": tax_breakdown,
    }
    payslip.save()
    return payslip


# ---------------------------------------------------------------------------
# Status transitions
# ---------------------------------------------------------------------------


@transaction.atomic
def submit_for_approval(run: PayrollRun) -> PayrollRun:
    if run.status != PayrollRun.Status.DRAFT:
        raise ValueError("Only DRAFT runs can be submitted for approval.")
    if not run.payslips.exists():
        raise ValueError("Cannot submit a run with no payslips.")
    run.status = PayrollRun.Status.PENDING
    run.save(update_fields=["status", "updated_at", "updated_by"])
    return run


@transaction.atomic
def approve_run(run: PayrollRun) -> PayrollRun:
    if run.status not in (PayrollRun.Status.DRAFT, PayrollRun.Status.PENDING):
        raise ValueError("Only DRAFT or PENDING runs can be approved.")
    run.status = PayrollRun.Status.APPROVED
    run.approved_at = timezone.now()
    run.save(update_fields=["status", "approved_at", "updated_at", "updated_by"])
    return run


@transaction.atomic
def mark_paid(run: PayrollRun) -> PayrollRun:
    if run.status != PayrollRun.Status.APPROVED:
        raise ValueError("Only APPROVED runs can be marked as paid.")
    run.status = PayrollRun.Status.PAID
    run.paid_at = timezone.now()
    run.period.is_closed = True
    run.period.save(update_fields=["is_closed", "updated_at", "updated_by"])
    run.save(update_fields=["status", "paid_at", "updated_at", "updated_by"])
    return run


@transaction.atomic
def revert_to_draft(run: PayrollRun) -> PayrollRun:
    """Force a run back to DRAFT regardless of current status.

    Intended for admin-only correction flows. Clears approved_at / paid_at
    and re-opens the related period if it was closed by mark_paid.
    """
    if run.status == PayrollRun.Status.DRAFT:
        return run
    run.status = PayrollRun.Status.DRAFT
    run.approved_at = None
    run.paid_at = None
    run.save(update_fields=["status", "approved_at", "paid_at", "updated_at", "updated_by"])
    if run.period.is_closed:
        run.period.is_closed = False
        run.period.save(update_fields=["is_closed", "updated_at", "updated_by"])
    return run
