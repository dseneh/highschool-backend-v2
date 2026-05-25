"""Payroll reports."""

from __future__ import annotations

from decimal import Decimal

from django.db.models import Sum
from django.db.models.functions import Coalesce
from rest_framework.response import Response
from rest_framework.views import APIView

from accounting.models import AccountingPayrollPostingBatch, AccountingPayrollPostingLine
from payroll.models import PayrollRun, Payslip

from ..access_policies import ReportsAccessPolicy
from ..utils.export_helpers import export_tabular_report, get_export_format, parse_date_param


class PayrollRunSummaryReportView(APIView):
    permission_classes = [ReportsAccessPolicy]

    def get(self, request):
        start_date = parse_date_param(request.query_params.get("start_date"))
        end_date = parse_date_param(request.query_params.get("end_date"))

        runs = PayrollRun.objects.select_related("period", "period__schedule").order_by("-created_at")
        if start_date:
            runs = runs.filter(period__start_date__gte=start_date)
        if end_date:
            runs = runs.filter(period__end_date__lte=end_date)

        results = []
        for run in runs:
            payslips = Payslip.objects.filter(payroll_run=run)
            gross = payslips.aggregate(total=Coalesce(Sum("gross_pay"), Decimal("0")))["total"] or 0
            net = payslips.aggregate(total=Coalesce(Sum("net_pay"), Decimal("0")))["total"] or 0
            deductions = payslips.aggregate(total=Coalesce(Sum("deductions"), Decimal("0")))["total"] or 0
            results.append(
                {
                    "run_id": str(run.id),
                    "period_name": run.period.name if run.period else "",
                    "start_date": run.period.start_date.isoformat() if run.period else "",
                    "end_date": run.period.end_date.isoformat() if run.period else "",
                    "status": run.status,
                    "employee_count": payslips.count(),
                    "gross_total": float(gross),
                    "deductions_total": float(deductions),
                    "net_total": float(net),
                }
            )

        payload = {"results": results}
        if get_export_format(request):
            rows = [
                [
                    r["period_name"],
                    r["start_date"],
                    r["end_date"],
                    r["status"],
                    r["employee_count"],
                    r["gross_total"],
                    r["deductions_total"],
                    r["net_total"],
                ]
                for r in results
            ]
            export_response = export_tabular_report(
                request,
                filename_base="payroll-run-summary",
                title="Payroll Run Summary",
                subtitle=None,
                summary_rows=None,
                headers=["Period", "Start", "End", "Status", "Employees", "Gross", "Deductions", "Net"],
                rows=rows,
            )
            if export_response:
                return export_response
        return Response(payload)


class PayrollRegisterReportView(APIView):
    permission_classes = [ReportsAccessPolicy]

    def get(self, request):
        payroll_run_id = request.query_params.get("payroll_run_id")
        payslips = Payslip.objects.select_related("employee", "payroll_run", "payroll_run__period").order_by(
            "employee__last_name",
            "employee__first_name",
        )
        if payroll_run_id:
            payslips = payslips.filter(payroll_run_id=payroll_run_id)

        results = []
        for slip in payslips:
            results.append(
                {
                    "employee_id": slip.employee.employee_number or slip.employee.id_number or str(slip.employee_id),
                    "employee_name": slip.employee.get_full_name(),
                    "period_name": slip.payroll_run.period.name if slip.payroll_run and slip.payroll_run.period else "",
                    "run_status": slip.payroll_run.status if slip.payroll_run else "",
                    "gross_pay": float(slip.gross_pay or 0),
                    "total_deductions": float(slip.deductions or 0),
                    "net_pay": float(slip.net_pay or 0),
                }
            )

        payload = {"results": results}
        if get_export_format(request):
            rows = [
                [
                    r["employee_id"],
                    r["employee_name"],
                    r["period_name"],
                    r["run_status"],
                    r["gross_pay"],
                    r["total_deductions"],
                    r["net_pay"],
                ]
                for r in results
            ]
            export_response = export_tabular_report(
                request,
                filename_base="payroll-register",
                
                title="Payroll Register",
                subtitle=None,
                summary_rows=[("Employee Count", len(results))],
                headers=["Employee ID", "Employee Name", "Period", "Run Status", "Gross", "Deductions", "Net"],
                rows=rows,
            
            )
            if export_response:
                return export_response
        return Response(payload)


class PayrollPostingJournalReportView(APIView):
    permission_classes = [ReportsAccessPolicy]

    def get(self, request):
        batches = AccountingPayrollPostingBatch.objects.select_related(
            "payroll_run",
            "journal_entry",
            "currency",
        ).prefetch_related("lines__staff_member", "lines__debit_account", "lines__credit_account")

        start_date = parse_date_param(request.query_params.get("start_date"))
        end_date = parse_date_param(request.query_params.get("end_date"))
        if start_date:
            batches = batches.filter(posting_date__gte=start_date)
        if end_date:
            batches = batches.filter(posting_date__lte=end_date)

        results = []
        for batch in batches.order_by("-posting_date"):
            for line in batch.lines.all():
                results.append(
                    {
                        "batch_id": str(batch.id),
                        "posting_date": batch.posting_date.isoformat(),
                        "batch_status": batch.batch_status,
                        "journal_reference": batch.journal_entry.reference_number if batch.journal_entry else "",
                        "staff_name": line.staff_member.get_full_name(),
                        "line_type": line.line_type,
                        "debit_account": line.debit_account.code if line.debit_account else "",
                        "credit_account": line.credit_account.code if line.credit_account else "",
                        "debit_amount": float(line.debit_amount or 0),
                        "credit_amount": float(line.credit_amount or 0),
                        "description": line.description or "",
                    }
                )

        payload = {"results": results}
        if get_export_format(request):
            rows = [
                [
                    r["posting_date"],
                    r["batch_status"],
                    r["journal_reference"],
                    r["staff_name"],
                    r["line_type"],
                    r["debit_account"],
                    r["credit_account"],
                    r["debit_amount"],
                    r["credit_amount"],
                    r["description"],
                ]
                for r in results
            ]
            export_response = export_tabular_report(
                request,
                filename_base="payroll-posting-journal",
                
                title="Payroll Posting Journal",
                subtitle=None,
                summary_rows=[("Line Count", len(results))],
                headers=["Date", "Status", "Journal Ref", "Staff", "Line Type", "Debit Acct", "Credit Acct", "Debit", "Credit", "Description"],
                rows=rows,
            
            )
            if export_response:
                return export_response
        return Response(payload)
