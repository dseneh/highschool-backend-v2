"""Advanced financial reports and custom report builder metadata."""

from __future__ import annotations

from decimal import Decimal

from django.db.models import Sum
from django.db.models.functions import Coalesce
from rest_framework.response import Response
from rest_framework.views import APIView

from accounting.models import AccountingCashTransaction, AccountingStudentBill
from accounting.services.post_all import apply_cash_transaction_list_filters

from ..access_policies import ReportsAccessPolicy
from ..utils.export_helpers import export_tabular_report, get_export_format, parse_date_param, resolve_academic_year

LEDGER_INCOME = {"income"}
LEDGER_EXPENSE = {"expense"}


class ProfitLossReportView(APIView):
    permission_classes = [ReportsAccessPolicy]

    def get(self, request):
        start_date = parse_date_param(request.query_params.get("start_date"))
        end_date = parse_date_param(request.query_params.get("end_date"))

        txns = AccountingCashTransaction.objects.filter(status="approved").select_related("transaction_type")
        txns = apply_cash_transaction_list_filters(txns, request.query_params)
        if start_date:
            txns = txns.filter(transaction_date__gte=start_date)
        if end_date:
            txns = txns.filter(transaction_date__lte=end_date)

        income_total = (
            txns.filter(transaction_type__transaction_category="income").aggregate(
                total=Coalesce(Sum("amount"), Decimal("0"))
            )["total"]
            or 0
        )
        expense_total = (
            txns.filter(transaction_type__transaction_category="expense").aggregate(
                total=Coalesce(Sum("amount"), Decimal("0"))
            )["total"]
            or 0
        )
        net = float(income_total) - float(expense_total)

        by_type = (
            txns.filter(transaction_type__transaction_category__in=["income", "expense"])
            .values("transaction_type__name", "transaction_type__transaction_category")
            .annotate(total=Coalesce(Sum("amount"), Decimal("0")))
            .order_by("transaction_type__transaction_category", "transaction_type__name")
        )
        breakdown = [
            {
                "transaction_type": row["transaction_type__name"] or "Unknown",
                "category": row["transaction_type__transaction_category"],
                "total": float(row["total"] or 0),
            }
            for row in by_type
        ]

        payload = {
            "start_date": start_date.isoformat() if start_date else None,
            "end_date": end_date.isoformat() if end_date else None,
            "summary": {
                "income_total": float(income_total),
                "expense_total": float(expense_total),
                "net_income": round(net, 2),
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
        academic_year, error = resolve_academic_year(request)
        if error:
            return error

        start_date = parse_date_param(request.query_params.get("start_date"))
        end_date = parse_date_param(request.query_params.get("end_date"))

        bills = AccountingStudentBill.objects.filter(academic_year=academic_year).exclude(
            status=AccountingStudentBill.BillStatus.CANCELLED
        )
        billed_total = bills.aggregate(total=Coalesce(Sum("net_amount"), Decimal("0")))["total"] or 0
        collected_total = bills.aggregate(total=Coalesce(Sum("paid_amount"), Decimal("0")))["total"] or 0
        outstanding_total = bills.aggregate(total=Coalesce(Sum("outstanding_amount"), Decimal("0")))["total"] or 0

        cash_income = AccountingCashTransaction.objects.filter(
            status="approved",
            transaction_type__transaction_category="income",
        )
        if start_date:
            cash_income = cash_income.filter(transaction_date__gte=start_date)
        if end_date:
            cash_income = cash_income.filter(transaction_date__lte=end_date)
        other_income = cash_income.aggregate(total=Coalesce(Sum("amount"), Decimal("0")))["total"] or 0

        summary = {
            "total_billed": float(billed_total),
            "total_collected_on_bills": float(collected_total),
            "outstanding_on_bills": float(outstanding_total),
            "other_income": float(other_income),
            "total_revenue": round(float(collected_total) + float(other_income), 2),
        }
        results = [
            {"metric": "Billed (Net)", "amount": summary["total_billed"]},
            {"metric": "Collected on Bills", "amount": summary["total_collected_on_bills"]},
            {"metric": "Outstanding on Bills", "amount": summary["outstanding_on_bills"]},
            {"metric": "Other Income", "amount": summary["other_income"]},
            {"metric": "Total Revenue", "amount": summary["total_revenue"]},
        ]
        payload = {
            "academic_year_id": str(academic_year.id),
            "summary": summary,
            "results": results,
        }

        if get_export_format(request):
            rows = [[r["metric"], r["amount"]] for r in results]
            export_response = export_tabular_report(
                request,
                filename_base=f"revenue-report-{academic_year.id}",
                title="Revenue Report",
                subtitle=f"Academic Year: {academic_year}",
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
