from datetime import date

from django.test import TestCase

from academics.models import AcademicYear, GradeLevel, Section
from common.status import AttendanceStatus, EnrollmentStatus
from students.models import Attendance, Enrollment, Student
from students.services.daily_attendance_stats import (
    build_attendance_status_distribution,
    build_daily_attendance_stats,
)


class DailyAttendanceStatsTests(TestCase):
    def setUp(self):
        self.year = AcademicYear.objects.create(
            name="2025-2026",
            start_date=date(2025, 9, 1),
            end_date=date(2026, 6, 30),
            current=True,
        )
        self.grade = GradeLevel.objects.create(name="Grade 1", level=1)
        self.section = Section.objects.create(name="General A", grade_level=self.grade)

        self.student_male = Student.objects.create(
            first_name="John",
            last_name="Doe",
            gender="male",
            entry_as="new",
            school_code=1,
            student_seq=1,
        )
        self.student_female = Student.objects.create(
            first_name="Jane",
            last_name="Doe",
            gender="female",
            entry_as="new",
            school_code=1,
            student_seq=2,
        )

        self.enrollment_male = Enrollment.objects.create(
            student=self.student_male,
            section=self.section,
            academic_year=self.year,
            status=EnrollmentStatus.ENROLLED,
        )
        self.enrollment_female = Enrollment.objects.create(
            student=self.student_female,
            section=self.section,
            academic_year=self.year,
            status=EnrollmentStatus.ENROLLED,
        )

        self.target_date = date(2026, 6, 4)
        Attendance.objects.create(
            enrollment=self.enrollment_female,
            date=self.target_date,
            status=AttendanceStatus.LATE.value,
        )
        Attendance.objects.create(
            enrollment=self.enrollment_male,
            date=self.target_date,
            status=AttendanceStatus.ABSENT.value,
        )

    def test_build_daily_attendance_stats_by_gender(self):
        payload = build_daily_attendance_stats(
            academic_year=self.year,
            target_date=self.target_date,
        )

        self.assertEqual(len(payload["sections"]), 1)
        row = payload["sections"][0]
        self.assertEqual(row["total_students"]["male"], 1)
        self.assertEqual(row["total_students"]["female"], 1)
        self.assertEqual(row["total_students"]["total"], 2)
        self.assertEqual(row["present"]["total"], 0)
        self.assertEqual(row["tardy"]["female"], 1)
        self.assertEqual(row["absent"]["male"], 1)

        self.assertEqual(payload["totals"]["total_students"]["total"], 2)
        self.assertEqual(payload["percentages"]["present"]["total"], 0.0)
        self.assertEqual(payload["percentages"]["tardy"]["female"], 100.0)

    def test_build_attendance_status_distribution_defaults_to_present(self):
        payload = build_attendance_status_distribution(
            academic_year=self.year,
            target_date=self.target_date,
        )

        self.assertEqual(payload["present"]["count"], 0)
        self.assertEqual(payload["late"]["count"], 1)
        self.assertEqual(payload["absent"]["count"], 1)

        # Remove attendance records — both students should count as present.
        Attendance.objects.all().delete()
        payload = build_attendance_status_distribution(
            academic_year=self.year,
            target_date=self.target_date,
        )

        self.assertEqual(payload["present"]["count"], 2)
        self.assertEqual(payload["present"]["percentage"], 100.0)
        self.assertEqual(payload["absent"]["count"], 0)
        self.assertEqual(payload["late"]["count"], 0)
