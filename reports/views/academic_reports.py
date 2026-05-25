"""Academic performance reports."""

from __future__ import annotations

from django.db.models import Avg, Count, ExpressionWrapper, F, FloatField
from rest_framework.response import Response
from rest_framework.views import APIView

from grading.models import Grade
from students.models import Enrollment

from ..access_policies import ReportsAccessPolicy
from ..utils.export_helpers import export_tabular_report, get_export_format, parse_date_param, read_multi_query_values, resolve_academic_year


class ClassGradeSummaryReportView(APIView):
    permission_classes = [ReportsAccessPolicy]

    def get(self, request):
        academic_year, error = resolve_academic_year(request)
        if error:
            return error

        grade_level_ids = read_multi_query_values(request, "grade_level_id")
        section_ids = read_multi_query_values(request, "section_id")

        grades = Grade.objects.filter(
            academic_year=academic_year,
            status=Grade.Status.APPROVED,
            score__isnull=False,
            assessment__max_score__gt=0,
        )
        if grade_level_ids:
            grades = grades.filter(section__grade_level_id__in=grade_level_ids)
        if section_ids:
            grades = grades.filter(section_id__in=section_ids)

        percentage_expr = ExpressionWrapper(
            (F("score") * 100.0) / F("assessment__max_score"),
            output_field=FloatField(),
        )

        grouped = (
            grades.values(
                "section__name",
                "section__grade_level__name",
                "subject__name",
            )
            .annotate(
                average_score=Avg(percentage_expr),
                student_count=Count("student_id", distinct=True),
                grade_count=Count("id"),
            )
            .order_by("section__grade_level__name", "section__name")
        )

        results = []
        for row in grouped:
            avg_score = float(row["average_score"] or 0)
            results.append(
                {
                    "grade_level": row["section__grade_level__name"] or "",
                    "section": row["section__name"] or "",
                    "subject": row["subject__name"] or "",
                    "average_score": round(avg_score, 2),
                    "student_count": row["student_count"],
                    "grade_count": row["grade_count"],
                }
            )

        payload = {"academic_year_id": str(academic_year.id), "results": results}
        if get_export_format(request):
            rows = [
                [r["grade_level"], r["section"], r["subject"], r["average_score"], r["student_count"], r["grade_count"]]
                for r in results
            ]
            export_response = export_tabular_report(
                request,
                filename_base=f"class-grade-summary-{academic_year.id}",
                title="Class Grade Summary",
                subtitle=f"Academic Year: {academic_year}",
                summary_rows=None,
                headers=["Grade", "Section", "Subject", "Average Score", "Students", "Grades"],
                rows=rows,
            
            )
            if export_response:
                return export_response
        return Response(payload)


class HonorRollReportView(APIView):
    permission_classes = [ReportsAccessPolicy]

    def get(self, request):
        academic_year, error = resolve_academic_year(request)
        if error:
            return error

        min_average = float(request.query_params.get("min_average") or 85)
        grade_level_ids = read_multi_query_values(request, "grade_level_id")
        section_ids = read_multi_query_values(request, "section_id")
        marking_period_id = (request.query_params.get("marking_period_id") or "").strip() or None
        marking_period_label = "All marking periods"
        if marking_period_id:
            from academics.models import MarkingPeriod

            mp = MarkingPeriod.objects.filter(id=marking_period_id).first()
            if mp:
                marking_period_label = mp.name

        enrollments_qs = Enrollment.objects.filter(academic_year=academic_year).select_related(
            "student",
            "section",
            "section__grade_level",
        )
        if grade_level_ids:
            enrollments_qs = enrollments_qs.filter(section__grade_level_id__in=grade_level_ids)
        if section_ids:
            enrollments_qs = enrollments_qs.filter(section_id__in=section_ids)

        enrollments = list(enrollments_qs)
        if not enrollments:
            payload = {
                "academic_year_id": str(academic_year.id),
                "min_average": min_average,
                "marking_period_id": marking_period_id,
                "marking_period_label": marking_period_label,
                "results": [],
            }
            if get_export_format(request):
                export_response = export_tabular_report(
                    request,
                    filename_base=f"honor-roll-{academic_year.id}",
                    title="Honor Roll",
                    subtitle=f"Minimum Average: {min_average} | {marking_period_label}",
                    summary_rows=[("Honorees", 0)],
                    headers=["Rank", "Student ID", "Name", "Grade", "Section", "Average", "Grades"],
                    rows=[],
                )
                if export_response:
                    return export_response
            return Response(payload)

        enrollment_map = {str(e.student_id): e for e in enrollments}
        student_ids = [e.student_id for e in enrollments]

        percentage_expr = ExpressionWrapper(
            (F("score") * 100.0) / F("assessment__max_score"),
            output_field=FloatField(),
        )
        grade_filters = {
            "academic_year": academic_year,
            "status": Grade.Status.APPROVED,
            "assessment__is_calculated": True,
            "score__isnull": False,
            "assessment__max_score__gt": 0,
            "student_id__in": student_ids,
        }
        if marking_period_id:
            grade_filters["assessment__marking_period_id"] = marking_period_id

        averages_qs = (
            Grade.objects.filter(**grade_filters)
            .values("student_id")
            .annotate(
                average_score=Avg(percentage_expr),
                grade_count=Count("id"),
            )
        )

        results = []
        for row in averages_qs:
            average = round(float(row["average_score"] or 0), 2)
            if average < min_average:
                continue
            student_id = str(row["student_id"])
            enrollment = enrollment_map.get(student_id)
            if not enrollment:
                continue
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
                    "average_score": average,
                    "grade_count": row["grade_count"],
                }
            )

        results.sort(key=lambda row: (-row["average_score"], row["student_name"]))
        for idx, row in enumerate(results, 1):
            row["rank"] = idx

        payload = {
            "academic_year_id": str(academic_year.id),
            "min_average": min_average,
            "marking_period_id": marking_period_id,
            "marking_period_label": marking_period_label,
            "results": results,
        }

        if get_export_format(request):
            rows = [
                [r["rank"], r["student_id"], r["student_name"], r["grade_level"], r["section"], r["average_score"], r["grade_count"]]
                for r in results
            ]
            export_response = export_tabular_report(
                request,
                filename_base=f"honor-roll-{academic_year.id}",
                title="Honor Roll",
                subtitle=f"Minimum Average: {min_average} | {marking_period_label}",
                summary_rows=[("Honorees", len(results))],
                headers=["Rank", "Student ID", "Name", "Grade", "Section", "Average", "Grades"],
                rows=rows,
            
            )
            if export_response:
                return export_response
        return Response(payload)
