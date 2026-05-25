"""General ledger and accounting close reports."""

from __future__ import annotations

from decimal import Decimal

from django.db.models import Q, Sum
from django.db.models.functions import Coalesce
from rest_framework.response import Response
from rest_framework.views import APIView

from accounting.models import AccountingCashTransaction, AccountingJournalEntry, AccountingJournalLine, AccountingLedgerAccount
from accounting.services.post_all import apply_cash_transaction_list_filters

from ..access_policies import ReportsAccessPolicy
from ..utils.export_helpers import export_tabular_report, get_export_format, parse_date_param


class JournalRegisterReportView(APIView):
    permission_classes = [ReportsAccessPolicy]

    def get(self, request):
        start_date = parse_date_param(request.query_params.get("start_date"))
        end_date = parse_date_param(request.query_params.get("end_date"))
        source = (request.query_params.get("source") or "").strip()
        status_filter = (request.query_params.get("status") or "posted").strip().lower()

        entries = AccountingJournalEntry.objects.select_related("academic_year").prefetch_related(
            "lines__ledger_account"
        )
        if start_date:
            entries = entries.filter(posting_date__gte=start_date)
        if end_date:
            entries = entries.filter(posting_date__lte=end_date)
        if source:
            entries = entries.filter(source=source)
        if status_filter and status_filter != "all":
            entries = entries.filter(status=status_filter)
        entries = entries.order_by("-posting_date", "-created_at")

        results = []
        for entry in entries:
            for line in entry.lines.all():
                results.append(
                    {
                        "reference_number": entry.reference_number,
                        "posting_date": entry.posting_date.isoformat(),
                        "source": entry.source,
                        "status": entry.status,
                        "description": entry.description,
                        "account_code": line.ledger_account.code,
                        "account_name": line.ledger_account.name,
                        "debit": float(line.debit_amount or 0),
                        "credit": float(line.credit_amount or 0),
                    }
                )

        payload = {"results": results, "count": len(results)}
        if get_export_format(request):
            rows = [
                [
                    r["reference_number"],
                    r["posting_date"],
                    r["source"],
                    r["status"],
                    r["account_code"],
                    r["account_name"],
                    r["debit"],
                    r["credit"],
                    r["description"],
                ]
                for r in results
            ]
            export_response = export_tabular_report(
                request,
                filename_base="journal-register",
                title="Journal Entry Register",
                subtitle=f"Status: {status_filter}",
                summary_rows=None,
                headers=["Reference", "Date", "Source", "Status", "Account Code", "Account Name", "Debit", "Credit", "Description"],
                rows=rows,
            )
            if export_response:
                return export_response
        return Response(payload)


class TrialBalanceReportView(APIView):
    permission_classes = [ReportsAccessPolicy]

    def get(self, request):
        start_date = parse_date_param(request.query_params.get("start_date"))
        end_date = parse_date_param(request.query_params.get("end_date"))

        lines = AccountingJournalLine.objects.filter(journal_entry__status=AccountingJournalEntry.EntryStatus.POSTED)
        if start_date:
            lines = lines.filter(journal_entry__posting_date__gte=start_date)
        if end_date:
            lines = lines.filter(journal_entry__posting_date__lte=end_date)

        totals = (
            lines.values("ledger_account_id", "ledger_account__code", "ledger_account__name", "ledger_account__account_type")
            .annotate(
                total_debit=Coalesce(Sum("debit_amount"), Decimal("0")),
                total_credit=Coalesce(Sum("credit_amount"), Decimal("0")),
            )
            .order_by("ledger_account__code")
        )

        results = []
        total_debit = 0.0
        total_credit = 0.0
        for row in totals:
            debit = float(row["total_debit"] or 0)
            credit = float(row["total_credit"] or 0)
            total_debit += debit
            total_credit += credit
            results.append(
                {
                    "account_code": row["ledger_account__code"],
                    "account_name": row["ledger_account__name"],
                    "account_type": row["ledger_account__account_type"],
                    "total_debit": debit,
                    "total_credit": credit,
                    "balance": round(debit - credit, 2),
                }
            )

        payload = {
            "results": results,
            "summary": {
                "total_debit": round(total_debit, 2),
                "total_credit": round(total_credit, 2),
            },
        }

        if get_export_format(request):
            rows = [
                [r["account_code"], r["account_name"], r["account_type"], r["total_debit"], r["total_credit"], r["balance"]]
                for r in results
            ]
            export_response = export_tabular_report(
                request,
                filename_base="trial-balance",
                title="Trial Balance",
                subtitle=None,
                summary_rows=[
                    ("Total Debit", payload["summary"]["total_debit"]),
                    ("Total Credit", payload["summary"]["total_credit"]),
                ],
                headers=["Account Code", "Account Name", "Type", "Debit", "Credit", "Balance"],
                rows=rows,
            )
            if export_response:
                return export_response
        return Response(payload)


class PendingTransactionsReportView(APIView):
    permission_classes = [ReportsAccessPolicy]

    def get(self, request):
        queryset = AccountingCashTransaction.objects.select_related(
            "bank_account",
            "transaction_type",
            "payment_method",
            "student",
        ).filter(status=AccountingCashTransaction.TransactionStatus.PENDING)
        queryset = apply_cash_transaction_list_filters(queryset, request.query_params)
        queryset = queryset.order_by("-transaction_date", "-created_at")

        results = []
        for txn in queryset:
            results.append(
                {
                    "reference_number": txn.reference_number,
                    "transaction_date": txn.transaction_date.isoformat(),
                    "category": txn.transaction_type.transaction_category if txn.transaction_type else "",
                    "transaction_type": txn.transaction_type.name if txn.transaction_type else "",
                    "description": txn.description or "",
                    "bank_account": txn.bank_account.account_name if txn.bank_account else "",
                    "amount": float(txn.amount),
                    "status": txn.status,
                    "student_id": txn.student.id_number if txn.student else "",
                    "student_name": txn.student.get_full_name() if txn.student else "",
                }
            )

        payload = {"results": results, "count": len(results)}
        if get_export_format(request):
            rows = [
                [
                    r["reference_number"],
                    r["transaction_date"],
                    r["category"],
                    r["transaction_type"],
                    r["bank_account"],
                    r["amount"],
                    r["status"],
                    r["student_id"],
                    r["student_name"],
                    r["description"],
                ]
                for r in results
            ]
            export_response = export_tabular_report(
                request,
                filename_base="pending-transactions",
                title="Pending Transactions Report",
                subtitle=None,
                summary_rows=[("Pending Count", len(results))],
                headers=["Reference", "Date", "Category", "Type", "Bank Account", "Amount", "Status", "Student ID", "Student Name", "Description"],
                rows=rows,
            )
            if export_response:
                return export_response
        return Response(payload)


class ChartOfAccountsReportView(APIView):
    permission_classes = [ReportsAccessPolicy]

    def get(self, request):
        include_inactive = request.query_params.get("include_inactive", "").lower() in {"1", "true", "yes"}
        accounts = AccountingLedgerAccount.objects.all().order_by("code")
        if not include_inactive:
            accounts = accounts.filter(is_active=True)

        results = [
            {
                "code": account.code,
                "name": account.name,
                "account_type": account.account_type,
                "category": account.category,
                "normal_balance": account.normal_balance,
                "is_header": account.is_header,
                "is_active": account.is_active,
            }
            for account in accounts
        ]

        payload = {"results": results, "count": len(results)}
        if get_export_format(request):
            rows = [
                [r["code"], r["name"], r["account_type"], r["category"], r["normal_balance"], "Yes" if r["is_header"] else "No", "Yes" if r["is_active"] else "No"]
                for r in results
            ]
            export_response = export_tabular_report(
                request,
                filename_base="chart-of-accounts",
                title="Chart of Accounts",
                subtitle=None,
                summary_rows=[("Account Count", len(results))],
                headers=["Code", "Name", "Type", "Category", "Normal Balance", "Header", "Active"],
                rows=rows,
            )
            if export_response:
                return export_response
        return Response(payload)
