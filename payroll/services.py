"""Payroll business logic — period derivation, tax application, payslip generation."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Iterable

from django.db import transaction
from django.utils import timezone

from .models import (
    AmountCalculationType,
    PayrollItem,
    PayrollPeriod,
    PayrollRun,
    Payslip,
    PaySchedule,
    TargetSalaryBy,
    TaxRule,
)

ZERO = Decimal("0.00")

_CALC_FLAT = AmountCalculationType.FLAT
_CALC_PERCENTAGE = AmountCalculationType.PERCENTAGE
_CALC_FORMULA = AmountCalculationType.FORMULA


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


_FORMULA_BUILTINS = {
    "min": lambda *args: min(Decimal(str(arg)) for arg in args),
    "max": lambda *args: max(Decimal(str(arg)) for arg in args),
    "abs": lambda value: abs(Decimal(str(value))),
    "Decimal": Decimal,
}

FORMULA_GUIDE = {
    "variables": ["gross", "basic", "allowances", "deductions", "taxable_gross"],
    "helpers": ["min", "max", "abs", "Decimal"],
    "templates": [
        {"label": "10% of gross", "formula": "gross * 0.10"},
        {"label": "5% of basic capped at 500", "formula": "min(basic * 0.05, 500)"},
        {"label": "Fixed 150", "formula": "150"},
        {"label": "Taxable gross floor", "formula": "max(taxable_gross, 0)"},
    ],
}


class _DecimalLiteralTransformer(ast.NodeTransformer):
    """Rewrite numeric literals in formulas to Decimal(...) for safe eval."""

    def visit_Constant(self, node: ast.Constant):
        if isinstance(node.value, bool):
            return node
        if isinstance(node.value, (int, float)):
            return ast.copy_location(
                ast.Call(
                    func=ast.Name(id="Decimal", ctx=ast.Load()),
                    args=[ast.Constant(value=str(node.value))],
                    keywords=[],
                ),
                node,
            )
        return node


def _compile_formula(formula: str):
    tree = ast.parse(formula.strip(), mode="eval")
    tree = _DecimalLiteralTransformer().visit(tree)
    ast.fix_missing_locations(tree)
    return compile(tree, "<formula>", "eval")


def _evaluate_formula(formula: str, ctx: dict) -> Decimal:
    """Evaluate a tax formula in a restricted namespace.

    Only allows the variables in ``ctx`` plus a small set of safe builtins.
    No imports, no attribute access on hidden globals.
    """
    if not formula or not formula.strip():
        return ZERO
    safe_globals = {"__builtins__": {}}
    safe_globals.update(_FORMULA_BUILTINS)
    safe_locals = {k: Decimal(str(v)) for k, v in ctx.items()}
    try:
        compiled = _compile_formula(formula)
        result = eval(compiled, safe_globals, safe_locals)  # noqa: S307 - intentional sandbox
    except SyntaxError as exc:
        raise SyntaxError(str(exc)) from exc
    return Decimal(str(result))


def get_formula_guide() -> dict:
    return FORMULA_GUIDE


def _normalize_salary_for_bracket(
    basic: Decimal,
    *,
    target_salary_by: str,
) -> Decimal:
    """Convert employee basic salary to the basis used for bracket matching."""
    if target_salary_by == TargetSalaryBy.ANNUAL:
        return Decimal(basic or 0) * Decimal("12")
    return Decimal(basic or 0)


def _salary_in_bracket(
    salary: Decimal,
    *,
    target_min: Decimal,
    target_max: Decimal,
) -> bool:
    """Return True when ``salary`` falls within the bracket bounds.

    ``0`` min means no lower bound; ``0`` max means no upper bound.
    """
    min_bound = Decimal(target_min or 0)
    max_bound = Decimal(target_max or 0)
    if min_bound > 0 and salary < min_bound:
        return False
    if max_bound > 0 and salary > max_bound:
        return False
    return True


def match_amount_rule(rules, *, basic: Decimal):
    """Pick the first amount rule whose salary bracket contains ``basic``."""
    for rule in rules:
        bracket_salary = _normalize_salary_for_bracket(
            basic,
            target_salary_by=rule.target_salary_by,
        )
        if _salary_in_bracket(
            bracket_salary,
            target_min=rule.target_salary_min,
            target_max=rule.target_salary_max,
        ):
            return rule
    return None


def _resolve_calc_base(applies_to: str, ctx: dict) -> Decimal:
    if applies_to == "basic":
        return ctx["basic"]
    if applies_to == "taxable_gross":
        return ctx["taxable_gross"]
    return ctx["gross"]


def _normalize_calculation_type(calculation_type) -> str:
    """Return a normalized calculation type string (flat/percentage/formula)."""
    calc = calculation_type or _CALC_FLAT
    if hasattr(calc, "value"):
        calc = calc.value
    normalized = str(calc).strip().lower()
    if normalized in (_CALC_FLAT, _CALC_PERCENTAGE, _CALC_FORMULA):
        return normalized
    return _CALC_FLAT


def _coerce_rule_calc_fields(rule) -> None:
    """Normalize bracket rule calc fields before amount resolution."""
    calc = _normalize_calculation_type(getattr(rule, "calculation_type", None))
    rule.calculation_type = calc
    if calc != _CALC_FORMULA:
        rule.formula = ""


def build_preview_amount_rule_objects(validated_items: list):
    """Build lightweight rule objects for preview endpoints."""
    rules = []
    for item in validated_items:
        rule = SimpleNamespace()
        for key, value in item.items():
            setattr(rule, key, value)
        _coerce_rule_calc_fields(rule)
        rules.append(rule)
    return rules


def resolve_amount_from_rule(rule, *, ctx: dict) -> Decimal:
    """Compute amount from a bracket rule record."""
    _coerce_rule_calc_fields(rule)
    base = _resolve_calc_base(rule.applies_to, ctx)
    calc = rule.calculation_type
    if calc == _CALC_FLAT:
        amount = Decimal(rule.value or 0)
    elif calc == _CALC_PERCENTAGE:
        amount = (Decimal(base) * Decimal(rule.value or 0)) / Decimal("100")
    elif calc == _CALC_FORMULA:
        amount = _evaluate_formula(getattr(rule, "formula", "") or "", ctx)
    else:
        amount = ZERO
    if rule.salary_limit is not None and Decimal(rule.salary_limit or 0) > 0:
        amount = min(amount, Decimal(rule.salary_limit))
    return amount.quantize(Decimal("0.01"))


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
    target_salary_min: Decimal | str | int | float | None = None,
    target_salary_max: Decimal | str | int | float | None = None,
    target_salary_by: str = TargetSalaryBy.PER_PERIOD,
    salary_limit: Decimal | str | int | float | None = None,
) -> dict:
    taxable_gross = gross
    ctx = {
        "gross": Decimal(gross or 0),
        "basic": Decimal(basic or 0),
        "allowances": Decimal(allowances or 0),
        "deductions": Decimal(deductions or 0),
        "taxable_gross": Decimal(taxable_gross or 0),
    }

    bracket_salary = _normalize_salary_for_bracket(
        ctx["basic"],
        target_salary_by=target_salary_by,
    )
    matched = _salary_in_bracket(
        bracket_salary,
        target_min=Decimal(str(target_salary_min or 0)),
        target_max=Decimal(str(target_salary_max or 0)),
    )

    base = _resolve_calc_base(applies_to, ctx)

    if not matched:
        return {
            "amount": "0.00",
            "base": str(base.quantize(Decimal("0.01"))),
            "matched": False,
            "bracket_salary": str(bracket_salary.quantize(Decimal("0.01"))),
            "context": {k: str(v.quantize(Decimal("0.01"))) for k, v in ctx.items()},
        }

    preview_rule = SimpleNamespace(
        calculation_type=calculation_type,
        value=value,
        formula=formula,
        applies_to=applies_to,
        salary_limit=salary_limit,
    )
    amount = resolve_amount_from_rule(preview_rule, ctx=ctx)
    return {
        "amount": str(amount),
        "base": str(base.quantize(Decimal("0.01"))),
        "matched": True,
        "bracket_salary": str(bracket_salary.quantize(Decimal("0.01"))),
        "context": {k: str(v.quantize(Decimal("0.01"))) for k, v in ctx.items()},
    }


def preview_amount_rules(
    *,
    rules: list,
    gross: Decimal,
    basic: Decimal,
    allowances: Decimal,
    deductions: Decimal,
) -> dict:
    """Preview all bracket rules and return per-rule results."""
    ctx = {
        "gross": Decimal(gross or 0),
        "basic": Decimal(basic or 0),
        "allowances": Decimal(allowances or 0),
        "deductions": Decimal(deductions or 0),
        "taxable_gross": Decimal(gross or 0),
    }
    matched_rule = match_amount_rule(rules, basic=ctx["basic"])
    breakdown = []
    for rule in rules:
        _coerce_rule_calc_fields(rule)
        bracket_salary = _normalize_salary_for_bracket(
            ctx["basic"],
            target_salary_by=rule.target_salary_by,
        )
        in_bracket = _salary_in_bracket(
            bracket_salary,
            target_min=rule.target_salary_min,
            target_max=rule.target_salary_max,
        )
        amount = ZERO
        formula_error = None
        if in_bracket:
            try:
                amount = resolve_amount_from_rule(rule, ctx=ctx)
            except (SyntaxError, ValueError, TypeError, ArithmeticError) as exc:
                formula_error = str(exc)
                amount = ZERO
        breakdown.append(
            {
                "rule_id": str(getattr(rule, "id", "")),
                "calculation_type": rule.calculation_type,
                "applies_to": rule.applies_to,
                "target_salary_min": str(rule.target_salary_min),
                "target_salary_max": str(rule.target_salary_max),
                "target_salary_by": rule.target_salary_by,
                "matched": rule is matched_rule,
                "in_bracket": in_bracket,
                "amount": str(amount),
                **({"formula_error": formula_error} if formula_error else {}),
            }
        )
    effective = ZERO
    formula_error = None
    if matched_rule:
        try:
            effective = resolve_amount_from_rule(matched_rule, ctx=ctx)
        except (SyntaxError, ValueError, TypeError, ArithmeticError) as exc:
            formula_error = str(exc)
            effective = ZERO
    result = {
        "amount": str(effective.quantize(Decimal("0.01"))),
        "matched": bool(matched_rule),
        "breakdown": breakdown,
    }
    if formula_error:
        result["formula_error"] = formula_error
    return result


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
    """Evaluate tax rules using bracket-based amount rules.

    Each tax rule resolves to zero when no amount rule matches the employee's
    salary bracket.
    """
    taxable_gross = gross
    ctx = {
        "gross": gross,
        "basic": basic,
        "allowances": allowances,
        "deductions": deductions,
        "taxable_gross": taxable_gross,
    }

    total = ZERO
    breakdown: list[dict] = []
    for rule in sorted(rules, key=lambda r: r.priority):
        if not rule.applies_on(on_date):
            continue
        amount_rules = list(rule.amount_rules.all())
        matched = match_amount_rule(amount_rules, basic=basic)
        if matched is None:
            breakdown.append(
                {
                    "rule_id": str(rule.id),
                    "name": rule.name,
                    "amount": "0.00",
                    "matched": False,
                }
            )
            continue
        amount = resolve_amount_from_rule(matched, ctx=ctx)
        total += amount
        breakdown.append(
            {
                "rule_id": str(rule.id),
                "name": rule.name,
                "amount_rule_id": str(matched.id),
                "calculation_type": matched.calculation_type,
                "applies_to": matched.applies_to,
                "base": str(_resolve_calc_base(matched.applies_to, ctx)),
                "amount": str(amount),
                "matched": True,
            }
        )
    return total.quantize(Decimal("0.01")), breakdown


# ---------------------------------------------------------------------------
# Payslip generation
# ---------------------------------------------------------------------------


def _quantize(value: Decimal) -> Decimal:
    return Decimal(value or 0).quantize(Decimal("0.01"))


def _resolve_item_amount(item: PayrollItem, *, basic: Decimal, gross: Decimal) -> Decimal:
    """Compute an item's effective amount from its catalog type's amount rules."""
    item_type = item.item_type_ref
    if item_type is None:
        return ZERO
    rules = list(item_type.amount_rules.all())
    matched = match_amount_rule(rules, basic=basic)
    if matched is None:
        return ZERO
    ctx = {
        "gross": Decimal(gross or 0),
        "basic": Decimal(basic or 0),
        "allowances": ZERO,
        "deductions": ZERO,
        "taxable_gross": Decimal(gross or 0),
    }
    return resolve_amount_from_rule(matched, ctx=ctx)


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

    rules = list(
        employee.tax_rules.prefetch_related("amount_rules").all()
    ) or list(TaxRule.objects.filter(is_active=True).prefetch_related("amount_rules"))
    tax, tax_breakdown = apply_tax_rules(
        rules=rules,
        gross=gross,
        basic=basic,
        allowances=allowance_total,
        deductions=deduction_total,
        on_date=on_date,
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
        .prefetch_related("payroll_items__item_type_ref__amount_rules", "tax_rules__amount_rules")
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

    rules = list(
        employee.tax_rules.prefetch_related("amount_rules").all()
    ) or list(TaxRule.objects.filter(is_active=True).prefetch_related("amount_rules"))
    tax, tax_breakdown = apply_tax_rules(
        rules=rules,
        gross=gross,
        basic=basic,
        allowances=payload["allowances"],
        deductions=payload["deductions"],
        on_date=payslip.payroll_run.period.end_date,
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
