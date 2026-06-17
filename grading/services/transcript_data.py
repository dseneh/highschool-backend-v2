"""Aggregate student academic history for official transcript PDF generation."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Optional
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from academics.models import AcademicYear, MarkingPeriod
from grading.models import GradeBook, GradeLetter, HonorCategory
from grading.services.ranking import RankingService
from grading.utils import (
    calculate_marking_period_percentage,
    calculate_student_overall_average,
    get_grading_settings,
    get_letter_grade,
)
from students.models import Enrollment, Student
from students.models.historical_grade import HistoricalGradeRecord
from students.services.student_lookup import get_student_by_identifier
from common.services.pdf_components import format_tenant_address, resolve_tenant_school
from hr.models import Employee
from settings.models import GradingSettings



def _parse_year_sort_key(label: str) -> int:
    match = re.search(r"(\d{4})", label or "")
    return int(match.group(1)) if match else 0


def _subject_final_percentage(
    student,
    gradebook,
    marking_periods: list[MarkingPeriod],
) -> Optional[float]:
    """Year-end subject grade from approved marking-period scores."""
    mp_percentages: dict = {}
    for mp in marking_periods:
        percentage = calculate_marking_period_percentage(
            gradebook, student, mp, status="approved"
        )
        if percentage is not None:
            mp_percentages[mp.id] = float(percentage)

    if not mp_percentages:
        return None

    settings = get_grading_settings()
    cumulative = True if settings is None else settings.cumulative_average_calculation

    if cumulative:
        values = list(mp_percentages.values())
        return round(sum(values) / len(values), 1)

    semesters: list = []
    seen_semester_ids: set = set()
    for mp in marking_periods:
        if mp.semester_id in seen_semester_ids:
            continue
        seen_semester_ids.add(mp.semester_id)
        semesters.append(mp.semester)

    if not semesters:
        return None

    semester_averages: list[float] = []
    for semester in semesters:
        sem_mps = [mp for mp in marking_periods if mp.semester_id == semester.id]
        sem_values = [mp_percentages[mp.id] for mp in sem_mps if mp.id in mp_percentages]
        if len(sem_values) != len(sem_mps) or not sem_values:
            return None
        semester_averages.append(sum(sem_values) / len(sem_values))

    return round(sum(semester_averages) / len(semester_averages), 1)


def _subject_transcript_percentage(
    student,
    gradebook,
    marking_periods: list[MarkingPeriod],
    *,
    allow_partial: bool = False,
) -> Optional[float]:
    """Subject percentage for transcript rows."""
    if allow_partial:
        pct = gradebook.final_percentage_for_student(student, status="approved")
        if pct is not None:
            return round(float(pct), 1)
        return None
    return _subject_final_percentage(student, gradebook, marking_periods)


def _historical_subject_final(
    records: list[HistoricalGradeRecord],
) -> tuple[Optional[float], Optional[str]]:
    """Resolve one final subject grade from prior-school records for a year."""
    if not records:
        return None, None

    full_year = [r for r in records if r.marking_period_id is None]
    if full_year:
        record = full_year[0]
        pct = float(record.final_percentage) if record.final_percentage is not None else None
        letter = record.final_letter or (get_letter_grade(pct) if pct is not None else None)
        return pct, letter

    mp_values = [
        float(r.final_percentage)
        for r in records
        if r.marking_period_id is not None and r.final_percentage is not None
    ]
    if mp_values:
        avg = round(sum(mp_values) / len(mp_values), 1)
        return avg, get_letter_grade(avg)

    for record in records:
        if record.final_letter:
            return None, record.final_letter
    return None, None


def _format_grade_display(
    percentage: Optional[float], letter: Optional[str] = None
) -> str:
    if percentage is not None:
        pct = float(percentage)
        resolved_letter = letter or get_letter_grade(pct)
        if resolved_letter and resolved_letter != "N/A":
            return f"{resolved_letter} ({pct:.1f}%)"
        return f"{pct:.1f}%"
    if letter:
        return letter
    return "-"


def _resolve_sort_end_date(
    explicit_end_date,
    academic_year,
) -> Optional[date]:
    if explicit_end_date:
        return explicit_end_date
    if academic_year and getattr(academic_year, "end_date", None):
        return academic_year.end_date
    return None


def _resolve_graduation_status(student: Student, enrollments: list[Enrollment]) -> str:
    if getattr(student, "date_of_graduation", None):
        return "Graduated"
    latest = enrollments[-1] if enrollments else None
    if latest and getattr(latest, "year_end_outcome", None):
        outcome = str(latest.year_end_outcome).replace("_", " ").title()
        if outcome.lower() == "graduated":
            return "Graduated"
        return outcome
    from students.services.student_status import compute_is_enrolled

    if compute_is_enrolled(student):
        return "On Track"
    return "In Progress"


@dataclass
class TranscriptGradeScaleEntry:
    letter: str
    min_percentage: float
    max_percentage: float


@dataclass
class TranscriptAcademicRow:
    institution_name: str
    academic_year_name: str
    grade_level_name: str
    marking_period: str
    marking_period_order: int
    subject_code: str
    subject_name: str
    grade_display: str
    percentage: Optional[float] = None
    letter: Optional[str] = None
    rank: Optional[str] = None
    sort_end_date: Optional[date] = None
    sort_grade_level: int = 0


@dataclass
class TranscriptYearBlock:
    institution_name: str
    academic_year_name: str
    grade_level_name: str
    sort_end_date: Optional[date] = None
    sort_grade_level: int = 0
    rows: list[TranscriptAcademicRow] = field(default_factory=list)
    year_average: Optional[float] = None
    year_average_letter: Optional[str] = None
    year_rank: Optional[str] = None


@dataclass
class TranscriptYearColumn:
    """Represents one academic year column in the pivoted transcript table."""
    academic_year_name: str
    grade_level_name: str
    sort_end_date: Optional[date] = None
    sort_grade_level: int = 0


@dataclass
class TranscriptSubjectRow:
    """Represents one subject row with grades across multiple years."""
    subject_code: str
    subject_name: str
    # Map: academic_year_name -> (percentage, letter)
    year_grades: dict[str, tuple[Optional[float], Optional[str]]] = field(default_factory=dict)
    final_average: Optional[float] = None
    final_average_letter: Optional[str] = None


@dataclass
class TranscriptPayload:
    school_name: str
    school_address: str
    school_phone: str
    school_website: str
    school_email: str
    emis_number: str
    transcript_id: str
    date_issued: str
    student_full_name: str
    student_id_number: str
    date_of_birth: Optional[str]
    grade_level: str
    graduation_year: Optional[str]
    date_enrolled: Optional[str]
    photo_path: Optional[str]
    cumulative_average: Optional[float]
    class_rank: Optional[str]
    percentile_rank: Optional[str]
    total_subjects: int
    graduation_status: str
    current_section: Optional[str]
    year_blocks: list[TranscriptYearBlock]
    grade_scale: list[TranscriptGradeScaleEntry]
    honors: list[str]
    signatory_name: str
    signatory_title: str
    secondary_signatory_name: str
    secondary_signatory_title: str
    disclaimer: str
    # New pivoted structure for subject-based table
    year_columns: list[TranscriptYearColumn] = field(default_factory=list)
    subject_rows: list[TranscriptSubjectRow] = field(default_factory=list)


class TranscriptDataService:
    """Build a structured payload for official transcript PDF rendering."""

    DISCLAIMER = (
        "This document is an official transcript only when signed by a school "
        "official and embossed with the school seal. It reflects approved "
        "grades recorded in the school's student information system."
    )

    @classmethod
    def build(cls, student: Student) -> TranscriptPayload:
        school = resolve_tenant_school(getattr(student, "school", None))
        now = timezone.now()
        tz = ZoneInfo(getattr(settings, "TIME_ZONE", "UTC"))
        local_now = now.astimezone(tz)

        enrollments = list(
            Enrollment.objects.filter(student=student)
            .select_related(
                "academic_year",
                "grade_level",
                "section",
                "section__grade_level",
            )
            .order_by("academic_year__start_date", "academic_year__name")
        )

        historical_records = list(
            HistoricalGradeRecord.objects.filter(
                student=student,
                status=HistoricalGradeRecord.Status.VERIFIED,
            )
            .select_related("grade_level", "subject", "marking_period", "academic_year")
            .order_by("period_end_date", "grade_level__level", "subject__name")
        )

        school_name = school.name if school else ""
        in_school_rows = cls._build_in_school_rows(enrollments, school_name=school_name)
        historical_rows = cls._build_historical_rows(historical_records)
        all_rows = sorted(
            in_school_rows + historical_rows,
            key=lambda r: (
                r.sort_end_date or date.min,
                r.sort_grade_level,
                r.institution_name,
                r.academic_year_name,
                r.marking_period_order,
                r.subject_name,
            ),
        )

        year_blocks = cls._group_into_year_blocks(all_rows)
        cls._attach_year_averages(year_blocks)
        cls._attach_year_ranks(student, enrollments, year_blocks)

        # Build pivoted subject-based structure (max last 3 years)
        year_columns, subject_rows = cls._pivot_to_subject_rows(year_blocks, max_years=3)

        cumulative_average = cls._compute_cumulative_average(enrollments, historical_records)
        class_rank, percentile_rank = cls._resolve_rank(student, enrollments)
        honors = cls._resolve_honors(student, enrollments, historical_records)
        grade_scale = cls._load_grade_scale()
        total_subjects = sum(len(block.rows) for block in year_blocks)
        graduation_status = _resolve_graduation_status(student, enrollments)

        first_enrollment = enrollments[0] if enrollments else None
        latest_enrollment = enrollments[-1] if enrollments else None
        grade_level = ""
        if latest_enrollment and latest_enrollment.grade_level:
            grade_level = latest_enrollment.grade_level.name
        elif student.grade_level:
            grade_level = student.grade_level.name

        current_section = None
        if latest_enrollment and latest_enrollment.section:
            current_section = latest_enrollment.section.name

        graduation_year = None
        if student.date_of_graduation:
            graduation_year = str(student.date_of_graduation.year)

        date_enrolled = None
        if student.entry_date:
            date_enrolled = student.entry_date.strftime("%b %d, %Y")
        elif first_enrollment and first_enrollment.academic_year:
            date_enrolled = first_enrollment.academic_year.start_date.strftime("%b %d, %Y")

        dob = None
        if getattr(student, "date_of_birth", None):
            dob = student.date_of_birth.strftime("%b %d, %Y")

        photo_path = None
        if getattr(student, "photo", None) and student.photo:
            try:
                photo_path = student.photo.path
            except Exception:
                photo_path = getattr(student.photo, "name", None)

        emis = ""
        if school and getattr(school, "emis_number", None):
            emis = str(school.emis_number)

        grading_settings = GradingSettings.objects.first()
        primary_role = (
            getattr(grading_settings, "transcript_primary_signatory_position", None)
            or "Principal"
        )
        secondary_role = (
            getattr(grading_settings, "transcript_secondary_signatory_position", None)
            or "Registrar"
        )
        signatory_name, signatory_title = cls._resolve_signatory_from_employee(primary_role)
        secondary_signatory_name, secondary_signatory_title = (
            cls._resolve_signatory_from_employee(secondary_role)
        )

        return TranscriptPayload(
            school_name=school.name if school else "",
            school_address=format_tenant_address(school),
            school_phone=(getattr(school, "phone", None) or "") if school else "",
            school_website=(getattr(school, "website", None) or "") if school else "",
            school_email=(getattr(school, "email", None) or "") if school else "",
            emis_number=emis,
            transcript_id=f"TRN-{local_now.year}-{student.id_number}",
            date_issued=local_now.strftime("%b %d, %Y"),
            student_full_name=student.get_full_name(),
            student_id_number=student.id_number,
            date_of_birth=dob,
            grade_level=grade_level,
            graduation_year=graduation_year,
            date_enrolled=date_enrolled,
            photo_path=photo_path,
            cumulative_average=cumulative_average,
            class_rank=class_rank,
            percentile_rank=percentile_rank,
            total_subjects=total_subjects,
            graduation_status=graduation_status,
            current_section=current_section,
            year_blocks=year_blocks,
            grade_scale=grade_scale,
            honors=honors,
            signatory_name=signatory_name,
            signatory_title=signatory_title,
            secondary_signatory_name=secondary_signatory_name,
            secondary_signatory_title=secondary_signatory_title,
            disclaimer=cls.DISCLAIMER,
            year_columns=year_columns,
            subject_rows=subject_rows,
        )

    @classmethod
    def build_for_student_id(cls, student_id: str) -> TranscriptPayload:
        student = get_student_by_identifier(student_id)
        return cls.build(student)

    @classmethod
    def _build_in_school_rows(
        cls,
        enrollments: list[Enrollment],
        *,
        school_name: str = "",
    ) -> list[TranscriptAcademicRow]:
        rows: list[TranscriptAcademicRow] = []

        for enrollment in enrollments:
            academic_year = enrollment.academic_year
            if not academic_year:
                continue

            grade_name = enrollment.grade_level.name if enrollment.grade_level else ""
            grade_level_num = enrollment.grade_level.level if enrollment.grade_level else 0
            year_name = academic_year.name or ""
            sort_end_date = _resolve_sort_end_date(None, academic_year)
            is_current_year = bool(getattr(academic_year, "current", False))

            if not enrollment.section_id:
                continue

            marking_periods = list(
                MarkingPeriod.objects.filter(
                    semester__academic_year=academic_year,
                    active=True,
                )
                .select_related("semester")
                .order_by("semester__start_date", "start_date")
            )

            gradebooks = list(
                GradeBook.objects.filter(
                    section_id=enrollment.section_id,
                    academic_year=academic_year,
                    active=True,
                )
                .select_related("subject")
                .order_by("subject__name")
            )

            for gradebook in gradebooks:
                subject = gradebook.subject
                subject_code = (subject.code or "-") if subject else "-"
                subject_name = subject.name if subject else "Unknown Subject"

                final_pct = _subject_transcript_percentage(
                    enrollment.student,
                    gradebook,
                    marking_periods,
                    allow_partial=is_current_year,
                )
                if final_pct is None:
                    continue

                letter = get_letter_grade(final_pct)
                marking_period_label = "YTD" if is_current_year else "Final"
                rows.append(
                    TranscriptAcademicRow(
                        institution_name=school_name or "-",
                        academic_year_name=year_name,
                        grade_level_name=grade_name,
                        marking_period=marking_period_label,
                        marking_period_order=0,
                        subject_code=subject_code,
                        subject_name=subject_name,
                        grade_display=_format_grade_display(final_pct, letter),
                        percentage=final_pct,
                        letter=letter,
                        sort_end_date=sort_end_date,
                        sort_grade_level=grade_level_num,
                    )
                )

        return rows

    @classmethod
    def _build_historical_rows(
        cls, historical_records: list[HistoricalGradeRecord]
    ) -> list[TranscriptAcademicRow]:
        """Historical transcript grades - one final row per institution/year/subject."""
        rows: list[TranscriptAcademicRow] = []
        grouped: dict[tuple, list[HistoricalGradeRecord]] = {}

        for record in historical_records:
            academic_year = record.academic_year or record.resolve_academic_year()
            year_label = (
                academic_year.name
                if academic_year
                else record.academic_year_label
            )
            key = (
                record.institution_name,
                str(academic_year.id) if academic_year else year_label,
                record.grade_level_id,
                str(record.subject_id or record.subject_name),
            )
            grouped.setdefault(key, []).append(record)

        for records in grouped.values():
            record = records[0]
            academic_year = record.academic_year or record.resolve_academic_year()
            grade_name = record.grade_level.name if record.grade_level else ""
            grade_level_num = record.grade_level.level if record.grade_level else 0
            year_name = (
                academic_year.name
                if academic_year
                else record.academic_year_label
            )

            pct, letter = _historical_subject_final(records)
            if pct is None and not letter:
                continue

            subject_code = record.subject.code if record.subject and record.subject.code else "-"
            sort_end_date = _resolve_sort_end_date(record.period_end_date, academic_year)

            rows.append(
                TranscriptAcademicRow(
                    institution_name=record.institution_name,
                    academic_year_name=year_name,
                    grade_level_name=grade_name,
                    marking_period="Final",
                    marking_period_order=0,
                    subject_code=subject_code,
                    subject_name=record.subject_name,
                    grade_display=_format_grade_display(pct, letter),
                    percentage=pct,
                    letter=letter,
                    sort_end_date=sort_end_date,
                    sort_grade_level=grade_level_num,
                )
            )

        return rows

    @classmethod
    def _group_into_year_blocks(
        cls, rows: list[TranscriptAcademicRow]
    ) -> list[TranscriptYearBlock]:
        block_map: dict[tuple, TranscriptYearBlock] = {}
        block_order: list[tuple] = []

        for row in rows:
            key = (row.institution_name, row.academic_year_name, row.grade_level_name)
            if key not in block_map:
                block_map[key] = TranscriptYearBlock(
                    institution_name=row.institution_name,
                    academic_year_name=row.academic_year_name,
                    grade_level_name=row.grade_level_name,
                    sort_end_date=row.sort_end_date,
                    sort_grade_level=row.sort_grade_level,
                )
                block_order.append(key)
            block = block_map[key]
            block.rows.append(row)
            if row.sort_end_date and (
                block.sort_end_date is None or row.sort_end_date > block.sort_end_date
            ):
                block.sort_end_date = row.sort_end_date

        blocks = [block_map[key] for key in block_order]
        blocks.sort(
            key=lambda block: (
                block.sort_end_date or date.min,
                block.sort_grade_level,
                block.academic_year_name,
                block.institution_name,
            )
        )
        return blocks

    @classmethod
    def _attach_year_averages(cls, blocks: list[TranscriptYearBlock]) -> None:
        for block in blocks:
            final_values = [
                row.percentage
                for row in block.rows
                if row.percentage is not None
                and row.marking_period in {"Final", "YTD"}
            ]
            if final_values:
                block.year_average = round(sum(final_values) / len(final_values), 1)
                block.year_average_letter = get_letter_grade(block.year_average)

    @classmethod
    def _attach_year_ranks(
        cls,
        student: Student,
        enrollments: list[Enrollment],
        blocks: list[TranscriptYearBlock],
    ) -> None:
        enrollment_by_year_grade = {
            (e.academic_year.name if e.academic_year else "", e.grade_level.name if e.grade_level else ""): e
            for e in enrollments
            if e.academic_year and e.grade_level
        }

        for block in blocks:
            enrollment = enrollment_by_year_grade.get(
                (block.academic_year_name, block.grade_level_name)
            )
            if not enrollment or not enrollment.section_id or not enrollment.academic_year_id:
                continue
            rankings = RankingService.get_report_card_rankings(
                str(student.id),
                str(enrollment.academic_year_id),
                str(enrollment.section_id),
            )
            final_rank = rankings.get("final", {}).get(str(student.id))
            if final_rank:
                block.year_rank = final_rank.get("label")
                for row in block.rows:
                    if not row.rank:
                        row.rank = block.year_rank

    @classmethod
    def _pivot_to_subject_rows(
        cls,
        year_blocks: list[TranscriptYearBlock],
        *,
        max_years: int = 3,
    ) -> tuple[list[TranscriptYearColumn], list[TranscriptSubjectRow]]:
        """
        Pivot year_blocks into a subject-based view with columns for academic years.
        Returns (year_columns, subject_rows).
        """
        if not year_blocks:
            return [], []

        # Take last N years
        recent_blocks = year_blocks[-max_years:] if len(year_blocks) > max_years else year_blocks

        # Build year columns
        year_columns = [
            TranscriptYearColumn(
                academic_year_name=block.academic_year_name,
                grade_level_name=block.grade_level_name,
                sort_end_date=block.sort_end_date,
                sort_grade_level=block.sort_grade_level,
            )
            for block in recent_blocks
        ]

        # Collect all unique subjects across these years
        subject_map: dict[tuple[str, str], TranscriptSubjectRow] = {}

        for block in recent_blocks:
            for row in block.rows:
                key = (row.subject_code, row.subject_name)
                if key not in subject_map:
                    subject_map[key] = TranscriptSubjectRow(
                        subject_code=row.subject_code,
                        subject_name=row.subject_name,
                    )
                subject_row = subject_map[key]
                subject_row.year_grades[block.academic_year_name] = (
                    row.percentage,
                    row.letter,
                )

        # Calculate final average for each subject across all years
        for subject_row in subject_map.values():
            percentages = [
                pct
                for pct, _ in subject_row.year_grades.values()
                if pct is not None
            ]
            if percentages:
                subject_row.final_average = round(sum(percentages) / len(percentages), 1)
                subject_row.final_average_letter = get_letter_grade(subject_row.final_average)

        # Sort subjects alphabetically by subject name
        subject_rows = sorted(subject_map.values(), key=lambda s: s.subject_name)

        return year_columns, subject_rows

    @classmethod
    def _compute_cumulative_average(
        cls,
        enrollments: list[Enrollment],
        historical_records: list[HistoricalGradeRecord],
    ) -> Optional[float]:
        year_averages: list[float] = []

        gradebook_cache: dict[tuple, list] = {}
        for enrollment in enrollments:
            if not enrollment.section_id or not enrollment.academic_year:
                continue
            cache_key = (str(enrollment.section_id), str(enrollment.academic_year_id))
            if cache_key not in gradebook_cache:
                gradebook_cache[cache_key] = list(
                    GradeBook.objects.filter(
                        section_id=enrollment.section_id,
                        academic_year=enrollment.academic_year,
                        active=True,
                    )
                )
            avg_data = calculate_student_overall_average(
                enrollment.student,
                enrollment.academic_year,
                gradebooks=gradebook_cache[cache_key],
                status="approved",
            )
            if avg_data.get("final_average") is not None:
                year_averages.append(float(avg_data["final_average"]))

        enrolled_years = {
            e.academic_year.name for e in enrollments if e.academic_year and e.academic_year.name
        }
        historical_rows = cls._build_historical_rows(
            [
                record
                for record in historical_records
                if record.academic_year_label not in enrolled_years
            ]
        )
        historical_by_year: dict[str, list[float]] = {}
        for row in historical_rows:
            if row.percentage is None:
                continue
            historical_by_year.setdefault(row.academic_year_name, []).append(row.percentage)

        for values in historical_by_year.values():
            if values:
                year_averages.append(sum(values) / len(values))

        if not year_averages:
            return None
        return round(sum(year_averages) / len(year_averages), 1)

    @classmethod
    def _resolve_rank(
        cls, student: Student, enrollments: list[Enrollment]
    ) -> tuple[Optional[str], Optional[str]]:
        for enrollment in reversed(enrollments):
            if not enrollment.section_id or not enrollment.academic_year_id:
                continue
            rankings = RankingService.get_report_card_rankings(
                str(student.id),
                str(enrollment.academic_year_id),
                str(enrollment.section_id),
            )
            final_rank = rankings.get("final", {}).get(str(student.id))
            if final_rank:
                rank_label = final_rank.get("label")
                percentile = final_rank.get("percentile")
                percentile_label = (
                    f"{int(round(percentile))}th Percentile" if percentile is not None else None
                )
                return rank_label, percentile_label
        return None, None

    @classmethod
    def _resolve_honors(
        cls,
        student: Student,
        enrollments: list[Enrollment],
        historical_records: list[HistoricalGradeRecord],
    ) -> list[str]:
        categories = list(HonorCategory.objects.all().order_by("-min_average"))
        if not categories:
            return []

        honors: list[str] = []
        seen: set[str] = set()
        gradebook_cache: dict[tuple, list] = {}

        for enrollment in enrollments:
            if not enrollment.academic_year:
                continue
            cache_key = (str(enrollment.section_id), str(enrollment.academic_year_id))
            if cache_key not in gradebook_cache:
                gradebook_cache[cache_key] = list(
                    GradeBook.objects.filter(
                        section_id=enrollment.section_id,
                        academic_year=enrollment.academic_year,
                        active=True,
                    )
                ) if enrollment.section_id else []

            avg_data = calculate_student_overall_average(
                student,
                enrollment.academic_year,
                gradebooks=gradebook_cache[cache_key],
                status="approved",
            )
            final_avg = avg_data.get("final_average")
            if final_avg is None:
                continue

            label = cls._match_honor_category(categories, float(final_avg))
            if label:
                entry = f"{label} - {enrollment.academic_year.name}"
                if entry not in seen:
                    seen.add(entry)
                    honors.append(entry)

        historical_rows = cls._build_historical_rows(historical_records)
        historical_by_year: dict[str, list[float]] = {}
        for row in historical_rows:
            if row.percentage is None:
                continue
            year_key = row.academic_year_name
            historical_by_year.setdefault(year_key, []).append(row.percentage)

        for year_label, values in historical_by_year.items():
            if not values:
                continue
            avg = sum(values) / len(values)
            label = cls._match_honor_category(categories, avg)
            if label:
                entry = f"{label} - {year_label}"
                if entry not in seen:
                    seen.add(entry)
                    honors.append(entry)

        return honors

    @staticmethod
    def _resolve_signatory_from_employee(role_title: str) -> tuple[str, str]:
        """Resolve signatory name/title from active employees by position/job title."""
        normalized_role = (role_title or "").strip() or "School Official"
        employees = Employee.objects.filter(active=True)

        # Prefer exact role matches first.
        match = (
            employees.filter(
                Q(position__title__iexact=normalized_role)
                | Q(job_title__iexact=normalized_role)
            )
            .select_related("position")
            .order_by("last_name", "first_name")
            .first()
        )
        if not match:
            # Then fallback to partial matches.
            match = (
                employees.filter(
                    Q(position__title__icontains=normalized_role)
                    | Q(job_title__icontains=normalized_role)
                )
                .select_related("position")
                .order_by("last_name", "first_name")
                .first()
            )

        if not match:
            return normalized_role, normalized_role

        title = (
            (match.position.title if getattr(match, "position", None) else None)
            or match.job_title
            or normalized_role
        )
        return match.get_full_name(), title

    @staticmethod
    def _match_honor_category(categories, average: float) -> Optional[str]:
        for category in categories:
            if float(category.min_average) <= average <= float(category.max_average):
                return category.label
        return None

    @staticmethod
    def _load_grade_scale() -> list[TranscriptGradeScaleEntry]:
        return [
            TranscriptGradeScaleEntry(
                letter=gl.letter,
                min_percentage=float(gl.min_percentage),
                max_percentage=float(gl.max_percentage),
            )
            for gl in GradeLetter.objects.all().order_by("order")
        ]
