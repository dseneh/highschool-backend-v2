"""Aggregate daily attendance counts by section and gender."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Iterable

from academics.services.school_days import iter_instructional_days
from common.status import AttendanceStatus, EnrollmentStatus, StudentStatus
from students.models import Attendance, Enrollment


@dataclass
class GenderCounts:
    male: int = 0
    female: int = 0
    other: int = 0

    @property
    def total(self) -> int:
        return self.male + self.female + self.other

    def to_dict(self) -> dict[str, int]:
        return {
            "male": self.male,
            "female": self.female,
            "total": self.total,
        }

    def add(self, gender_bucket: str) -> None:
        if gender_bucket == "male":
            self.male += 1
        elif gender_bucket == "female":
            self.female += 1
        else:
            self.other += 1


@dataclass
class SectionAttendanceStatsRow:
    section_id: str
    class_label: str
    grade_level: str
    section_name: str
    total_students: GenderCounts = field(default_factory=GenderCounts)
    present: GenderCounts = field(default_factory=GenderCounts)
    tardy: GenderCounts = field(default_factory=GenderCounts)
    absent: GenderCounts = field(default_factory=GenderCounts)

    def to_dict(self) -> dict:
        return {
            "section_id": self.section_id,
            "class_label": self.class_label,
            "grade_level": self.grade_level,
            "section_name": self.section_name,
            "total_students": self.total_students.to_dict(),
            "present": self.present.to_dict(),
            "tardy": self.tardy.to_dict(),
            "absent": self.absent.to_dict(),
        }


def _gender_bucket(gender: str | None) -> str:
    normalized = (gender or "").strip().lower()
    if normalized == "male":
        return "male"
    if normalized == "female":
        return "female"
    return "other"


def _attendance_bucket(status: str) -> str:
    if status == AttendanceStatus.PRESENT.value:
        return "present"
    if status == AttendanceStatus.LATE.value:
        return "tardy"
    return "absent"


def _normalize_attendance_status(status) -> str:
    if not status:
        return AttendanceStatus.PRESENT.value
    return str(status).strip().lower()


def _dashboard_distribution_bucket(status: str) -> str:
    """Bucket for dashboard pie chart (present / late / absent / excused)."""
    normalized = _normalize_attendance_status(status)
    if normalized == AttendanceStatus.PRESENT.value:
        return "present"
    if normalized == AttendanceStatus.LATE.value:
        return "late"
    if normalized == AttendanceStatus.ABSENT.value:
        return "absent"
    return "excused"


def _enrollments_for_attendance_snapshot(academic_year):
    """Match dashboard student summary enrollment rules."""
    return (
        Enrollment.objects.filter(academic_year=academic_year)
        .exclude(status__in=[EnrollmentStatus.CANCELED, EnrollmentStatus.WITHDRAWN])
        .exclude(
            student__status__in=[
                StudentStatus.WITHDRAWN,
                StudentStatus.GRADUATED,
                StudentStatus.TRANSFERRED,
                StudentStatus.DELETED,
            ]
        )
        .select_related("student", "section", "section__grade_level")
    )


def build_attendance_status_distribution(
    *,
    academic_year,
    target_date: date,
) -> dict[str, dict[str, int]]:
    """
    School-wide status counts for one date.

    Enrollments without a saved row count as present (implicit default).
    """
    enrollments = list(
        _enrollments_for_attendance_snapshot(academic_year).order_by(
            "section__grade_level__level",
            "section__name",
            "student__last_name",
        )
    )
    enrollment_ids = [enrollment.id for enrollment in enrollments]

    attendance_map = {
        str(row.enrollment_id): _normalize_attendance_status(row.status)
        for row in Attendance.objects.filter(enrollment_id__in=enrollment_ids, date=target_date)
    }

    counts = {label: 0 for label in ("present", "absent", "late", "excused")}

    for enrollment in enrollments:
        status = attendance_map.get(
            str(enrollment.id),
            AttendanceStatus.PRESENT.value,
        )
        counts[_dashboard_distribution_bucket(status)] += 1

    total = sum(counts.values())
    return {
        label: {
            "count": count,
            "percentage": _pct(count, total),
        }
        for label, count in counts.items()
    }


def _pct(numerator: int, denominator: int) -> int:
    if denominator <= 0:
        return 0
    return int(round((numerator / denominator) * 100))


def _coerce_attendance_date(value) -> date | None:
    if isinstance(value, date):
        return value
    if value is None:
        return None
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        return None


def _iter_weekday_dates(start: date, end: date) -> list[date]:
    """Mon–Fri dates when the school calendar yields no instructional days."""
    dates: list[date] = []
    current = start
    while current <= end:
        if current.isoweekday() <= 5:
            dates.append(current)
        current += timedelta(days=1)
    return dates


def _resolve_trend_dates(
    *,
    academic_year,
    end_date: date,
    school_days: int,
) -> list[date]:
    period_end = min(end_date, academic_year.end_date)
    period_start = academic_year.start_date
    if period_start > period_end:
        return []

    instructional = list(iter_instructional_days(period_start, period_end))
    if instructional:
        return instructional[-school_days:]

    weekdays = _iter_weekday_dates(period_start, period_end)
    return weekdays[-school_days:]


def build_attendance_trend(
    *,
    academic_year,
    end_date: date,
    school_days: int = 30,
) -> list[dict]:
    """
    Daily present / absent / late counts for dashboard line chart.

    Unmarked enrollments count as present (same as ``build_attendance_status_distribution``).
    """
    if not academic_year or school_days <= 0:
        return []

    target_dates = _resolve_trend_dates(
        academic_year=academic_year,
        end_date=end_date,
        school_days=school_days,
    )
    if not target_dates:
        return []

    enrollments = list(_enrollments_for_attendance_snapshot(academic_year))
    enrollment_ids = [enrollment.id for enrollment in enrollments]
    if not enrollment_ids:
        return []

    range_start = target_dates[0]
    range_end = target_dates[-1]

    attendance_by_date: dict[date, dict[str, str]] = defaultdict(dict)
    for row in Attendance.objects.filter(
        enrollment_id__in=enrollment_ids,
        date__gte=range_start,
        date__lte=range_end,
    ).values("enrollment_id", "date", "status"):
        row_date = _coerce_attendance_date(row["date"])
        if row_date is None:
            continue
        attendance_by_date[row_date][str(row["enrollment_id"])] = _normalize_attendance_status(
            row["status"]
        )

    series: list[dict] = []
    for target_date in target_dates:
        day_map = attendance_by_date.get(target_date, {})
        counts = {label: 0 for label in ("present", "absent", "late", "excused")}
        for enrollment in enrollments:
            status = day_map.get(
                str(enrollment.id),
                AttendanceStatus.PRESENT.value,
            )
            bucket = _dashboard_distribution_bucket(status)
            counts[bucket] += 1

        total = sum(counts.values())
        series.append(
            {
                "date": target_date.isoformat(),
                "label": target_date.strftime("%b %d"),
                "total": total,
                "present": counts["present"],
                "absent": counts["absent"],
                "late": counts["late"],
            }
        )

    return series


def build_percentage_summary(
    totals: GenderCounts,
    present: GenderCounts,
    tardy: GenderCounts,
    absent: GenderCounts,
) -> dict[str, dict[str, int | float]]:
    return {
        "present": {
            "male": _pct(present.male, totals.male),
            "female": _pct(present.female, totals.female),
            "total": _pct(present.total, totals.total),
        },
        "tardy": {
            "male": _pct(tardy.male, totals.male),
            "female": _pct(tardy.female, totals.female),
            "total": _pct(tardy.total, totals.total),
        },
        "absent": {
            "male": _pct(absent.male, totals.male),
            "female": _pct(absent.female, totals.female),
            "total": _pct(absent.total, totals.total),
        },
    }


def _active_enrollments_queryset(academic_year, grade_level_ids: list[str], section_ids: list[str]):
    enrollments = _enrollments_for_attendance_snapshot(academic_year)
    if grade_level_ids:
        enrollments = enrollments.filter(section__grade_level_id__in=grade_level_ids)
    if section_ids:
        enrollments = enrollments.filter(section_id__in=section_ids)
    return enrollments.order_by("section__grade_level__level", "section__name", "student__last_name")


def _skip_student(student) -> bool:
    return student.status in (
        StudentStatus.WITHDRAWN,
        StudentStatus.GRADUATED,
        StudentStatus.TRANSFERRED,
        StudentStatus.DELETED,
    )


def build_daily_attendance_stats(
    *,
    academic_year,
    target_date: date,
    grade_level_ids: Iterable[str] | None = None,
    section_ids: Iterable[str] | None = None,
) -> dict:
    grade_ids = list(grade_level_ids or [])
    section_id_list = list(section_ids or [])

    enrollments = list(_active_enrollments_queryset(academic_year, grade_ids, section_id_list))
    enrollment_ids = [enrollment.id for enrollment in enrollments]

    attendance_map = {
        str(row.enrollment_id): row.status
        for row in Attendance.objects.filter(enrollment_id__in=enrollment_ids, date=target_date)
    }

    rows_by_section: dict[str, SectionAttendanceStatsRow] = {}
    section_order: list[str] = []

    for enrollment in enrollments:
        if _skip_student(enrollment.student):
            continue

        section = enrollment.section
        if not section:
            continue

        section_key = str(section.id)
        if section_key not in rows_by_section:
            rows_by_section[section_key] = SectionAttendanceStatsRow(
                section_id=section_key,
                class_label=section.section_class,
                grade_level=section.grade_level.name if section.grade_level else "",
                section_name=section.name,
            )
            section_order.append(section_key)

        row = rows_by_section[section_key]
        gender = _gender_bucket(getattr(enrollment.student, "gender", None))
        # No row for this date means the student is present (implicit default).
        status = attendance_map.get(str(enrollment.id), AttendanceStatus.PRESENT.value)
        bucket = _attendance_bucket(status)

        row.total_students.add(gender)
        if bucket == "present":
            row.present.add(gender)
        elif bucket == "tardy":
            row.tardy.add(gender)
        else:
            row.absent.add(gender)

    section_rows = [rows_by_section[key] for key in section_order]

    totals = GenderCounts()
    present_totals = GenderCounts()
    tardy_totals = GenderCounts()
    absent_totals = GenderCounts()

    for row in section_rows:
        for bucket, target in (
            (row.total_students, totals),
            (row.present, present_totals),
            (row.tardy, tardy_totals),
            (row.absent, absent_totals),
        ):
            target.male += bucket.male
            target.female += bucket.female
            target.other += bucket.other

    return {
        "date": target_date.isoformat(),
        "academic_year_id": str(academic_year.id),
        "percentages": build_percentage_summary(totals, present_totals, tardy_totals, absent_totals),
        "sections": [row.to_dict() for row in section_rows],
        "totals": {
            "total_students": totals.to_dict(),
            "present": present_totals.to_dict(),
            "tardy": tardy_totals.to_dict(),
            "absent": absent_totals.to_dict(),
        },
    }
