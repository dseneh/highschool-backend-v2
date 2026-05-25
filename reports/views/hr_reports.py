"""HR and staff reports."""

from __future__ import annotations

from django.db.models import Count
from rest_framework.response import Response
from rest_framework.views import APIView

from hr.models import Employee

from ..access_policies import ReportsAccessPolicy
from ..utils.export_helpers import export_tabular_report, get_export_format


class StaffDirectoryReportView(APIView):
    permission_classes = [ReportsAccessPolicy]

    def get(self, request):
        include_inactive = request.query_params.get("include_inactive", "").lower() in {"1", "true", "yes"}
        department_id = request.query_params.get("department_id")

        employees = Employee.objects.select_related("department", "position").order_by("last_name", "first_name")
        if not include_inactive:
            employees = employees.filter(employment_status=Employee.EmploymentStatus.ACTIVE)
        if department_id:
            employees = employees.filter(department_id=department_id)

        results = []
        for employee in employees:
            results.append(
                {
                    "employee_id": employee.employee_number or employee.id_number or str(employee.id),
                    "full_name": employee.get_full_name(),
                    "email": employee.email or "",
                    "phone": employee.phone_number or "",
                    "department": employee.department.name if employee.department else "",
                    "position": employee.position.title if employee.position else "",
                    "employment_status": employee.employment_status,
                    "is_active": employee.employment_status == Employee.EmploymentStatus.ACTIVE,
                }
            )

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
        }

        if get_export_format(request):
            rows = [
                [
                    r["employee_id"],
                    r["full_name"],
                    r["email"],
                    r["phone"],
                    r["department"],
                    r["position"],
                    r["employment_status"],
                    "Yes" if r["is_active"] else "No",
                ]
                for r in results
            ]
            export_response = export_tabular_report(
                request,
                filename_base="staff-directory",
                
                title="Staff Directory",
                subtitle=None,
                summary_rows=[("Total Staff", len(results))],
                headers=["Employee ID", "Name", "Email", "Phone", "Department", "Position", "Status", "Active"],
                rows=rows,
            
            )
            if export_response:
                return export_response
        return Response(payload)
