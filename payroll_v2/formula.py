"""Shared payroll formula and amount-rule evaluation."""

from __future__ import annotations

import ast
from decimal import Decimal
from types import SimpleNamespace

from payroll_v2.enums import CalculationType
from payroll_v2.schedule_services import annual_salary_from_period_basic

ZERO = Decimal("0.00")

_CALC_FLAT = CalculationType.FLAT
_CALC_PERCENTAGE = CalculationType.PERCENTAGE
_CALC_FORMULA = CalculationType.FORMULA


class TargetSalaryBy:
    PER_PERIOD = "per_period"
    ANNUAL = "annual"


class ItemAppliesTo:
    GROSS = "gross"
    BASIC = "basic"
    TAXABLE_GROSS = "taxable_gross"
    ANNUAL = "annual"


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
    annual_salary: Decimal | str | int | float | None = None,
) -> dict:
    pp = Decimal(str(periods_per_year or 12))
    ctx = build_amount_rule_context(
        gross=gross,
        basic=basic,
        allowances=allowances,
        deductions=deductions,
        periods_per_year=pp,
        annual_salary=Decimal(str(annual_salary)) if annual_salary is not None else None,
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


