"""Banking and cash account reports."""

from __future__ import annotations

from rest_framework.response import Response
from rest_framework.views import APIView

from accounting.models import AccountingBankAccount, AccountingCashTransaction
from accounting.services.post_all import apply_cash_transaction_list_filters
from accounting.services.posting import (
    compute_bank_account_native_balance,
    recalculate_bank_account_current_balance,
)

from ..access_policies import ReportsAccessPolicy
from ..accounting_totals import (
    approved_cash_for_bank_account,
    compute_bank_account_cash_on_hand,
    sum_approved_cash_net_native,
    sum_inflow_amount,
    sum_outflow_amount,
)
from ..utils.export_helpers import export_tabular_report, get_export_format, parse_date_param


class BankBalanceSummaryReportView(APIView):
    permission_classes = [ReportsAccessPolicy]

    def get(self, request):
        accounts = AccountingBankAccount.objects.filter(
            status=AccountingBankAccount.AccountStatus.ACTIVE
        ).select_related("currency").order_by("account_name")

        results = []
        for account in accounts:
            recalculate_bank_account_current_balance(account)
            opening = float(account.opening_balance or 0)
            transaction_net = float(compute_bank_account_native_balance(account))
            cash_on_hand = float(compute_bank_account_cash_on_hand(account))

            results.append(
                {
                    "account_id": str(account.id),
                    "account_name": account.account_name,
                    "bank_name": account.bank_name,
                    "account_number": account.account_number,
                    "account_type": account.account_type,
                    "opening_balance": opening,
                    "transaction_net": transaction_net,
                    "cash_on_hand": cash_on_hand,
                    "current_balance": cash_on_hand,
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
                    r["transaction_net"],
                    r["cash_on_hand"],
                    r["currency"],
                ]
                for r in results
            ]
            export_response = export_tabular_report(
                request,
                filename_base="bank-balance-summary",
                title="Bank Balance Summary",
                subtitle="Opening balance plus approved cash activity (native currency per account).",
                summary_rows=None,
                headers=[
                    "Account",
                    "Bank",
                    "Account No.",
                    "Type",
                    "Opening",
                    "Activity Net",
                    "Cash on Hand",
                    "Currency",
                ],
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

        accounts = AccountingBankAccount.objects.filter(
            status=AccountingBankAccount.AccountStatus.ACTIVE
        ).select_related("currency")
        if bank_account_id:
            accounts = accounts.filter(id=bank_account_id)

        results = []
        for account in accounts:
            period_txns = AccountingCashTransaction.objects.filter(
                bank_account=account,
                status=AccountingCashTransaction.TransactionStatus.APPROVED,
            )
            period_txns = apply_cash_transaction_list_filters(period_txns, request.query_params)
            if start_date:
                period_txns = period_txns.filter(transaction_date__gte=start_date)
            if end_date:
                period_txns = period_txns.filter(transaction_date__lte=end_date)
            if account.currency_id:
                period_txns = period_txns.filter(currency_id=account.currency_id)

            income_total = float(sum_inflow_amount(period_txns, use_base=False))
            expense_total = float(sum_outflow_amount(period_txns, use_base=False))
            period_net = float(sum_approved_cash_net_native(period_txns))
            transfer_net = round(period_net - (income_total - expense_total), 2)

            opening = float(account.opening_balance or 0)
            cash_on_hand = float(compute_bank_account_cash_on_hand(account, end_date=end_date))

            results.append(
                {
                    "account_name": account.account_name,
                    "bank_name": account.bank_name,
                    "account_number": account.account_number,
                    "opening_balance": opening,
                    "income_total": income_total,
                    "expense_total": expense_total,
                    "transfer_total": transfer_net,
                    "period_net_cash": round(period_net, 2),
                    "currency": account.currency.code if account.currency else "",
                    "cash_on_hand": cash_on_hand,
                    "computed_balance": cash_on_hand,
                    "recorded_balance": cash_on_hand,
                    "variance": 0,
                    "transaction_count": period_txns.count(),
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
                    r["period_net_cash"],
                    r["cash_on_hand"],
                    r["transaction_count"],
                ]
                for r in results
            ]
            export_response = export_tabular_report(
                request,
                filename_base="bank-reconciliation",
                title="Bank Reconciliation Report",
                subtitle="Approved cash activity in account currency; cash on hand = opening + cumulative net.",
                summary_rows=None,
                headers=[
                    "Account",
                    "Bank",
                    "Opening",
                    "Income",
                    "Expense",
                    "Transfers",
                    "Period Net",
                    "Cash on Hand",
                    "Transactions",
                ],
                rows=rows,
            )
            if export_response:
                return export_response
        return Response(payload)
