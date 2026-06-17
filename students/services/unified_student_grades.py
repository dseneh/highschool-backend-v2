"""Build unified student grade rows merging in-school gradebooks and historical transcript grades."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional

from academics.models import AcademicYear
from students.models import Enrollment, Student
from students.models.historical_grade import HistoricalGradeRecord


def historical_grade_rows_for_year(
    student: Student,
    academic_year: AcademicYear,
    *,
    verified_only: bool = True,
) -> list[dict[str, Any]]:
    qs = HistoricalGradeRecord.objects.filter(
        student=student,
        academic_year=academic_year,
    ).select_related("subject", "grade_level", "marking_period")

    if verified_only:
        qs = qs.filter(status=HistoricalGradeRecord.Status.VERIFIED)

    rows = []
    for record in qs.order_by("subject__name", "subject_name"):
        pct = float(record.final_percentage) if record.final_percentage is not None else None
        rows.append(
            {
                "id": str(record.id),
                "source": "transferred",
                "institution_name": record.institution_name,
                "is_editable": False,
                "status": record.status,
                "subject": {
                    "id": str(record.subject_id),
                    "name": record.subject_name or record.subject.name,
                },
                "grade_level": {
                    "id": str(record.grade_level_id),
                    "name": record.grade_level.name,
                },
                "final_percentage": pct,
                "letter_grade": record.final_letter or "-",
                "marking_period": (
                    {"id": str(record.marking_period_id), "name": record.marking_period.name}
                    if record.marking_period_id
                    else None
                ),
                "include_in_calculations": record.include_in_calculations,
            }
        )
    return rows


def historical_year_average(rows: list[dict[str, Any]]) -> Optional[float]:
    values = [
        r["final_percentage"]
        for r in rows
        if r.get("include_in_calculations") and r.get("final_percentage") is not None
    ]
    if not values:
        values = [r["final_percentage"] for r in rows if r.get("final_percentage") is not None]
    if not values:
        return None
    return round(sum(values) / len(values), 1)


def build_historical_only_response(
    student: Student,
    academic_year: AcademicYear,
    *,
    verified_only: bool = False,
) -> dict[str, Any]:
    rows = historical_grade_rows_for_year(
        student, academic_year, verified_only=verified_only
    )
    gradebooks = [
        {
            "id": row["id"],
            "name": row["subject"]["name"],
            "source": "transferred",
            "institution_name": row["institution_name"],
            "is_editable": False,
            "subject": row["subject"],
            "calculation_method": None,
            "final_percentage": row["final_percentage"],
            "letter_grade": row["letter_grade"],
            "status": row["status"],
            "marking_periods": [],
        }
        for row in rows
    ]
    avg = historical_year_average(rows)
    gl = rows[0]["grade_level"] if rows else None
    return {
        "id": str(student.id),
        "id_number": student.id_number,
        "full_name": student.get_full_name(),
        "section": None,
        "grade_level": gl,
        "academic_year": {
            "id": str(academic_year.id),
            "name": academic_year.name,
            "year_type": academic_year.year_type,
        },
        "year_mode": "historical",
        "has_enrollment": False,
        "gradebooks": gradebooks,
        "overall_averages": {"final_average": avg} if avg is not None else None,
        "total_gradebooks": len(gradebooks),
    }


def merge_transferred_into_gradebooks(
    gradebooks_data: list,
    student: Student,
    academic_year: AcademicYear,
    in_school_subject_ids: set[str],
) -> list:
    transferred = historical_grade_rows_for_year(student, academic_year)
    for row in transferred:
        sid = row["subject"]["id"]
        if sid in in_school_subject_ids:
            continue
        gradebooks_data.append(
            {
                "gradebook": None,
                "transferred_row": row,
            }
        )
    return gradebooks_data


def student_has_historical_grades_for_year(
    student: Student, academic_year: AcademicYear, *, verified_only: bool = True
) -> bool:
    qs = HistoricalGradeRecord.objects.filter(student=student, academic_year=academic_year)
    if verified_only:
        qs = qs.filter(status=HistoricalGradeRecord.Status.VERIFIED)
    return qs.exists()


def student_has_enrollment_for_year(student: Student, academic_year: AcademicYear) -> bool:
    return Enrollment.objects.filter(student=student, academic_year=academic_year).exists()
