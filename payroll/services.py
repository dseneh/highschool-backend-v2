"""Payroll business logic — period derivation, tax application, payslip generation."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Iterable

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .models import (
    AmountCalculationType,
    ItemAppliesTo,
    PayrollItem,
    PayrollItemType,
    PayrollPayslipColumnGroup,
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
    "variables": ["gross", "basic", "annual", "allowances", "deductions", "taxable_gross"],
    "helpers": ["min", "max", "abs", "Decimal"],
    "templates": [
        {"label": "10% of gross", "formula": "gross * 0.10"},
        {"label": "5% of basic capped at 500", "formula": "min(basic * 0.05, 500)"},
        {"label": "2% of annual salary", "formula": "annual * 0.02"},
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


def periods_per_year_for_schedule(schedule) -> Decimal:
    """Map pay schedule frequency to annualization factor for per-period basic pay."""
    if schedule is None:
        return Decimal("12")
    frequency = getattr(schedule, "frequency", None) or PaySchedule.Frequency.MONTHLY
    if frequency == PaySchedule.Frequency.WEEKLY:
        return Decimal("52")
    if frequency == PaySchedule.Frequency.BIWEEKLY:
        return Decimal("26")
    return Decimal("12")


def annual_salary_from_period_basic(
    basic: Decimal,
    *,
    periods_per_year: Decimal | None = None,
) -> Decimal:
    pp = periods_per_year or Decimal("12")
    return Decimal(basic or 0) * pp


def _normalize_applies_to(applies_to) -> str:
    """Normalize applies_to from model enums or legacy strings."""
    if applies_to is None:
        return ItemAppliesTo.GROSS
    if hasattr(applies_to, "value"):
        applies_to = applies_to.value
    normalized = str(applies_to).strip().lower()
    if normalized in ("basic", "gross", "taxable_gross", "annual"):
        return normalized
    return ItemAppliesTo.GROSS


def build_amount_rule_context(
    *,
    gross: Decimal,
    basic: Decimal,
    allowances: Decimal = ZERO,
    deductions: Decimal = ZERO,
    periods_per_year: Decimal | None = None,
    annual_salary: Decimal | None = None,
) -> dict:
    pp = periods_per_year or Decimal("12")
    gross_d = Decimal(gross or 0)
    basic_d = Decimal(basic or 0)
    allowances_d = Decimal(allowances or 0)
    annual = (
        Decimal(annual_salary or 0)
        if annual_salary is not None
        else annual_salary_from_period_basic(basic_d, periods_per_year=pp)
    )
    return {
        "gross": gross_d,
        "basic": basic_d,
        "allowances": allowances_d,
        "deductions": Decimal(deductions or 0),
        "taxable_gross": (basic_d + allowances_d).quantize(Decimal("0.01")),
        "annual": annual,
        "periods_per_year": pp,
    }


def _bracket_salary_for_amount_rule(
    rule,
    *,
    ctx: dict | None = None,
    basic: Decimal,
    periods_per_year: Decimal | None = None,
    annual_salary: Decimal | None = None,
) -> Decimal:
    """Salary basis used to test bracket min/max for an amount rule."""
    target_by = getattr(rule, "target_salary_by", TargetSalaryBy.PER_PERIOD) or TargetSalaryBy.PER_PERIOD
    if target_by == TargetSalaryBy.ANNUAL:
        return _normalize_salary_for_bracket(
            basic,
            target_salary_by=TargetSalaryBy.ANNUAL,
            periods_per_year=periods_per_year,
            annual_salary=annual_salary,
        )

    if ctx is None:
        ctx = build_amount_rule_context(
            gross=basic,
            basic=basic,
            periods_per_year=periods_per_year,
            annual_salary=annual_salary,
        )

    applies_to = _normalize_applies_to(getattr(rule, "applies_to", None))
    if applies_to == "annual":
        return ctx.get("annual") or annual_salary_from_period_basic(
            ctx["basic"],
            periods_per_year=ctx.get("periods_per_year"),
        )
    if applies_to == "gross":
        return ctx["gross"]
    if applies_to == "taxable_gross":
        return ctx["taxable_gross"]
    return ctx["basic"]


def _normalize_salary_for_bracket(
    basic: Decimal,
    *,
    target_salary_by: str,
    periods_per_year: Decimal | None = None,
    annual_salary: Decimal | None = None,
) -> Decimal:
    """Convert employee pay to the salary basis used for bracket matching."""
    if target_salary_by == TargetSalaryBy.ANNUAL:
        if annual_salary is not None:
            return Decimal(annual_salary or 0)
        return annual_salary_from_period_basic(
            basic,
            periods_per_year=periods_per_year,
        )
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


def match_amount_rule(
    rules,
    *,
    basic: Decimal,
    periods_per_year: Decimal | None = None,
    annual_salary: Decimal | None = None,
    ctx: dict | None = None,
):
    """Pick the first amount rule whose salary bracket contains the employee.

    Bracket matching uses the rule's ``applies_to`` basis (gross, taxable gross,
    basic, or annual) when ``target_salary_by`` is per-period.

    When no bracket matches, fall back to a catch-all rule (min=0 and max=0)
    if one exists so item types with a single open bracket still apply to all
    salaries.
    """
    catch_all = None
    ordered_rules = sorted(
        rules,
        key=lambda rule: (
            int(getattr(rule, "sort_order", 0) or 0),
            Decimal(getattr(rule, "target_salary_min", 0) or 0),
        ),
    )
    for rule in ordered_rules:
        bracket_salary = _bracket_salary_for_amount_rule(
            rule,
            ctx=ctx,
            basic=basic,
            periods_per_year=periods_per_year,
            annual_salary=annual_salary,
        )
        min_bound = Decimal(rule.target_salary_min or 0)
        max_bound = Decimal(rule.target_salary_max or 0)
        if min_bound <= 0 and max_bound <= 0:
            catch_all = rule
        if _salary_in_bracket(
            bracket_salary,
            target_min=min_bound,
            target_max=max_bound,
        ):
            return rule
    return catch_all


def _ordered_amount_rules(item_type) -> list:
    return list(
        item_type.amount_rules.order_by("sort_order", "target_salary_min"),
    )


def _pick_amount_rule(
    rules,
    *,
    basic: Decimal,
    ignore_brackets: bool = False,
    periods_per_year: Decimal | None = None,
    annual_salary: Decimal | None = None,
    ctx: dict | None = None,
):
    """Return ``(rule, matched)`` for amount resolution.

    Post-net additions skip bracket checks and always use the first configured
    rule so assigned employees receive the amount regardless of salary/tax band.
    """
    ordered = sorted(
        rules,
        key=lambda rule: (
            int(getattr(rule, "sort_order", 0) or 0),
            Decimal(getattr(rule, "target_salary_min", 0) or 0),
        ),
    )
    if not ordered:
        return None, False
    if ignore_brackets:
        return ordered[0], True
    matched = match_amount_rule(
        ordered,
        basic=basic,
        periods_per_year=periods_per_year,
        annual_salary=annual_salary,
        ctx=ctx,
    )
    if matched is not None:
        return matched, True
    return None, False


def _resolve_calc_base(applies_to, ctx: dict) -> Decimal:
    normalized = _normalize_applies_to(applies_to)
    if normalized == "basic":
        return ctx["basic"]
    if normalized == "annual":
        return ctx.get("annual") or annual_salary_from_period_basic(
            ctx["basic"],
            periods_per_year=ctx.get("periods_per_year"),
        )
    if normalized == "taxable_gross":
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
    periods_per_year: Decimal | str | int | float | None = None,
) -> dict:
    pp = Decimal(str(periods_per_year or 12))
    ctx = build_amount_rule_context(
        gross=gross,
        basic=basic,
        allowances=allowances,
        deductions=deductions,
        periods_per_year=pp,
    )

    preview_rule = SimpleNamespace(
        target_salary_by=target_salary_by,
        applies_to=applies_to,
    )
    bracket_salary = _bracket_salary_for_amount_rule(
        preview_rule,
        ctx=ctx,
        basic=ctx["basic"],
        periods_per_year=pp,
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
    periods_per_year: Decimal | None = None,
) -> dict:
    """Preview all bracket rules and return per-rule results."""
    ctx = build_amount_rule_context(
        gross=gross,
        basic=basic,
        allowances=allowances,
        deductions=deductions,
        periods_per_year=periods_per_year,
    )
    matched_rule = match_amount_rule(
        rules,
        basic=ctx["basic"],
        periods_per_year=ctx["periods_per_year"],
        ctx=ctx,
    )
    breakdown = []
    for rule in rules:
        _coerce_rule_calc_fields(rule)
        bracket_salary = _bracket_salary_for_amount_rule(
            rule,
            ctx=ctx,
            basic=ctx["basic"],
            periods_per_year=ctx["periods_per_year"],
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
    periods_per_year: Decimal | None = None,
    annual_salary: Decimal | None = None,
    overrides: dict | None = None,
) -> tuple[Decimal, list[dict]]:
    """Evaluate tax rules using bracket-based amount rules.

    Each tax rule resolves to zero when no amount rule matches the employee's
    salary bracket.
    """
    ctx = build_amount_rule_context(
        gross=gross,
        basic=basic,
        allowances=allowances,
        deductions=deductions,
        periods_per_year=periods_per_year,
        annual_salary=annual_salary,
    )

    total = ZERO
    breakdown: list[dict] = []
    for rule in sorted(rules, key=lambda r: r.priority):
        if not rule.applies_on(on_date):
            continue
        amount_rules = list(rule.amount_rules.all())
        matched = match_amount_rule(
            amount_rules,
            basic=basic,
            periods_per_year=ctx["periods_per_year"],
            annual_salary=annual_salary,
            ctx=ctx,
        )
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


def _item_catalog_kind(item: PayrollItem) -> str:
    ref = item.item_type_ref
    if ref is not None:
        return ref.item_type
    return item.item_type


def _item_is_taxable_addition(item: PayrollItem) -> bool:
    kind = _item_catalog_kind(item)
    if kind in (PayrollItemType.ItemType.DEDUCTION, PayrollItemType.ItemType.ADJUSTMENT):
        return False
    ref = item.item_type_ref
    if ref is None:
        return True
    return bool(ref.is_taxable)


def _summarize_payroll_items(
    resolved: list[tuple[PayrollItem, Decimal, bool]],
) -> dict:
    taxable_allowances = ZERO
    post_net_additions = ZERO
    deduction_total = ZERO
    allowance_lines: list[dict] = []
    adjustment_lines: list[dict] = []
    deduction_lines: list[dict] = []

    for item, amount, matched in resolved:
        amt = _quantize(amount)
        kind = _item_catalog_kind(item)
        line = {
            "id": str(item.id),
            "name": item.name,
            "amount": str(amt),
            "matched": matched,
            "override": bool(getattr(item, "override_calculation_type", None)),
        }
        item_type = item.item_type_ref
        if item_type is not None:
            line["item_type_id"] = str(item_type.id)
            line["item_type_name"] = item_type.name
        else:
            line["item_type_id"] = ""
            line["item_type_name"] = ""

        if amt == ZERO:
            if not matched:
                target_lines = (
                    deduction_lines
                    if kind == PayrollItemType.ItemType.DEDUCTION
                    else adjustment_lines
                    if not _item_is_taxable_addition(item)
                    else allowance_lines
                )
                target_lines.append(line)
            continue

        if kind == PayrollItemType.ItemType.DEDUCTION:
            deduction_total += amt
            deduction_lines.append(line)
            continue

        if _item_is_taxable_addition(item):
            taxable_allowances += amt
            allowance_lines.append(line)
        else:
            post_net_additions += amt
            adjustment_lines.append(line)

    return {
        "allowances": _quantize(taxable_allowances),
        "adjustments": _quantize(post_net_additions),
        "deductions": _quantize(deduction_total),
        "breakdown": {
            "allowances": allowance_lines,
            "adjustments": adjustment_lines,
            "deductions": deduction_lines,
        },
    }


def _load_item_type_payslip_column_groups(
    item_type_ids: Iterable[str] | None = None,
) -> dict[str, PayrollPayslipColumnGroup]:
    qs = PayrollItemType.objects.select_related("payslip_column_group").filter(
        payslip_column_group_id__isnull=False,
    )
    if item_type_ids is not None:
        ids = [value for value in item_type_ids if value]
        if not ids:
            return {}
        qs = qs.filter(id__in=ids)
    return {
        str(item_type.id): item_type.payslip_column_group
        for item_type in qs
    }


def _collect_breakdown_item_type_ids(breakdown: dict) -> set[str]:
    ids: set[str] = set()
    for bucket in ("allowances", "adjustments", "deductions"):
        for line in breakdown.get(bucket, []):
            item_type_id = (line.get("item_type_id") or "").strip()
            if item_type_id:
                ids.add(item_type_id)
    return ids


def _apply_payslip_column_layout_from_item_types(breakdown: dict) -> None:
    """Stamp display column ids on breakdown lines from item-type group assignments."""
    item_type_ids = _collect_breakdown_item_type_ids(breakdown)
    item_type_to_group = _load_item_type_payslip_column_groups(item_type_ids)
    for bucket in ("allowances", "adjustments", "deductions"):
        for line in breakdown.get(bucket, []):
            item_type_id = (line.get("item_type_id") or "").strip()
            if not item_type_id:
                line["table_column_id"] = ""
                line["table_column_label"] = ""
                continue
            group = item_type_to_group.get(item_type_id)
            if group is not None:
                line["table_column_id"] = f"group:{group.id}"
                line["table_column_label"] = group.label
            else:
                label = (line.get("item_type_name") or line.get("name") or "").strip()
                line["table_column_id"] = f"item:{item_type_id}"
                line["table_column_label"] = label


def _apply_payslip_column_layout_for_unassigned(breakdown: dict) -> None:
    """Apply item-type group/standalone layout only where no column is stamped yet."""
    item_type_ids = _collect_breakdown_item_type_ids(breakdown)
    item_type_to_group = _load_item_type_payslip_column_groups(item_type_ids)
    for bucket in ("allowances", "adjustments", "deductions"):
        for line in breakdown.get(bucket, []):
            if (line.get("table_column_id") or "").strip():
                continue
            item_type_id = (line.get("item_type_id") or "").strip()
            if not item_type_id:
                line["table_column_id"] = ""
                line["table_column_label"] = ""
                continue
            group = item_type_to_group.get(item_type_id)
            if group is not None:
                line["table_column_id"] = f"group:{group.id}"
                line["table_column_label"] = group.label
            else:
                label = (line.get("item_type_name") or line.get("name") or "").strip()
                line["table_column_id"] = f"item:{item_type_id}"
                line["table_column_label"] = label


def _preserve_breakdown_column_layout(new_breakdown: dict, old_breakdown: dict | None) -> None:
    """Keep existing table column assignments when recalculating a single payslip."""
    old_breakdown = old_breakdown or {}
    for bucket in ("allowances", "adjustments", "deductions"):
        old_by_type = {
            line.get("item_type_id"): line
            for line in old_breakdown.get(bucket, [])
            if line.get("item_type_id")
        }
        for line in new_breakdown.get(bucket, []):
            item_type_id = line.get("item_type_id") or ""
            if not item_type_id:
                line["table_column_id"] = ""
                line["table_column_label"] = ""
                continue
            previous = old_by_type.get(item_type_id)
            if previous is not None:
                line["table_column_id"] = previous.get("table_column_id") or ""
                line["table_column_label"] = previous.get("table_column_label") or ""
    _apply_payslip_column_layout_for_unassigned(new_breakdown)


def _payroll_item_override_rule(item: PayrollItem):
    calc_type = getattr(item, "override_calculation_type", None)
    if not calc_type:
        return None
    return SimpleNamespace(
        calculation_type=calc_type,
        value=getattr(item, "override_value", None),
        formula=getattr(item, "override_formula", "") or "",
        applies_to=getattr(item, "override_applies_to", None) or ItemAppliesTo.BASIC,
        salary_limit=None,
    )


def _resolve_item_amount(
    item: PayrollItem,
    *,
    basic: Decimal,
    gross: Decimal,
    allowances: Decimal = ZERO,
    deductions: Decimal = ZERO,
    ignore_brackets: bool = False,
    periods_per_year: Decimal | None = None,
    annual_salary: Decimal | None = None,
) -> tuple[Decimal, bool]:
    """Compute an item's effective amount from override or catalog type rules."""
    ctx = build_amount_rule_context(
        gross=gross,
        basic=basic,
        allowances=allowances,
        deductions=deductions,
        periods_per_year=periods_per_year,
        annual_salary=annual_salary,
    )
    override_rule = _payroll_item_override_rule(item)
    if override_rule is not None:
        return resolve_amount_from_rule(override_rule, ctx=ctx), True

    item_type = item.item_type_ref
    if item_type is None:
        return ZERO, False
    rules = _ordered_amount_rules(item_type)
    matched, bracket_matched = _pick_amount_rule(
        rules,
        basic=basic,
        ignore_brackets=ignore_brackets,
        periods_per_year=ctx["periods_per_year"],
        annual_salary=annual_salary,
        ctx=ctx,
    )
    if matched is None:
        return ZERO, False
    return resolve_amount_from_rule(matched, ctx=ctx), bracket_matched


def _resolve_payroll_items_for_employee(
    items: list[PayrollItem],
    *,
    basic: Decimal,
    overtime_pay: Decimal = ZERO,
    periods_per_year: Decimal | None = None,
    annual_salary: Decimal | None = None,
) -> dict:
    """Resolve assigned payroll items, iterating until taxable gross stabilizes."""
    gross_estimate = basic
    resolved: list[tuple[PayrollItem, Decimal, bool]] = []

    for _ in range(10):
        pass_resolved: list[tuple[PayrollItem, Decimal, bool]] = []
        running_allowances = ZERO
        running_deductions = ZERO

        for item in items:
            kind = _item_catalog_kind(item)
            ignore_brackets = (
                kind != PayrollItemType.ItemType.DEDUCTION
                and not _item_is_taxable_addition(item)
            )
            amount, matched = _resolve_item_amount(
                item,
                basic=basic,
                gross=_quantize(gross_estimate + overtime_pay),
                allowances=running_allowances,
                deductions=running_deductions,
                ignore_brackets=ignore_brackets,
                periods_per_year=periods_per_year,
                annual_salary=annual_salary,
            )
            pass_resolved.append((item, amount, matched))
            amt = _quantize(amount)
            if kind == PayrollItemType.ItemType.DEDUCTION:
                running_deductions += amt
            elif _item_is_taxable_addition(item):
                running_allowances += amt

        summarized = _summarize_payroll_items(pass_resolved)
        new_gross = _quantize(basic + summarized["allowances"] + overtime_pay)
        resolved = pass_resolved
        if new_gross == gross_estimate:
            break
        gross_estimate = new_gross

    return _summarize_payroll_items(resolved)


def preview_employee_payroll_items(
    employee,
    *,
    on_date: date | None = None,
    basic_override: Decimal | None = None,
) -> dict:
    """Preview resolved payroll item amounts for an employee (no payslip persisted)."""
    on_date = on_date or date.today()
    basic = _quantize(
        basic_override
        if basic_override is not None
        else (employee.basic_salary or 0)
    )
    items = [
        item
        for item in employee.payroll_items.select_related(
            "item_type_ref",
            "item_type_ref__payslip_column_group",
        ).prefetch_related(
            "item_type_ref__amount_rules",
        )
        if item.applies_on(on_date)
    ]
    periods_per_year = periods_per_year_for_schedule(getattr(employee, "pay_schedule", None))
    if basic_override is not None:
        annual_salary = annual_salary_from_period_basic(basic, periods_per_year=periods_per_year)
    else:
        annual_salary = Decimal(getattr(employee, "annual_salary", 0) or 0)
    summarized = _resolve_payroll_items_for_employee(
        items,
        basic=basic,
        periods_per_year=periods_per_year,
        annual_salary=annual_salary,
    )
    lines: list[dict] = []
    for bucket in ("allowances", "adjustments", "deductions"):
        for line in summarized["breakdown"].get(bucket, []):
            lines.append(
                {
                    **line,
                    "bucket": bucket,
                }
            )
    return {
        "basic_salary": str(basic),
        "annual_salary": str(annual_salary),
        "periods_per_year": str(periods_per_year),
        "allowances_total": str(summarized["allowances"]),
        "adjustments_total": str(summarized["adjustments"]),
        "deductions_total": str(summarized["deductions"]),
        "lines": lines,
    }


def sync_payroll_item_type_to_employees(
    *,
    item_type: PayrollItemType,
    scope: str,
    employee_ids: list[str] | None = None,
    department_id: str | None = None,
    position_id: str | None = None,
) -> dict:
    """
    Create per-employee PayrollItem rows for a catalog item type when missing.
    Does not remove or overwrite existing assignments.
    """
    from hr.models import Employee

    normalized_scope = (scope or "all").strip().lower()
    if normalized_scope not in {"all", "selected", "department", "position"}:
        raise ValueError("Invalid sync scope. Use all, selected, department, or position.")

    employees = Employee.objects.filter(
        employment_status=Employee.EmploymentStatus.ACTIVE,
    ).select_related("department", "position")
    if normalized_scope == "selected":
        identifiers = [str(v).strip() for v in (employee_ids or []) if str(v).strip()]
        if not identifiers:
            raise ValueError("Provide at least one employee id or id_number for selected scope.")
        employees = employees.filter(
            Q(id__in=identifiers) | Q(id_number__in=identifiers)
        )
    elif normalized_scope == "department":
        if not department_id:
            raise ValueError("department_id is required for department scope.")
        employees = employees.filter(department_id=department_id)
    elif normalized_scope == "position":
        if not position_id:
            raise ValueError("position_id is required for position scope.")
        employees = employees.filter(position_id=position_id)

    employees = employees.order_by("id_number", "id")
    employee_list = list(employees)
    if not employee_list:
        return {
            "scope": normalized_scope,
            "item_type_id": str(item_type.id),
            "item_type_name": item_type.name,
            "matched_employees": 0,
            "created": 0,
            "already_assigned": 0,
        }

    existing_employee_ids = set(
        PayrollItem.objects.filter(
            item_type_ref_id=item_type.id,
            employee_id__in=[e.id for e in employee_list],
        ).values_list("employee_id", flat=True)
    )

    to_create: list[PayrollItem] = []
    for employee in employee_list:
        if employee.id in existing_employee_ids:
            continue
        to_create.append(
            PayrollItem(
                employee=employee,
                item_type_ref=item_type,
                name=item_type.name,
                item_type=item_type.item_type,
                is_active=True,
            )
        )

    if to_create:
        PayrollItem.objects.bulk_create(to_create)

    return {
        "scope": normalized_scope,
        "item_type_id": str(item_type.id),
        "item_type_name": item_type.name,
        "matched_employees": len(employee_list),
        "created": len(to_create),
        "already_assigned": len(employee_list) - len(to_create),
    }


def _build_payslip_payload(
    employee,
    run: PayrollRun,
    *,
    apply_column_layout: bool = False,
) -> dict:
    """Compute a fresh payslip payload for ``employee`` against ``run``."""
    period = run.period
    schedule = period.schedule
    on_date = period.end_date

    basic = _quantize(employee.basic_salary or 0)
    periods_per_year = periods_per_year_for_schedule(schedule)
    annual_salary = Decimal(getattr(employee, "annual_salary", 0) or 0)

    items = [
        item
        for item in employee.payroll_items.select_related(
            "item_type_ref",
            "item_type_ref__payslip_column_group",
        ).prefetch_related(
            "item_type_ref__amount_rules",
        )
        if item.applies_on(on_date)
    ]

    overtime_hours = ZERO  # editable in DRAFT
    overtime_pay = _quantize(
        Decimal(employee.hourly_rate or 0) * overtime_hours * Decimal(schedule.overtime_multiplier or 0)
    )

    summarized = _resolve_payroll_items_for_employee(
        items,
        basic=basic,
        overtime_pay=overtime_pay,
        periods_per_year=periods_per_year,
        annual_salary=annual_salary,
    )
    allowance_total = summarized["allowances"]
    adjustment_total = summarized["adjustments"]
    deduction_total = summarized["deductions"]

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
        periods_per_year=periods_per_year,
        annual_salary=annual_salary,
    )

    net = _quantize(gross - tax - deduction_total + adjustment_total)

    breakdown = {
        **summarized["breakdown"],
        "tax": tax_breakdown,
    }
    if apply_column_layout:
        _apply_payslip_column_layout_from_item_types(breakdown)

    return {
        "currency": schedule.currency,
        "basic_salary": basic,
        "overtime_hours": overtime_hours,
        "overtime_pay": overtime_pay,
        "unpaid_leave_days": ZERO,
        "allowances": allowance_total,
        "adjustments": adjustment_total,
        "deductions": deduction_total,
        "tax": tax,
        "gross_pay": gross,
        "net_pay": net,
        "breakdown": breakdown,
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
        .prefetch_related(
            "payroll_items__item_type_ref__amount_rules",
            "payroll_items__item_type_ref__payslip_column_group",
            "tax_rules__amount_rules",
        )
    )

    payslips: list[Payslip] = []
    for employee in employees:
        readiness = employee.payroll_readiness()
        if not readiness["ready"]:
            continue
        payload = _build_payslip_payload(employee, run, apply_column_layout=True)
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

    payload = _build_payslip_payload(payslip.employee, payslip.payroll_run, apply_column_layout=False)
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
    annual_salary = Decimal(getattr(employee, "annual_salary", 0) or 0)

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
        periods_per_year=periods_per_year_for_schedule(schedule),
        annual_salary=annual_salary,
    )
    net = _quantize(gross - tax - payload["deductions"] + payload["adjustments"])

    payslip.basic_salary = basic
    payslip.overtime_hours = overtime_hours
    payslip.overtime_pay = overtime_pay
    payslip.unpaid_leave_days = unpaid_leave_days
    payslip.allowances = payload["allowances"]
    payslip.adjustments = payload["adjustments"]
    payslip.deductions = payload["deductions"]
    payslip.tax = tax
    payslip.gross_pay = gross
    payslip.net_pay = net
    new_breakdown = {
        **payload["breakdown"],
        "tax": tax_breakdown,
    }
    _preserve_breakdown_column_layout(new_breakdown, payslip.breakdown)
    payslip.breakdown = new_breakdown
    payslip.save()
    return payslip


# ---------------------------------------------------------------------------
# Status transitions
# ---------------------------------------------------------------------------


def validate_payroll_settings_configured() -> None:
    """Ensure payroll accounting settings are configured before workflow actions."""
    from .models import PayrollSettings

    settings = PayrollSettings.objects.select_related("transaction_type").first()
    if settings is None or settings.transaction_type_id is None:
        raise ValueError(
            "Configure a payroll transaction type in Payroll settings before continuing."
        )

    tx_type = settings.transaction_type
    if not tx_type.is_active:
        raise ValueError("The configured payroll transaction type is inactive.")
    if tx_type.transaction_category != "expense":
        raise ValueError("Payroll transaction type must be an expense type.")


def validate_payroll_disbursement_account(run: PayrollRun) -> None:
    """Ensure the run has a funded disbursement account before workflow submission."""
    if not run.bank_account_id:
        raise ValueError("Select a disbursement bank account before submitting this payroll run.")

    bank_account = run.bank_account
    if bank_account.ledger_account_id is None:
        raise ValueError("The disbursement account must be linked to a ledger account.")

    schedule_currency_id = run.period.schedule.currency_id
    if bank_account.currency_id != schedule_currency_id:
        raise ValueError("Bank account currency must match the pay schedule currency.")

    from accounting.services.payroll_posting import aggregate_payroll_run_totals
    from accounting.services.posting import recalculate_bank_account_current_balance

    net = aggregate_payroll_run_totals(run)["net"]
    if net <= 0:
        return

    available_balance = recalculate_bank_account_current_balance(bank_account)
    if net > available_balance:
        raise ValueError(
            f"Insufficient balance in {bank_account.account_name}. "
            f"Available: {available_balance:,.2f}, payroll net pay: {net:,.2f}."
        )


@transaction.atomic
def submit_for_approval(run: PayrollRun) -> PayrollRun:
    if run.status != PayrollRun.Status.DRAFT:
        raise ValueError("Only DRAFT runs can be submitted for approval.")
    if not run.payslips.exists():
        raise ValueError("Cannot submit a run with no payslips.")
    validate_payroll_settings_configured()
    validate_payroll_disbursement_account(run)
    run.status = PayrollRun.Status.PENDING
    run.save(update_fields=["status", "updated_at", "updated_by"])
    return run


@transaction.atomic
def approve_run(run: PayrollRun) -> PayrollRun:
    if run.status not in (PayrollRun.Status.DRAFT, PayrollRun.Status.PENDING):
        raise ValueError("Only DRAFT or PENDING runs can be approved.")
    validate_payroll_settings_configured()
    validate_payroll_disbursement_account(run)
    run.status = PayrollRun.Status.APPROVED
    run.approved_at = timezone.now()
    run.save(update_fields=["status", "approved_at", "updated_at", "updated_by"])
    return run


@transaction.atomic
def mark_paid(
    run: PayrollRun,
    *,
    bank_account=None,
    actor=None,
) -> PayrollRun:
    if run.status != PayrollRun.Status.APPROVED:
        raise ValueError("Only APPROVED runs can be marked as paid.")

    validate_payroll_settings_configured()

    if bank_account is not None:
        run.bank_account = bank_account
        run.save(update_fields=["bank_account", "updated_at", "updated_by"])

    if run.bank_account_id is None:
        raise ValueError("Select a bank account before marking this run paid.")

    from accounting.services.payroll_posting import post_payroll_run_to_ledger
    from django.core.exceptions import ValidationError as DjangoValidationError

    try:
        post_payroll_run_to_ledger(run, actor=actor)
    except DjangoValidationError as exc:
        message = exc.messages[0] if getattr(exc, "messages", None) else str(exc)
        raise ValueError(message) from exc

    run.status = PayrollRun.Status.PAID
    run.paid_at = timezone.now()
    run.period.is_closed = True
    run.period.save(update_fields=["is_closed", "updated_at", "updated_by"])
    run.save(update_fields=["status", "paid_at", "updated_at", "updated_by"])
    return run


@transaction.atomic
def revert_to_draft(run: PayrollRun, *, actor=None) -> PayrollRun:
    """Force a run back to DRAFT regardless of current status.

    Intended for admin-only correction flows. Clears approved_at / paid_at
    and re-opens the related period if it was closed by mark_paid.
    """
    if run.status == PayrollRun.Status.DRAFT:
        return run

    if run.status == PayrollRun.Status.PAID:
        from accounting.services.payroll_posting import reverse_payroll_run_posting

        reverse_payroll_run_posting(run, actor=actor)

    run.status = PayrollRun.Status.DRAFT
    run.approved_at = None
    run.paid_at = None
    run.save(update_fields=["status", "approved_at", "paid_at", "updated_at", "updated_by"])
    if run.period.is_closed:
        run.period.is_closed = False
        run.period.save(update_fields=["is_closed", "updated_at", "updated_by"])
    return run
