"""Bulk student report card export by grade level / section."""

from __future__ import annotations

import json
import logging
import re
import zipfile
from io import BytesIO

from django.http import HttpResponse
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from grading.access_policies import GradebookAccessPolicy
from grading.models import GradeBook
from grading.services.pdf_report import build_student_report_card_pdf_bytes
from grading.utils import calculate_student_overall_average, get_letter_grade
from common.status import EnrollmentStatus
from students.models import Enrollment

from ..utils.export_helpers import read_multi_query_values, resolve_academic_year
from ..utils.pdf_merge import merge_pdf_bytes

logger = logging.getLogger(__name__)

MAX_BULK_REPORT_CARDS = 200

BUNDLE_INDIVIDUAL = "individual"
BUNDLE_COMBINED = "combined"


def _safe_zip_name(value: str) -> str:
    cleaned = re.sub(r"[^\w\-.]+", "_", str(value or "").strip())
    return cleaned or "report"


def _is_truthy_param(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes"}


def _resolve_bundle_mode(request) -> str | None:
    """
    Return BUNDLE_INDIVIDUAL, BUNDLE_COMBINED, or None when not downloading.
    """
    export = str(request.query_params.get("export") or "").strip().lower()
    bundle = str(request.query_params.get("bundle") or "").strip().lower()

    if export in {"zip", "individual", "separate", "multiple"}:
        return BUNDLE_INDIVIDUAL
    if export in {"pdf", "combined", "single", "merged", "merge"}:
        return BUNDLE_COMBINED
    if bundle in {"individual", "separate", "multiple", "zip"}:
        return BUNDLE_INDIVIDUAL
    if bundle in {"combined", "single", "merged", "pdf"}:
        return BUNDLE_COMBINED
    if _is_truthy_param(export) or _is_truthy_param(request.query_params.get("download")):
        return BUNDLE_COMBINED if bundle == BUNDLE_COMBINED else BUNDLE_INDIVIDUAL
    return None


def _gradebooks_for_section(section_id, academic_year, cache: dict) -> list:
    if not section_id:
        return []
    if section_id not in cache:
        cache[section_id] = list(
            GradeBook.objects.filter(
                section_id=section_id,
                academic_year=academic_year,
                active=True,
            ).select_related("subject", "section", "section_subject")
        )
    return cache[section_id]


def _build_student_report_rows(enrollment_list, academic_year) -> list[dict]:
    """Build preview rows with overall averages (approved grades only)."""
    gradebook_cache: dict = {}
    rows: list[dict] = []

    for enrollment in enrollment_list:
        student = enrollment.student
        gradebooks = _gradebooks_for_section(
            enrollment.section_id, academic_year, gradebook_cache
        )
        avg_data = calculate_student_overall_average(
            student,
            academic_year,
            gradebooks=gradebooks,
            status="approved",
        )
        final_average = avg_data.get("final_average")
        has_grades = final_average is not None

        rows.append(
            {
                "enrollment_id": str(enrollment.id),
                "student_id": student.id_number,
                "student_name": student.get_full_name(),
                "grade_level": enrollment.grade_level.name if enrollment.grade_level else "",
                "section": enrollment.section.name if enrollment.section else "",
                "overall_average": final_average,
                "letter_grade": get_letter_grade(final_average) if has_grades else None,
                "has_grades": has_grades,
                "gradebook_count": avg_data.get("total_gradebooks") or 0,
            }
        )

    return rows


def _filter_enrollments_by_grade_status(
    enrollment_list, student_rows: list[dict], *, exclude_no_grades: bool
) -> list:
    if not exclude_no_grades:
        return enrollment_list
    rows_with_grades = {row["enrollment_id"] for row in student_rows if row["has_grades"]}
    return [e for e in enrollment_list if str(e.id) in rows_with_grades]


def _generate_report_card_documents(enrollment_list, academic_year):
    pdf_documents: list[tuple[str, bytes]] = []
    failures: list[dict[str, str]] = []

    for enrollment in enrollment_list:
        student = enrollment.student
        filename = (
            f"report_card_{_safe_zip_name(student.id_number)}_"
            f"{_safe_zip_name(academic_year.name)}.pdf"
        )
        try:
            pdf_bytes = build_student_report_card_pdf_bytes(
                student, academic_year, enrollment
            )
            pdf_documents.append((filename, pdf_bytes))
        except Exception as exc:
            logger.exception(
                "Report card generation failed for student %s",
                student.id_number,
            )
            failures.append(
                {
                    "student_id": student.id_number,
                    "student_name": student.get_full_name(),
                    "error": str(exc),
                }
            )

    return pdf_documents, failures


def _build_download_filename(academic_year, grade_level_ids, section_ids, extension: str) -> str:
    section_part = section_ids[0] if len(section_ids) == 1 else "multi"
    grade_part = grade_level_ids[0] if len(grade_level_ids) == 1 else "multi"
    return (
        f"report_cards_{_safe_zip_name(academic_year.name)}_"
        f"g{grade_part}_s{section_part}.{extension}"
    )


class BulkReportCardsExportView(APIView):
    """
    Preview or download report cards for students in a grade level and/or section.

    GET /reports/academics/report-cards/?academic_year_id=...&grade_level_id=...&section_id=...
      - preview=true  -> JSON list + count
      - exclude_no_grades=true -> omit students without approved grades (export only)
      - export=zip or bundle=individual -> ZIP of separate PDFs
      - export=pdf or bundle=combined   -> single merged PDF
    """

    permission_classes = [GradebookAccessPolicy]

    def get(self, request):
        academic_year, error = resolve_academic_year(request)
        if error:
            return error

        grade_level_ids = read_multi_query_values(request, "grade_level_id")
        section_ids = read_multi_query_values(request, "section_id")
        exclude_no_grades = _is_truthy_param(
            request.query_params.get("exclude_no_grades")
        )

        if not grade_level_ids and not section_ids:
            return Response(
                {
                    "detail": "Provide at least one filter: grade_level_id and/or section_id.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        enrollments = (
            Enrollment.objects.filter(academic_year=academic_year)
            .exclude(status=EnrollmentStatus.WITHDRAWN)
            .select_related("student", "section", "grade_level", "section__grade_level")
            .order_by("section__name", "student__last_name", "student__first_name")
        )

        if section_ids:
            enrollments = enrollments.filter(section_id__in=section_ids)
        if grade_level_ids:
            enrollments = enrollments.filter(
                section__grade_level_id__in=grade_level_ids
            )

        enrollment_list = list(enrollments)
        student_rows = _build_student_report_rows(enrollment_list, academic_year)
        export_enrollments = _filter_enrollments_by_grade_status(
            enrollment_list,
            student_rows,
            exclude_no_grades=exclude_no_grades,
        )

        bundle_mode = _resolve_bundle_mode(request)
        preview = _is_truthy_param(request.query_params.get("preview"))

        with_grades = sum(1 for row in student_rows if row["has_grades"])
        without_grades = len(student_rows) - with_grades

        if preview and bundle_mode is None:
            return Response(
                {
                    "academic_year_id": str(academic_year.id),
                    "academic_year": str(academic_year),
                    "total_enrolled": len(student_rows),
                    "with_grades": with_grades,
                    "without_grades": without_grades,
                    "count": len(export_enrollments),
                    "max_export": MAX_BULK_REPORT_CARDS,
                    "bundle_modes": [BUNDLE_INDIVIDUAL, BUNDLE_COMBINED],
                    "students": student_rows,
                }
            )

        if bundle_mode is None:
            return Response(
                {
                    "detail": (
                        "Use export=zip (separate PDFs in a ZIP) or export=pdf "
                        "(one combined PDF). Optional bundle=individual|combined."
                    ),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not export_enrollments:
            return Response(
                {
                    "detail": (
                        "No students with approved grades match the selected filters."
                        if exclude_no_grades
                        else "No enrolled students match the selected filters."
                    ),
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        if len(export_enrollments) > MAX_BULK_REPORT_CARDS:
            return Response(
                {
                    "detail": (
                        f"Too many students ({len(export_enrollments)}) for a single download. "
                        f"Maximum is {MAX_BULK_REPORT_CARDS}. Narrow filters or export in smaller groups."
                    ),
                    "count": len(export_enrollments),
                    "max_export": MAX_BULK_REPORT_CARDS,
                },
                status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )

        pdf_documents, failures = _generate_report_card_documents(
            export_enrollments, academic_year
        )

        if not pdf_documents:
            return Response(
                {
                    "detail": "Could not generate any report cards.",
                    "failures": failures,
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        manifest = {
            "academic_year": str(academic_year),
            "bundle": bundle_mode,
            "exclude_no_grades": exclude_no_grades,
            "generated": len(pdf_documents),
            "failed": len(failures),
            "failures": failures,
        }

        if bundle_mode == BUNDLE_COMBINED:
            try:
                merged_bytes = merge_pdf_bytes([doc[1] for doc in pdf_documents])
            except Exception as exc:
                logger.exception("Failed to merge report card PDFs")
                return Response(
                    {
                        "detail": f"Failed to merge report cards into one PDF: {exc}",
                        "failures": failures,
                    },
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

            filename = _build_download_filename(
                academic_year, grade_level_ids, section_ids, "pdf"
            )
            response = HttpResponse(merged_bytes, content_type="application/pdf")
            response["Content-Disposition"] = f'attachment; filename="{filename}"'
            if failures:
                response["X-Report-Card-Failures"] = str(len(failures))
            return response

        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for filename, pdf_bytes in pdf_documents:
                archive.writestr(filename, pdf_bytes)
            archive.writestr(
                "manifest.json",
                json.dumps(manifest, indent=2),
            )

        zip_buffer.seek(0)
        zip_name = _build_download_filename(
            academic_year, grade_level_ids, section_ids, "zip"
        )
        response = HttpResponse(
            zip_buffer.getvalue(),
            content_type="application/zip",
        )
        response["Content-Disposition"] = f'attachment; filename="{zip_name}"'
        return response
