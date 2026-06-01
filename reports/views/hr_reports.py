"""HR and staff reports."""

from __future__ import annotations

from django.db.models import Count
from rest_framework.response import Response
from rest_framework.views import APIView

from hr.employee_filters import apply_employee_list_filters
from hr.models import Employee

from ..access_policies import ReportsAccessPolicy
from ..services.employee_list_export import (
    EMPLOYEE_EXPORT_HEADERS,
    build_grouped_employee_export_rows,
)
from ..utils.export_helpers import export_tabular_report, get_export_format


def _format_gender(value: str | None) -> str:
    if not value:
        return ""
    return str(value).replace("_", " ").title()


def _format_status(value: str | None) -> str:
    if not value:
        return ""
    return str(value).replace("_", " ").title()


def _employee_records(queryset) -> list[dict]:
    records: list[dict] = []
    for employee in queryset:
        readiness = employee.payroll_readiness()
        records.append(
            {
                "employee_id": employee.id_number or str(employee.id),
                "full_name": employee.get_full_name(),
                "email": employee.email or "",
                "phone": employee.phone_number or "",
                "gender": _format_gender(employee.gender),
                "department": employee.department.name if employee.department else "",
                "position": employee.position.title if employee.position else "",
                "manager": employee.manager.get_full_name() if employee.manager else "",
                "employment_status": _format_status(employee.employment_status),
                "role": "Teacher" if employee.is_teacher else "Staff",
                "payroll_ready": "Yes" if readiness.get("ready") else "No",
                "hire_date": employee.hire_date.isoformat() if employee.hire_date else "",
                "job_title": employee.job_title or "",
            }
        )
    return records


class EmployeeListReportView(APIView):
    """Filtered employee roster with optional grouped PDF/Excel export."""

    permission_classes = [ReportsAccessPolicy]

    def get(self, request):
        group_by = (request.query_params.get("group_by") or "none").strip().lower()
        if group_by not in {"none", "department", "position"}:
            group_by = "none"

        employees = (
            Employee.objects.select_related("department", "position", "manager")
            .order_by("last_name", "first_name", "id_number")
        )
        employees = apply_employee_list_filters(employees, request.query_params)

        results = _employee_records(employees)

        summary = (
            employees.values("department__name")
            .annotate(count=Count("id"))
            .order_by("department__name")
        )
        payload = {
            "results": results,
            "summary_by_department": [
                {"department": row["department__name"] or "Unassigned", "count": row["count"]}
                for row in summary
            ],
            "total_count": len(results),
            "group_by": group_by,
        }

        export_format = get_export_format(request)
        if export_format:
            grouped_label = {
                "none": None,
                "department": "Department",
                "position": "Position",
            }.get(group_by)
            subtitle_parts = [f"Total employees: {len(results)}"]
            if grouped_label:
                subtitle_parts.append(f"Grouped by {grouped_label}")

            rows = build_grouped_employee_export_rows(results, group_by=group_by)
            export_response = export_tabular_report(
                request,
                filename_base="employees-export",
                title="Employee List",
                subtitle=" · ".join(subtitle_parts),
                summary_rows=[("Total Employees", len(results))],
                headers=EMPLOYEE_EXPORT_HEADERS,
                rows=rows,
                column_widths=[14, 24, 24, 14, 10, 18, 18, 20, 14, 10, 12, 12, 18],
            )
            if export_response:
                return export_response

        return Response(payload)


class StaffDirectoryReportView(EmployeeListReportView):
    """Backward-compatible staff directory report (active employees by default)."""

    def get(self, request):
        params = request.query_params.copy()
        include_inactive = params.get("include_inactive", "").lower() in {"1", "true", "yes"}
        if not include_inactive and not params.get("employment_status") and not params.get("status"):
            params["employment_status"] = Employee.EmploymentStatus.ACTIVE
        if params.get("department_id") and not params.get("department"):
            params["department"] = params.get("department_id")

        group_by = (params.get("group_by") or "none").strip().lower()
        if group_by not in {"none", "department", "position"}:
            group_by = "none"

        employees = (
            Employee.objects.select_related("department", "position", "manager")
            .order_by("last_name", "first_name", "id_number")
        )
        employees = apply_employee_list_filters(employees, params)
        results = _employee_records(employees)

        summary = (
            employees.values("department__name")
            .annotate(count=Count("id"))
            .order_by("department__name")
        )
        payload = {
            "results": results,
            "summary_by_department": [
                {"department": row["department__name"] or "Unassigned", "count": row["count"]}
                for row in summary
            ],
            "total_count": len(results),
            "group_by": group_by,
        }

        export_format = get_export_format(request)
        if export_format:
            grouped_label = {"none": None, "department": "Department", "position": "Position"}.get(group_by)
            subtitle_parts = [f"Total employees: {len(results)}"]
            if grouped_label:
                subtitle_parts.append(f"Grouped by {grouped_label}")
            rows = build_grouped_employee_export_rows(results, group_by=group_by)
            export_response = export_tabular_report(
                request,
                filename_base="staff-directory",
                title="Staff Directory",
                subtitle=" · ".join(subtitle_parts),
                summary_rows=[("Total Staff", len(results))],
                headers=EMPLOYEE_EXPORT_HEADERS,
                rows=rows,
                column_widths=[14, 24, 24, 14, 10, 18, 18, 20, 14, 10, 12, 12, 18],
            )
            if export_response:
                return export_response

        return Response(payload)
