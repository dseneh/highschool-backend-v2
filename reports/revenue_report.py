"""Revenue report helpers — aligned with accounting cash totals."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.db.models import Sum
from django.db.models.functions import Coalesce

from accounting.models import AccountingStudentBill
from accounting.services.currency_totals import (
    get_tenant_base_currency,
    serialize_currency,
    sum_cash_metric_by_currency,
)
from reports.accounting_totals import (
    approved_cash_queryset,
    filter_cash_by_period,
    income_breakdown_by_type,
    split_tuition_and_other_income,
    sum_approved_cash_net,
    sum_expense_total,
)

REVENUE_METRICS: list[dict[str, str]] = [
    {"key": "total_billed", "label": "Billed (Net)", "section": "receivables"},
    {"key": "total_collected_on_bills", "label": "Collected on Bills", "section": "receivables"},
    {"key": "outstanding_on_bills", "label": "Outstanding on Bills", "section": "receivables"},
    {"key": "tuition_income", "label": "Tuition Income (Cash)", "section": "revenue"},
    {"key": "other_income", "label": "Other Income (Cash)", "section": "revenue"},
    {"key": "total_revenue", "label": "Total Revenue", "section": "revenue"},
    {"key": "total_expense", "label": "Total Expense (Cash)", "section": "cash"},
    {"key": "net_cash_movement", "label": "Net Cash Movement (Period)", "section": "cash"},
    {
        "key": "cash_on_hand",
        "label": "Cash Balance (Approved)",
        "section": "cash",
    },
]

CHART_METRIC_KEYS = ("total_revenue", "tuition_income", "total_collected_on_bills")


def academic_year_label(academic_year) -> str:
    if academic_year.name:
        return str(academic_year.name)
    if academic_year.start_date and academic_year.end_date:
        return f"{academic_year.start_date.year}/{academic_year.end_date.year}"
    return str(academic_year.id)


def compute_revenue_summary_for_year(academic_year, start_date=None, end_date=None) -> dict[str, float]:
    period_start = start_date or academic_year.start_date
    period_end = end_date or academic_year.end_date

    bills = AccountingStudentBill.objects.filter(academic_year=academic_year).exclude(
        status=AccountingStudentBill.BillStatus.CANCELLED
    )
    billed_total = bills.aggregate(total=Coalesce(Sum("net_amount"), Decimal("0")))["total"] or 0
    collected_on_bills = bills.aggregate(total=Coalesce(Sum("paid_amount"), Decimal("0")))["total"] or 0
    outstanding_on_bills = bills.aggregate(total=Coalesce(Sum("outstanding_amount"), Decimal("0")))["total"] or 0

    cash_qs = filter_cash_by_period(approved_cash_queryset(), period_start, period_end)
    tuition_income, other_income, total_revenue = split_tuition_and_other_income(cash_qs)
    total_expense = sum_expense_total(cash_qs)
    net_cash_movement = sum_approved_cash_net(cash_qs)
    cash_on_hand_qs = filter_cash_by_period(approved_cash_queryset(), None, period_end)
    cash_on_hand = sum_approved_cash_net(cash_on_hand_qs)
    cash_on_hand_by_currency = [
        {
            "currency_code": row["currency_code"],
            "currency_symbol": row["currency_symbol"],
            "balance": str(row["net_all_flows"]),
        }
        for row in sum_cash_metric_by_currency(cash_on_hand_qs, use_base=False)
    ]
    base_currency = serialize_currency(get_tenant_base_currency())
    currency_breakdown = sum_cash_metric_by_currency(cash_qs, use_base=False)
    currency_breakdown_base = sum_cash_metric_by_currency(cash_qs, use_base=True)

    return {
        "period_start": period_start.isoformat() if period_start else None,
        "period_end": period_end.isoformat() if period_end else None,
        "base_currency": base_currency,
        "total_billed": float(billed_total),
        "total_collected_on_bills": float(collected_on_bills),
        "outstanding_on_bills": float(outstanding_on_bills),
        "tuition_income": float(tuition_income),
        "other_income": float(other_income),
        "total_revenue": float(total_revenue),
        "total_expense": float(total_expense),
        "net_cash_movement": float(net_cash_movement),
        "cash_on_hand": float(cash_on_hand),
        "currency_breakdown": currency_breakdown,
        "currency_breakdown_base": currency_breakdown_base,
        "cash_on_hand_by_currency": cash_on_hand_by_currency,
    }


def compute_metric_trend(current: float, previous: float | None) -> dict[str, Any] | None:
    if previous is None:
        return None

    if previous == 0:
        if current == 0:
            return {"pct": 0.0, "direction": "neutral", "previous": 0.0}
        return {
            "pct": 100.0,
            "direction": "up" if current > 0 else "neutral",
            "previous": 0.0,
        }

    pct_change = ((current - previous) / abs(previous)) * 100
    if abs(pct_change) < 0.05:
        direction = "neutral"
    elif pct_change > 0:
        direction = "up"
    else:
        direction = "down"

    return {
        "pct": round(abs(pct_change), 1),
        "direction": direction,
        "previous": round(previous, 2),
    }


def attach_metric_trends(
    current: dict[str, float],
    previous: dict[str, float] | None,
) -> dict[str, dict[str, Any]]:
    metrics: dict[str, dict[str, Any]] = {}
    for metric in REVENUE_METRICS:
        key = metric["key"]
        value = float(current.get(key, 0))
        prev_value = None if previous is None else float(previous.get(key, 0))
        metrics[key] = {
            "value": value,
            "trend": compute_metric_trend(value, prev_value),
        }
    return metrics


def build_revenue_overview_payload(academic_years) -> dict[str, Any]:
    ordered_years = list(academic_years.order_by("start_date"))
    rows: list[dict[str, Any]] = []
    previous_summary: dict[str, float] | None = None

    for academic_year in ordered_years:
        summary = compute_revenue_summary_for_year(academic_year)
        rows.append(
            {
                "academic_year_id": str(academic_year.id),
                "academic_year_label": academic_year_label(academic_year),
                "period_start": summary["period_start"],
                "period_end": summary["period_end"],
                "metrics": attach_metric_trends(summary, previous_summary),
            }
        )
        previous_summary = summary

    chart_categories = [row["academic_year_label"] for row in rows]
    chart_series = [
        {
            "key": metric["key"],
            "name": metric["label"],
            "data": [row["metrics"][metric["key"]]["value"] for row in rows],
        }
        for metric in REVENUE_METRICS
        if metric["key"] in CHART_METRIC_KEYS
    ]

    return {
        "view": "overview",
        "metrics": REVENUE_METRICS,
        "base_currency": serialize_currency(get_tenant_base_currency()),
        "rows": list(reversed(rows)),
        "chart": {
            "categories": chart_categories,
            "series": chart_series,
        },
    }


def build_revenue_year_payload(academic_year, start_date=None, end_date=None) -> dict[str, Any]:
    from academics.models import AcademicYear

    period_start = start_date or academic_year.start_date
    period_end = end_date or academic_year.end_date

    summary = compute_revenue_summary_for_year(academic_year, start_date, end_date)
    prior_year = (
        AcademicYear.objects.filter(start_date__lt=academic_year.start_date)
        .order_by("-start_date")
        .first()
    )
    prior_summary = (
        compute_revenue_summary_for_year(prior_year) if prior_year is not None else None
    )
    metrics_with_trends = attach_metric_trends(summary, prior_summary)

    results = [
        {
            "metric": metric["label"],
            "metric_key": metric["key"],
            "amount": metrics_with_trends[metric["key"]]["value"],
            "trend": metrics_with_trends[metric["key"]]["trend"],
            "section": metric["section"],
        }
        for metric in REVENUE_METRICS
    ]

    type_breakdown = income_breakdown_by_type(
        filter_cash_by_period(
            approved_cash_queryset(),
            period_start,
            period_end,
        )
    )

    return {
        "view": "year",
        "academic_year_id": str(academic_year.id),
        "academic_year_label": academic_year_label(academic_year),
        "prior_academic_year_label": academic_year_label(prior_year) if prior_year else None,
        "base_currency": summary.get("base_currency"),
        "summary": summary,
        "metrics": metrics_with_trends,
        "results": results,
        "breakdown": type_breakdown,
        "currency_breakdown": summary.get("currency_breakdown") or [],
        "currency_breakdown_base": summary.get("currency_breakdown_base") or [],
        "cash_on_hand_by_currency": summary.get("cash_on_hand_by_currency") or [],
    }
