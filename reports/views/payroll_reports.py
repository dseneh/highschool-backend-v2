"""Payroll reports."""

from __future__ import annotations

from decimal import Decimal

from rest_framework.response import Response
from rest_framework.views import APIView

from accounting.models import AccountingPayrollPostingBatch, AccountingPayrollPostingLine
from payroll_v2.models import PayrollEmployeeItem, PayrollRunRecord

from ..access_policies import ReportsAccessPolicy
from ..utils.export_helpers import export_tabular_report, get_export_format, parse_date_param, resolve_export_currency_note


def _apply_payroll_run_filters(queryset, request):
    """Filter payroll runs by optional date range overlap and pay schedule."""
    start_date = parse_date_param(request.query_params.get("start_date"))
    end_date = parse_date_param(request.query_params.get("end_date"))
    pay_schedule_id = (
        request.query_params.get("pay_schedule_id")
        or request.query_params.get("schedule_id")
        or request.query_params.get("schedule")
    )

    if start_date:
        queryset = queryset.filter(pay_period_end__gte=start_date)
    if end_date:
        queryset = queryset.filter(pay_period_start__lte=end_date)
    if pay_schedule_id:
        queryset = queryset.filter(pay_schedule_id=pay_schedule_id)
    return queryset


class PayrollRunSummaryReportView(APIView):
    permission_classes = [ReportsAccessPolicy]

    def get(self, request):
        runs = PayrollRunRecord.objects.select_related("pay_schedule", "payroll_period").order_by(
            "-pay_period_end",
            "-created_at",
        )
        runs = _apply_payroll_run_filters(runs, request)

        results = []
        for run in runs:
            items = run.employee_items.all()
            employee_count = items.count()
            gross = sum((item.gross_pay for item in items), Decimal("0.00"))
            tax = sum((item.total_tax for item in items), Decimal("0.00"))
            deductions = sum((item.total_deductions for item in items), Decimal("0.00"))
            reimbursements = sum((item.total_reimbursements for item in items), Decimal("0.00"))
            take_home = sum((item.net_pay for item in items), Decimal("0.00"))
            non_tax_deductions = deductions - tax
            taxable_net = take_home - reimbursements
            schedule = run.pay_schedule
            period = run.payroll_period
            results.append(
                {
                    "run_id": str(run.id),
                    "schedule_name": schedule.name if schedule else "",
                    "period_name": period.name if period else run.payroll_number,
                    "start_date": run.pay_period_start.isoformat() if run.pay_period_start else "",
                    "end_date": run.pay_period_end.isoformat() if run.pay_period_end else "",
                    "status": run.status,
                    "employee_count": employee_count,
                    "gross_total": float(gross),
                    "deductions_total": float(non_tax_deductions),
                    "tax_total": float(tax),
                    "taxable_net_total": float(taxable_net),
                    "adjustments_total": float(reimbursements),
                    "take_home_total": float(take_home),
                }
            )

        summary = {
            "run_count": len(results),
            "employee_count": sum(row["employee_count"] for row in results),
            "gross_total": sum(row["gross_total"] for row in results),
            "deductions_total": sum(row["deductions_total"] for row in results),
            "tax_total": sum(row["tax_total"] for row in results),
            "taxable_net_total": sum(row["taxable_net_total"] for row in results),
            "adjustments_total": sum(row["adjustments_total"] for row in results),
            "take_home_total": sum(row["take_home_total"] for row in results),
        }
        payload = {"results": results, "summary": summary}
        if get_export_format(request):
            rows = [
                [
                    r["schedule_name"],
                    r["period_name"],
                    r["start_date"],
                    r["end_date"],
                    r["status"],
                    r["employee_count"],
                    r["gross_total"],
                    r["deductions_total"],
                    r["tax_total"],
                    r["taxable_net_total"],
                    r["adjustments_total"],
                    r["take_home_total"],
                ]
                for r in results
            ]
            export_response = export_tabular_report(
                request,
                filename_base="payroll-run-summary",
                title="Payroll Run Summary",
                subtitle=resolve_export_currency_note(request),
                summary_rows=[
                    ("Runs", summary["run_count"]),
                    ("Employees", summary["employee_count"]),
                    ("Gross Total", summary["gross_total"]),
                    ("Net Total", summary["taxable_net_total"]),
                    ("Adjustments Total", summary["adjustments_total"]),
                    ("Take Home Total", summary["take_home_total"]),
                ],
                headers=[
                    "Schedule",
                    "Period",
                    "Start",
                    "End",
                    "Status",
                    "Employees",
                    "Gross",
                    "Deductions",
                    "Tax",
                    "Net",
                    "Adjustments",
                    "Take Home",
                ],
                rows=rows,
                plain_amounts=True,
            )
            if export_response:
                return export_response
        return Response(payload)


class PayrollRegisterReportView(APIView):
    permission_classes = [ReportsAccessPolicy]

    def get(self, request):
        payroll_run_id = request.query_params.get("payroll_run_id")
        pay_schedule_id = (
            request.query_params.get("pay_schedule_id")
            or request.query_params.get("schedule_id")
            or request.query_params.get("schedule")
        )
        items = PayrollEmployeeItem.objects.select_related(
            "employee",
            "payroll",
            "payroll__pay_schedule",
            "payroll__payroll_period",
        ).order_by(
            "employee__last_name",
            "employee__first_name",
        )
        if payroll_run_id:
            items = items.filter(payroll_id=payroll_run_id)
        if pay_schedule_id:
            items = items.filter(payroll__pay_schedule_id=pay_schedule_id)

        results = []
        for item in items:
            run = item.payroll
            period = run.payroll_period if run else None
            schedule = run.pay_schedule if run else None
            take_home = float(item.net_pay or 0)
            reimbursements = float(item.total_reimbursements or 0)
            tax = float(item.total_tax or 0)
            deductions = float(item.total_deductions or 0)
            taxable_net = take_home - reimbursements
            results.append(
                {
                    "employee_id": item.employee.id_number or str(item.employee_id),
                    "employee_name": item.employee.get_full_name(),
                    "schedule_name": schedule.name if schedule else "",
                    "period_name": period.name if period else (run.payroll_number if run else ""),
                    "run_status": run.status if run else "",
                    "gross_pay": float(item.gross_pay or 0),
                    "total_deductions": deductions - tax,
                    "tax": tax,
                    "taxable_net": taxable_net,
                    "adjustments": reimbursements,
                    "take_home": take_home,
                }
            )

        summary = {
            "employee_count": len(results),
            "gross_total": sum(row["gross_pay"] for row in results),
            "deductions_total": sum(row["total_deductions"] for row in results),
            "tax_total": sum(row["tax"] for row in results),
            "taxable_net_total": sum(row["taxable_net"] for row in results),
            "adjustments_total": sum(row["adjustments"] for row in results),
            "take_home_total": sum(row["take_home"] for row in results),
        }
        payload = {"results": results, "summary": summary}
        if get_export_format(request):
            rows = [
                [
                    r["employee_id"],
                    r["employee_name"],
                    r["schedule_name"],
                    r["period_name"],
                    r["run_status"],
                    r["gross_pay"],
                    r["total_deductions"],
                    r["tax"],
                    r["taxable_net"],
                    r["adjustments"],
                    r["take_home"],
                ]
                for r in results
            ]
            export_response = export_tabular_report(
                request,
                filename_base="payroll-register",
                title="Payroll Register",
                subtitle=resolve_export_currency_note(request),
                summary_rows=[
                    ("Employee Count", summary["employee_count"]),
                    ("Gross Total", summary["gross_total"]),
                    ("Net Total", summary["taxable_net_total"]),
                    ("Adjustments Total", summary["adjustments_total"]),
                    ("Take Home Total", summary["take_home_total"]),
                ],
                headers=[
                    "Employee ID",
                    "Employee Name",
                    "Schedule",
                    "Period",
                    "Run Status",
                    "Gross",
                    "Deductions",
                    "Tax",
                    "Net",
                    "Adjustments",
                    "Take Home",
                ],
                rows=rows,
                plain_amounts=True,
            )
            if export_response:
                return export_response
        return Response(payload)


class PayrollPostingJournalReportView(APIView):
    permission_classes = [ReportsAccessPolicy]

    def get(self, request):
        batches = AccountingPayrollPostingBatch.objects.select_related(
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

        summary = {
            "line_count": len(results),
            "total_debit": sum(r["debit_amount"] for r in results),
            "total_credit": sum(r["credit_amount"] for r in results),
        }
        payload = {"results": results, "summary": summary}
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
                subtitle=resolve_export_currency_note(request),
                summary_rows=[("Line Count", len(results))],
                headers=["Date", "Status", "Journal Ref", "Staff", "Line Type", "Debit Acct", "Credit Acct", "Debit", "Credit", "Description"],
                rows=rows,
                plain_amounts=True,
            )
            if export_response:
                return export_response
        return Response(payload)
