"""Attendance reports."""

from __future__ import annotations

from collections import defaultdict

from rest_framework.response import Response
from rest_framework.views import APIView

from common.status import AttendanceStatus
from students.models import Attendance, Enrollment
from students.services.attendance_stats import build_student_attendance_summary, count_school_days

from ..access_policies import ReportsAccessPolicy
from ..utils.export_helpers import export_tabular_report, get_export_format, parse_date_param, read_multi_query_values, resolve_academic_year


def _filter_enrollments(academic_year, grade_level_ids, section_ids):
    enrollments = Enrollment.objects.filter(academic_year=academic_year).select_related(
        "student",
        "section",
        "section__grade_level",
    )
    if grade_level_ids:
        enrollments = enrollments.filter(section__grade_level_id__in=grade_level_ids)
    if section_ids:
        enrollments = enrollments.filter(section_id__in=section_ids)
    return enrollments.order_by("section__name", "student__last_name")


class AttendanceSummaryReportView(APIView):
    permission_classes = [ReportsAccessPolicy]

    def get(self, request):
        academic_year, error = resolve_academic_year(request)
        if error:
            return error

        start_date = parse_date_param(request.query_params.get("start_date"))
        end_date = parse_date_param(request.query_params.get("end_date"))
        grade_level_ids = read_multi_query_values(request, "grade_level_id")
        section_ids = read_multi_query_values(request, "section_id")

        enrollments = list(_filter_enrollments(academic_year, grade_level_ids, section_ids))
        enrollment_ids = [e.id for e in enrollments]

        attendance_by_enrollment: dict[str, list] = defaultdict(list)
        attendance_qs = Attendance.objects.filter(enrollment_id__in=enrollment_ids)
        if start_date:
            attendance_qs = attendance_qs.filter(date__gte=start_date)
        if end_date:
            attendance_qs = attendance_qs.filter(date__lte=end_date)

        for record in attendance_qs:
            attendance_by_enrollment[str(record.enrollment_id)].append(record)

        school_days = count_school_days(academic_year, start_date=start_date, end_date=end_date)

        results = []
        for enrollment in enrollments:
            rows = attendance_by_enrollment.get(str(enrollment.id), [])
            summary = build_student_attendance_summary(rows, school_days)
            results.append(
                {
                    "student_id": enrollment.student.id_number,
                    "student_name": enrollment.student.get_full_name(),
                    "grade_level": (
                        enrollment.section.grade_level.name
                        if enrollment.section and enrollment.section.grade_level
                        else ""
                    ),
                    "section": enrollment.section.name if enrollment.section else "",
                    "present": summary["present_days"],
                    "absent": summary["absent"],
                    "late": summary["late"],
                    "excused": summary["excused"],
                    "total_days": summary["school_days_elapsed"],
                    "attendance_pct": summary["attendance_rate"],
                }
            )

        payload = {"academic_year_id": str(academic_year.id), "results": results}
        if get_export_format(request):
            rows = [
                [
                    r["student_id"],
                    r["student_name"],
                    r["grade_level"],
                    r["section"],
                    r["present"],
                    r["absent"],
                    r["late"],
                    r["total_days"],
                    r["attendance_pct"],
                ]
                for r in results
            ]
            export_response = export_tabular_report(
                request,
                filename_base=f"attendance-summary-{academic_year.id}",
                title="Student Attendance Summary",
                subtitle=f"Academic Year: {academic_year}",
                summary_rows=None,
                headers=["Student ID", "Name", "Grade", "Section", "Present", "Absent", "Late", "Total Days", "Attendance %"],
                rows=rows,
            )
            if export_response:
                return export_response
        return Response(payload)


class DailyAttendanceRegisterReportView(APIView):
    permission_classes = [ReportsAccessPolicy]

    def get(self, request):
        academic_year, error = resolve_academic_year(request)
        if error:
            return error

        target_date = parse_date_param(request.query_params.get("date"))
        if not target_date:
            from datetime import date

            target_date = date.today()

        grade_level_ids = read_multi_query_values(request, "grade_level_id")
        section_ids = read_multi_query_values(request, "section_id")

        enrollments = _filter_enrollments(academic_year, grade_level_ids, section_ids)

        attendance_map = {
            str(row.enrollment_id): row
            for row in Attendance.objects.filter(
                enrollment__in=enrollments,
                date=target_date,
            ).select_related("enrollment")
        }

        results = []
        for enrollment in enrollments:
            record = attendance_map.get(str(enrollment.id))
            results.append(
                {
                    "date": target_date.isoformat(),
                    "student_id": enrollment.student.id_number,
                    "student_name": enrollment.student.get_full_name(),
                    "grade_level": (
                        enrollment.section.grade_level.name
                        if enrollment.section and enrollment.section.grade_level
                        else ""
                    ),
                    "section": enrollment.section.name if enrollment.section else "",
                    "status": record.status if record else AttendanceStatus.PRESENT.value,
                    "notes": record.notes if record else "",
                }
            )

        payload = {"date": target_date.isoformat(), "results": results}
        if get_export_format(request):
            rows = [
                [r["date"], r["student_id"], r["student_name"], r["grade_level"], r["section"], r["status"], r["notes"]]
                for r in results
            ]
            export_response = export_tabular_report(
                request,
                filename_base=f"daily-attendance-{target_date.isoformat()}",
                title="Daily Attendance Register",
                subtitle=f"Date: {target_date.isoformat()}",
                summary_rows=None,
                headers=["Date", "Student ID", "Name", "Grade", "Section", "Status", "Notes"],
                rows=rows,
            )
            if export_response:
                return export_response
        return Response(payload)
