"""Accounts receivable and collections reports."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.db.models.functions import Coalesce
from rest_framework.response import Response
from rest_framework.views import APIView

from accounting.models import (
    AccountingConcession,
    AccountingInstallmentLine,
    AccountingInstallmentPlan,
    AccountingStudentBill,
    AccountingStudentPaymentAllocation,
)
from students.services.balance import annotate_student_balance_totals

from ..access_policies import ReportsAccessPolicy
from ..utils.export_helpers import export_tabular_report, get_export_format, read_multi_query_values, resolve_academic_year


def _filter_bills(request, academic_year):
    bills = (
        AccountingStudentBill.objects.filter(academic_year=academic_year)
        .exclude(status=AccountingStudentBill.BillStatus.CANCELLED)
        .select_related(
            "student",
            "enrollment",
            "enrollment__section",
            "grade_level",
        )
    )
    grade_level_ids = read_multi_query_values(request, "grade_level_id")
    section_ids = read_multi_query_values(request, "section_id")
    if grade_level_ids:
        bills = bills.filter(grade_level_id__in=grade_level_ids)
    if section_ids:
        bills = bills.filter(enrollment__section_id__in=section_ids)
    student_query = (request.query_params.get("student") or "").strip()
    if student_query:
        bills = bills.filter(
            Q(student__id_number__icontains=student_query)
            | Q(student__first_name__icontains=student_query)
            | Q(student__last_name__icontains=student_query)
        )
    return bills


def _aging_bucket(days_overdue: int) -> str:
    if days_overdue <= 0:
        return "current"
    if days_overdue <= 30:
        return "1_30"
    if days_overdue <= 60:
        return "31_60"
    if days_overdue <= 90:
        return "61_90"
    return "90_plus"


class ARAgingReportView(APIView):
    """Outstanding balances bucketed by age."""

    permission_classes = [ReportsAccessPolicy]

    def get(self, request):
        academic_year, error = resolve_academic_year(request)
        if error:
            return error

        today = date.today()
        bills = list(_filter_bills(request, academic_year))
        student_ids = {bill.student_id for bill in bills}
        from students.models import Student

        balance_map = {
            str(row.id): float(row.balance_total or 0)
            for row in annotate_student_balance_totals(
                Student.objects.filter(id__in=student_ids),
                academic_year=academic_year,
            )
        }

        results = []
        summary = {
            "current": 0.0,
            "1_30": 0.0,
            "31_60": 0.0,
            "61_90": 0.0,
            "90_plus": 0.0,
            "total_outstanding": 0.0,
        }

        for bill in bills:
            balance = balance_map.get(str(bill.student_id), float(bill.outstanding_amount))
            if balance <= 0:
                continue
            days_overdue = (today - bill.due_date).days
            bucket = _aging_bucket(days_overdue)
            summary[bucket] = round(summary[bucket] + balance, 2)
            summary["total_outstanding"] = round(summary["total_outstanding"] + balance, 2)
            results.append(
                {
                    "student_id": bill.student.id_number,
                    "student_name": bill.student.get_full_name(),
                    "grade_level": bill.grade_level.name if bill.grade_level else "",
                    "section": bill.enrollment.section.name if bill.enrollment and bill.enrollment.section else "",
                    "due_date": bill.due_date.isoformat(),
                    "days_overdue": max(days_overdue, 0),
                    "aging_bucket": bucket,
                    "net_bill": float(bill.net_amount),
                    "outstanding": round(balance, 2),
                    "status": bill.status,
                }
            )

        payload = {
            "academic_year_id": str(academic_year.id),
            "academic_year": str(academic_year),
            "summary": summary,
            "results": results,
        }

        rows = [
            [
                r["student_id"],
                r["student_name"],
                r["grade_level"],
                r["section"],
                r["due_date"],
                r["days_overdue"],
                r["aging_bucket"],
                r["net_bill"],
                r["outstanding"],
                r["status"],
            ]
            for r in results
        ]
        export_response = export_tabular_report(
            request,
            filename_base=f"ar-aging-{academic_year.id}",
            title="AR Aging Report",
            subtitle=f"Academic Year: {academic_year}",
            summary_rows=[
                ("Current", summary["current"]),
                ("1-30 Days", summary["1_30"]),
                ("31-60 Days", summary["31_60"]),
                ("61-90 Days", summary["61_90"]),
                ("90+ Days", summary["90_plus"]),
                ("Total Outstanding", summary["total_outstanding"]),
            ],
            headers=[
                "Student ID",
                "Student Name",
                "Grade",
                "Section",
                "Due Date",
                "Days Overdue",
                "Bucket",
                "Net Bill",
                "Outstanding",
                "Status",
            ],
            rows=rows,
        )
        if export_response:
            return export_response
        return Response(payload)


class InstallmentComplianceReportView(APIView):
    """Expected vs actual payments by installment period."""

    permission_classes = [ReportsAccessPolicy]

    def get(self, request):
        academic_year, error = resolve_academic_year(request)
        if error:
            return error

        plan = (
            AccountingInstallmentPlan.objects.filter(academic_year=academic_year, is_active=True)
            .prefetch_related("lines")
            .first()
        )
        installment_lines = list(plan.lines.order_by("sequence")) if plan else []
        bills = list(_filter_bills(request, academic_year))

        from students.models import Student

        student_ids = {bill.student_id for bill in bills}
        balance_map = {
            str(row.id): float(row.paid_total or 0)
            for row in annotate_student_balance_totals(
                Student.objects.filter(id__in=student_ids),
                academic_year=academic_year,
            )
        }

        allocation_totals = (
            AccountingStudentPaymentAllocation.objects.filter(
                student_bill__academic_year=academic_year,
            )
            .values("installment_line_id")
            .annotate(total=Coalesce(Sum("allocated_amount"), Decimal("0")))
        )
        allocated_by_line = {
            str(row["installment_line_id"]): float(row["total"] or 0)
            for row in allocation_totals
            if row["installment_line_id"]
        }

        results = []
        for line in installment_lines:
            expected_total = 0.0
            actual_total = allocated_by_line.get(str(line.id), 0.0)
            student_count = 0
            for bill in bills:
                expected = round(float(bill.net_amount) * float(line.percentage) / 100.0, 2)
                if expected <= 0:
                    continue
                student_count += 1
                expected_total += expected
                paid = balance_map.get(str(bill.student_id), float(bill.paid_amount))
                compliance_pct = round(min(paid, expected) / expected * 100, 1) if expected else 0
                results.append(
                    {
                        "installment_name": line.name,
                        "installment_sequence": line.sequence,
                        "due_date": line.due_date.isoformat(),
                        "percentage": float(line.percentage),
                        "student_id": bill.student.id_number,
                        "student_name": bill.student.get_full_name(),
                        "grade_level": bill.grade_level.name if bill.grade_level else "",
                        "section": bill.enrollment.section.name if bill.enrollment and bill.enrollment.section else "",
                        "expected_amount": expected,
                        "total_paid_to_date": round(paid, 2),
                        "compliance_pct": compliance_pct,
                        "is_overdue": line.due_date < date.today() and paid < expected,
                    }
                )

            if student_count == 0:
                results.append(
                    {
                        "installment_name": line.name,
                        "installment_sequence": line.sequence,
                        "due_date": line.due_date.isoformat(),
                        "percentage": float(line.percentage),
                        "student_id": "",
                        "student_name": "",
                        "grade_level": "",
                        "section": "",
                        "expected_amount": 0,
                        "total_paid_to_date": round(actual_total, 2),
                        "compliance_pct": 0,
                        "is_overdue": line.due_date < date.today(),
                    }
                )

        payload = {
            "academic_year_id": str(academic_year.id),
            "plan_name": plan.name if plan else "",
            "results": results,
        }

        if get_export_format(request):
            rows = [
                [
                    r["installment_name"],
                    r["due_date"],
                    r["student_id"],
                    r["student_name"],
                    r["grade_level"],
                    r["section"],
                    r["expected_amount"],
                    r["total_paid_to_date"],
                    r["compliance_pct"],
                    "Yes" if r["is_overdue"] else "No",
                ]
                for r in results
            ]
            export_response = export_tabular_report(
                request,
                filename_base=f"installment-compliance-{academic_year.id}",
                title="Installment Compliance Report",
                subtitle=f"Academic Year: {academic_year}",
                summary_rows=None,
                headers=[
                    "Installment",
                    "Due Date",
                    "Student ID",
                    "Student Name",
                    "Grade",
                    "Section",
                    "Expected",
                    "Paid To Date",
                    "Compliance %",
                    "Overdue",
                ],
                rows=rows,
            
            )
            if export_response:
                return export_response
        return Response(payload)


class ConcessionSummaryReportView(APIView):
    """Concession totals grouped by type and target."""

    permission_classes = [ReportsAccessPolicy]

    def get(self, request):
        academic_year, error = resolve_academic_year(request)
        if error:
            return error

        concessions = (
            AccountingConcession.objects.filter(academic_year=academic_year, is_active=True)
            .select_related("student", "student_bill", "student_bill__grade_level")
        )
        grade_level_ids = read_multi_query_values(request, "grade_level_id")
        if grade_level_ids:
            concessions = concessions.filter(student_bill__grade_level_id__in=grade_level_ids)

        grouped: dict[tuple[str, str], dict] = defaultdict(
            lambda: {"count": 0, "total_amount": 0.0, "students": set()}
        )
        detail_rows = []
        for concession in concessions:
            key = (concession.concession_type, concession.target)
            amount = float(concession.computed_amount or 0)
            grouped[key]["count"] += 1
            grouped[key]["total_amount"] = round(grouped[key]["total_amount"] + amount, 2)
            grouped[key]["students"].add(str(concession.student_id))
            detail_rows.append(
                {
                    "student_id": concession.student.id_number,
                    "student_name": concession.student.get_full_name(),
                    "grade_level": (
                        concession.student_bill.grade_level.name
                        if concession.student_bill and concession.student_bill.grade_level
                        else ""
                    ),
                    "concession_type": concession.concession_type,
                    "target": concession.target,
                    "value": float(concession.value),
                    "computed_amount": amount,
                    "start_date": concession.start_date.isoformat(),
                    "end_date": concession.end_date.isoformat() if concession.end_date else "",
                }
            )

        groups = [
            {
                "concession_type": key[0],
                "target": key[1],
                "count": value["count"],
                "student_count": len(value["students"]),
                "total_amount": value["total_amount"],
            }
            for key, value in sorted(grouped.items())
        ]

        payload = {
            "academic_year_id": str(academic_year.id),
            "groups": groups,
            "results": detail_rows,
        }

        if get_export_format(request):
            rows = [
                [
                    r["student_id"],
                    r["student_name"],
                    r["grade_level"],
                    r["concession_type"],
                    r["target"],
                    r["value"],
                    r["computed_amount"],
                    r["start_date"],
                    r["end_date"],
                ]
                for r in detail_rows
            ]
            export_response = export_tabular_report(
                request,
                filename_base=f"concession-summary-{academic_year.id}",
                title="Concession Summary Report",
                subtitle=f"Academic Year: {academic_year}",
                summary_rows=[(f"{g['concession_type']} / {g['target']}", g["total_amount"]) for g in groups],
                headers=[
                    "Student ID",
                    "Student Name",
                    "Grade",
                    "Type",
                    "Target",
                    "Value",
                    "Amount",
                    "Start",
                    "End",
                ],
                rows=rows,
            
            )
            if export_response:
                return export_response
        return Response(payload)


class CollectionRateReportView(APIView):
    """Collection rates rolled up by grade level and section."""

    permission_classes = [ReportsAccessPolicy]

    def get(self, request):
        academic_year, error = resolve_academic_year(request)
        if error:
            return error

        group_by = (request.query_params.get("group_by") or "grade_level").strip().lower()
        if group_by not in {"grade_level", "section"}:
            group_by = "grade_level"

        bills = list(_filter_bills(request, academic_year))
        from students.models import Student

        balance_map = {
            str(row.id): {
                "paid_total": float(row.paid_total or 0),
                "billed_total": float(row.billed_total or 0),
            }
            for row in annotate_student_balance_totals(
                Student.objects.filter(id__in={bill.student_id for bill in bills}),
                academic_year=academic_year,
            )
        }

        buckets: dict[str, dict] = defaultdict(
            lambda: {
                "label": "",
                "student_count": 0,
                "total_billed": 0.0,
                "total_paid": 0.0,
                "total_outstanding": 0.0,
            }
        )

        for bill in bills:
            if group_by == "section":
                key = str(bill.enrollment.section_id) if bill.enrollment and bill.enrollment.section_id else "unassigned"
                label = bill.enrollment.section.name if bill.enrollment and bill.enrollment.section else "Unassigned"
            else:
                key = str(bill.grade_level_id) if bill.grade_level_id else "unassigned"
                label = bill.grade_level.name if bill.grade_level else "Unassigned"

            info = balance_map.get(str(bill.student_id), {})
            billed = info.get("billed_total", float(bill.net_amount))
            paid = info.get("paid_total", float(bill.paid_amount))
            outstanding = max(billed - paid, 0)

            bucket = buckets[key]
            bucket["label"] = label
            bucket["student_count"] += 1
            bucket["total_billed"] = round(bucket["total_billed"] + billed, 2)
            bucket["total_paid"] = round(bucket["total_paid"] + paid, 2)
            bucket["total_outstanding"] = round(bucket["total_outstanding"] + outstanding, 2)

        results = []
        for key, bucket in sorted(buckets.items(), key=lambda item: item[1]["label"]):
            billed = bucket["total_billed"]
            paid = bucket["total_paid"]
            collection_rate = round(paid / billed * 100, 1) if billed else 0
            results.append(
                {
                    "group_id": key,
                    "group_label": bucket["label"],
                    "student_count": bucket["student_count"],
                    "total_billed": billed,
                    "total_paid": paid,
                    "total_outstanding": bucket["total_outstanding"],
                    "collection_rate_pct": collection_rate,
                }
            )

        payload = {
            "academic_year_id": str(academic_year.id),
            "group_by": group_by,
            "results": results,
        }

        if get_export_format(request):
            rows = [
                [
                    r["group_label"],
                    r["student_count"],
                    r["total_billed"],
                    r["total_paid"],
                    r["total_outstanding"],
                    r["collection_rate_pct"],
                ]
                for r in results
            ]
            export_response = export_tabular_report(
                request,
                filename_base=f"collection-rate-{group_by}-{academic_year.id}",
                title="Collection Rate Report",
                subtitle=f"Academic Year: {academic_year} — Grouped by {group_by.replace('_', ' ').title()}",
                summary_rows=None,
                headers=[
                    "Group",
                    "Students",
                    "Total Billed",
                    "Total Paid",
                    "Outstanding",
                    "Collection Rate %",
                ],
                rows=rows,
            
            )
            if export_response:
                return export_response
        return Response(payload)


class PaymentAllocationReportView(APIView):
    """Payment allocations against bills and installments."""

    permission_classes = [ReportsAccessPolicy]

    def get(self, request):
        academic_year, error = resolve_academic_year(request)
        if error:
            return error

        allocations = (
            AccountingStudentPaymentAllocation.objects.filter(student_bill__academic_year=academic_year)
            .select_related(
                "student_bill",
                "student_bill__student",
                "student_bill__grade_level",
                "student_bill__enrollment__section",
                "cash_transaction",
                "installment_line",
            )
            .order_by("-allocation_date")
        )

        grade_level_ids = read_multi_query_values(request, "grade_level_id")
        section_ids = read_multi_query_values(request, "section_id")
        if grade_level_ids:
            allocations = allocations.filter(student_bill__grade_level_id__in=grade_level_ids)
        if section_ids:
            allocations = allocations.filter(student_bill__enrollment__section_id__in=section_ids)

        results = []
        for allocation in allocations:
            bill = allocation.student_bill
            txn = allocation.cash_transaction
            results.append(
                {
                    "student_id": bill.student.id_number,
                    "student_name": bill.student.get_full_name(),
                    "grade_level": bill.grade_level.name if bill.grade_level else "",
                    "section": bill.enrollment.section.name if bill.enrollment and bill.enrollment.section else "",
                    "allocation_date": allocation.allocation_date.isoformat(),
                    "allocated_amount": float(allocation.allocated_amount),
                    "installment_name": allocation.installment_line.name if allocation.installment_line else "",
                    "payment_reference": txn.reference_number if txn else "",
                    "payment_date": txn.transaction_date.isoformat() if txn else "",
                    "bill_net_amount": float(bill.net_amount),
                }
            )

        payload = {
            "academic_year_id": str(academic_year.id),
            "results": results,
        }

        if get_export_format(request):
            rows = [
                [
                    r["student_id"],
                    r["student_name"],
                    r["grade_level"],
                    r["section"],
                    r["allocation_date"],
                    r["allocated_amount"],
                    r["installment_name"],
                    r["payment_reference"],
                    r["payment_date"],
                    r["bill_net_amount"],
                ]
                for r in results
            ]
            export_response = export_tabular_report(
                request,
                filename_base=f"payment-allocations-{academic_year.id}",
                title="Payment Allocation Report",
                subtitle=f"Academic Year: {academic_year}",
                summary_rows=None,
                headers=[
                    "Student ID",
                    "Student Name",
                    "Grade",
                    "Section",
                    "Allocation Date",
                    "Amount",
                    "Installment",
                    "Payment Ref",
                    "Payment Date",
                    "Bill Net",
                ],
                rows=rows,
            
            )
            if export_response:
                return export_response
        return Response(payload)
