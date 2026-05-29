"""Advanced financial reports and custom report builder metadata."""

from __future__ import annotations

from rest_framework.response import Response
from rest_framework.views import APIView

from academics.models import AcademicYear
from accounting.services.post_all import apply_cash_transaction_list_filters

from ..access_policies import ReportsAccessPolicy
from ..accounting_totals import (
    approved_cash_queryset,
    expense_breakdown_by_type,
    filter_cash_by_period,
    income_breakdown_by_type,
    sum_expense_total,
    sum_income_revenue,
)
from ..revenue_report import (
    REVENUE_METRICS,
    build_revenue_overview_payload,
    build_revenue_year_payload,
)
from ..utils.export_helpers import export_tabular_report, get_export_format, parse_date_param, resolve_academic_year


class ProfitLossReportView(APIView):
    permission_classes = [ReportsAccessPolicy]

    def get(self, request):
        start_date = parse_date_param(request.query_params.get("start_date"))
        end_date = parse_date_param(request.query_params.get("end_date"))

        txns = approved_cash_queryset()
        txns = apply_cash_transaction_list_filters(txns, request.query_params)
        txns = filter_cash_by_period(txns, start_date, end_date)

        income_total = float(sum_income_revenue(txns))
        expense_total = float(sum_expense_total(txns))
        net = round(income_total - expense_total, 2)

        income_breakdown = income_breakdown_by_type(txns)
        expense_breakdown = expense_breakdown_by_type(txns)
        breakdown = [
            {
                "transaction_type": row["transaction_type"],
                "category": "income",
                "total": row["total"],
                "transaction_count": row["transaction_count"],
            }
            for row in income_breakdown
        ] + [
            {
                "transaction_type": row["transaction_type"],
                "category": "expense",
                "total": row["total"],
                "transaction_count": row["transaction_count"],
            }
            for row in expense_breakdown
        ]

        payload = {
            "start_date": start_date.isoformat() if start_date else None,
            "end_date": end_date.isoformat() if end_date else None,
            "summary": {
                "income_total": income_total,
                "expense_total": expense_total,
                "net_income": net,
            },
            "breakdown": breakdown,
        }

        if get_export_format(request):
            rows = [[b["category"], b["transaction_type"], b["total"]] for b in breakdown]
            rows.append(["", "Net Income", payload["summary"]["net_income"]])
            export_response = export_tabular_report(
                request,
                filename_base="profit-loss-summary",
                title="Profit & Loss Summary",
                subtitle=f"{payload['start_date'] or 'Beginning'} to {payload['end_date'] or 'Today'}",
                summary_rows=[
                    ("Income", payload["summary"]["income_total"]),
                    ("Expense", payload["summary"]["expense_total"]),
                    ("Net Income", payload["summary"]["net_income"]),
                ],
                headers=["Category", "Transaction Type", "Total"],
                rows=rows,
            )
            if export_response:
                return export_response
        return Response(payload)


class RevenueReportView(APIView):
    permission_classes = [ReportsAccessPolicy]

    def get(self, request):
        view = (request.query_params.get("view") or "overview").strip().lower()

        if view == "overview":
            payload = build_revenue_overview_payload(AcademicYear.objects.all())
            if get_export_format(request):
                headers = ["Academic Year", *[metric["label"] for metric in REVENUE_METRICS]]
                rows = [
                    [
                        row["academic_year_label"],
                        *[row["metrics"][metric["key"]]["value"] for metric in REVENUE_METRICS],
                    ]
                    for row in payload["rows"]
                ]
                export_response = export_tabular_report(
                    request,
                    filename_base="revenue-report-overview",
                    title="Revenue Report — Overview",
                    subtitle="All academic years",
                    summary_rows=None,
                    headers=headers,
                    rows=rows,
                )
                if export_response:
                    return export_response
            return Response(payload)

        academic_year, error = resolve_academic_year(request)
        if error:
            return error

        start_date = parse_date_param(request.query_params.get("start_date"))
        end_date = parse_date_param(request.query_params.get("end_date"))
        payload = build_revenue_year_payload(academic_year, start_date, end_date)

        if get_export_format(request):
            rows = [[r["metric"], r["amount"]] for r in payload["results"]]
            export_response = export_tabular_report(
                request,
                filename_base=f"revenue-report-{academic_year.id}",
                title="Revenue Report",
                subtitle=(
                    f"Academic Year: {payload['academic_year_label']} · "
                    f"{payload['summary']['period_start'] or 'Start'} to "
                    f"{payload['summary']['period_end'] or 'End'}"
                ),
                summary_rows=None,
                headers=["Metric", "Amount"],
                rows=rows,
            )
            if export_response:
                return export_response
        return Response(payload)


class CustomReportBuilderView(APIView):
    """Metadata endpoint for future custom report builder UI."""

    permission_classes = [ReportsAccessPolicy]

    def get(self, request):
        return Response(
            {
                "available_reports": [
                    {"slug": "payment-summary", "endpoint": "reports/finance/", "filters": ["academic_year_id", "grade_level_id", "section_id", "payment_status"]},
                    {"slug": "ar-aging", "endpoint": "reports/finance/ar-aging/", "filters": ["academic_year_id", "grade_level_id", "section_id"]},
                    {"slug": "income-expense-summary", "endpoint": "reports/accounting-summary/", "filters": ["start_date", "end_date", "group_by", "status", "category"]},
                    {"slug": "trial-balance", "endpoint": "reports/accounting/trial-balance/", "filters": ["start_date", "end_date"]},
                    {"slug": "attendance-summary", "endpoint": "reports/attendance/summary/", "filters": ["academic_year_id", "start_date", "end_date"]},
                ],
                "export_formats": ["json", "xlsx"],
                "scheduled_delivery": False,
            }
        )
