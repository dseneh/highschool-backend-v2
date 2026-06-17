"""Unified student academic-year timeline (enrollments + historical transcript grades)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from django.db.models import Count, Q

from academics.models import AcademicYear
from students.models import Enrollment, Student
from students.models.historical_grade import HistoricalGradeRecord


@dataclass
class StudentAcademicYearEntry:
    academic_year_id: str
    name: str
    year_type: str
    sort_year: int
    grade_level: Optional[dict]
    source: str  # enrollment | transferred | both
    has_enrollment: bool
    has_historical_grades: bool
    historical_grade_count: int
    verified_historical_count: int
    start_date: Optional[str]
    end_date: Optional[str]


class StudentGradeHistoryService:
    @classmethod
    def list_for_student(cls, student: Student) -> list[StudentAcademicYearEntry]:
        enrollments = (
            Enrollment.objects.filter(student=student)
            .select_related("academic_year", "grade_level")
            .order_by("academic_year__start_date", "academic_year__name")
        )

        historical_stats = (
            HistoricalGradeRecord.objects.filter(student=student)
            .values("academic_year_id")
            .annotate(
                total=Count("id"),
                verified=Count(
                    "id",
                    filter=Q(status=HistoricalGradeRecord.Status.VERIFIED),
                ),
            )
        )
        historical_by_year = {
            row["academic_year_id"]: row
            for row in historical_stats
            if row["academic_year_id"]
        }

        entries: dict[str, StudentAcademicYearEntry] = {}

        for enrollment in enrollments:
            ay = enrollment.academic_year
            if not ay:
                continue
            key = str(ay.id)
            grade_level = None
            if enrollment.grade_level:
                grade_level = {
                    "id": str(enrollment.grade_level_id),
                    "name": enrollment.grade_level.name,
                    "level": enrollment.grade_level.level,
                }
            hist = historical_by_year.get(key, {})
            entries[key] = StudentAcademicYearEntry(
                academic_year_id=key,
                name=ay.name or "",
                year_type=ay.year_type,
                sort_year=cls._sort_year(ay),
                grade_level=grade_level,
                source="enrollment",
                has_enrollment=True,
                has_historical_grades=bool(hist),
                historical_grade_count=hist.get("total", 0),
                verified_historical_count=hist.get("verified", 0),
                start_date=ay.start_date.isoformat() if ay.start_date else None,
                end_date=ay.end_date.isoformat() if ay.end_date else None,
            )

        for record in HistoricalGradeRecord.objects.filter(
            student=student, academic_year__isnull=True
        ):
            resolved = record.resolve_academic_year()
            if resolved:
                record.academic_year = resolved
                record.save(update_fields=["academic_year"])

        historical_records = HistoricalGradeRecord.objects.filter(
            student=student
        ).select_related("academic_year", "grade_level")

        historical_grouped: dict[str, dict] = {}
        for record in historical_records:
            ay = record.academic_year or record.resolve_academic_year()
            if not ay:
                continue
            key = str(ay.id)
            bucket = historical_grouped.setdefault(
                key,
                {
                    "academic_year": ay,
                    "grade_level": record.grade_level,
                    "total": 0,
                    "verified": 0,
                },
            )
            bucket["total"] += 1
            if record.status == HistoricalGradeRecord.Status.VERIFIED:
                bucket["verified"] += 1

        for key, bucket in historical_grouped.items():
            ay = bucket["academic_year"]
            if key in entries:
                entry = entries[key]
                entry.has_historical_grades = True
                entry.historical_grade_count = bucket["total"]
                entry.verified_historical_count = bucket["verified"]
                entry.source = "both" if entry.has_enrollment else "transferred"
                continue

            gl = bucket.get("grade_level")
            grade_level = None
            if gl:
                grade_level = {"id": str(gl.id), "name": gl.name, "level": gl.level}

            entries[key] = StudentAcademicYearEntry(
                academic_year_id=key,
                name=ay.name or "",
                year_type=ay.year_type,
                sort_year=cls._sort_year(ay),
                grade_level=grade_level,
                source="transferred",
                has_enrollment=False,
                has_historical_grades=True,
                historical_grade_count=bucket["total"],
                verified_historical_count=bucket["verified"],
                start_date=ay.start_date.isoformat() if ay.start_date else None,
                end_date=ay.end_date.isoformat() if ay.end_date else None,
            )

        return sorted(entries.values(), key=lambda e: (e.sort_year, e.name))

    @staticmethod
    def _sort_year(academic_year: AcademicYear) -> int:
        if academic_year.start_date:
            return academic_year.start_date.year
        match = re.search(r"(\d{4})", academic_year.name or "")
        return int(match.group(1)) if match else 0

    @classmethod
    def serialize_for_student(cls, student: Student) -> list[dict]:
        return [
            {
                "academic_year_id": entry.academic_year_id,
                "name": entry.name,
                "year_type": entry.year_type,
                "sort_year": entry.sort_year,
                "grade_level": entry.grade_level,
                "source": entry.source,
                "has_enrollment": entry.has_enrollment,
                "has_historical_grades": entry.has_historical_grades,
                "historical_grade_count": entry.historical_grade_count,
                "verified_historical_count": entry.verified_historical_count,
                "start_date": entry.start_date,
                "end_date": entry.end_date,
            }
            for entry in cls.list_for_student(student)
        ]
