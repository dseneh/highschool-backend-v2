"""Banking and cash account reports."""

from __future__ import annotations

from django.db.models import Q, Sum
from django.db.models.functions import Coalesce
from decimal import Decimal

from rest_framework.response import Response
from rest_framework.views import APIView

from accounting.models import AccountingBankAccount, AccountingCashTransaction
from accounting.services.post_all import apply_cash_transaction_list_filters

from ..access_policies import ReportsAccessPolicy
from ..utils.export_helpers import export_tabular_report, get_export_format, parse_date_param


class BankBalanceSummaryReportView(APIView):
    permission_classes = [ReportsAccessPolicy]

    def get(self, request):
        accounts = AccountingBankAccount.objects.filter(status=AccountingBankAccount.AccountStatus.ACTIVE).order_by("account_name")
        results = []
        for account in accounts:
            results.append(
                {
                    "account_id": str(account.id),
                    "account_name": account.account_name,
                    "bank_name": account.bank_name,
                    "account_number": account.account_number,
                    "account_type": account.account_type,
                    "opening_balance": float(account.opening_balance or 0),
                    "current_balance": float(account.current_balance or 0),
                    "currency": account.currency.code if account.currency else "",
                }
            )

        payload = {"results": results}
        if get_export_format(request):
            rows = [
                [
                    r["account_name"],
                    r["bank_name"],
                    r["account_number"],
                    r["account_type"],
                    r["opening_balance"],
                    r["current_balance"],
                    r["currency"],
                ]
                for r in results
            ]
            export_response = export_tabular_report(
                request,
                filename_base="bank-balance-summary",
                title="Bank Balance Summary",
                subtitle=None,
                summary_rows=None,
                headers=["Account", "Bank", "Account No.", "Type", "Opening", "Current", "Currency"],
                rows=rows,
            )
            if export_response:
                return export_response
        return Response(payload)


class BankReconciliationReportView(APIView):
    permission_classes = [ReportsAccessPolicy]

    def get(self, request):
        start_date = parse_date_param(request.query_params.get("start_date"))
        end_date = parse_date_param(request.query_params.get("end_date"))
        bank_account_id = request.query_params.get("bank_account_id")

        accounts = AccountingBankAccount.objects.filter(status=AccountingBankAccount.AccountStatus.ACTIVE)
        if bank_account_id:
            accounts = accounts.filter(id=bank_account_id)

        results = []
        for account in accounts:
            txns = AccountingCashTransaction.objects.filter(
                bank_account=account,
                status="approved",
            )
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
            transfer_in = (
                txns.filter(transaction_type__transaction_category="transfer").aggregate(
                    total=Coalesce(Sum("amount"), Decimal("0"))
                )["total"]
                or 0
            )

            opening = float(account.opening_balance or 0)
            computed = round(opening + float(income_total) + float(transfer_in) - float(expense_total), 2)
            current = float(account.current_balance or 0)

            results.append(
                {
                    "account_name": account.account_name,
                    "bank_name": account.bank_name,
                    "account_number": account.account_number,
                    "opening_balance": opening,
                    "income_total": float(income_total),
                    "expense_total": float(expense_total),
                    "transfer_total": float(transfer_in),
                    "computed_balance": computed,
                    "recorded_balance": current,
                    "variance": round(current - computed, 2),
                    "transaction_count": txns.count(),
                }
            )

        payload = {"results": results}
        if get_export_format(request):
            rows = [
                [
                    r["account_name"],
                    r["bank_name"],
                    r["opening_balance"],
                    r["income_total"],
                    r["expense_total"],
                    r["transfer_total"],
                    r["computed_balance"],
                    r["recorded_balance"],
                    r["variance"],
                    r["transaction_count"],
                ]
                for r in results
            ]
            export_response = export_tabular_report(
                request,
                filename_base="bank-reconciliation",
                title="Bank Reconciliation Report",
                subtitle=None,
                summary_rows=None,
                headers=[
                    "Account",
                    "Bank",
                    "Opening",
                    "Income",
                    "Expense",
                    "Transfers",
                    "Computed",
                    "Recorded",
                    "Variance",
                    "Transactions",
                ],
                rows=rows,
            )
            if export_response:
                return export_response
        return Response(payload)
