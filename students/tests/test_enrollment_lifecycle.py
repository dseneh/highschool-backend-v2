from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from common.status import EnrollmentStatus, StudentStatus, YearEndOutcome
from students.services.enrollment_lifecycle import (
    EnrollmentLifecycleError,
    close_enrollment_year,
    graduate_student,
    resolve_next_grade_level,
    transfer_out_student,
)
from students.services.student_status import compute_is_enrolled


class ResolveNextGradeLevelTests(SimpleTestCase):
    def test_repeat_returns_same_grade(self):
        grade = SimpleNamespace(id="g1", level=5, division_id="d1")
        result = resolve_next_grade_level(grade, YearEndOutcome.REPEATED)
        self.assertEqual(result, grade)

    @patch("students.services.enrollment_lifecycle.GradeLevel.objects")
    def test_promote_returns_next_level_in_division(self, mock_objects):
        grade = SimpleNamespace(id="g1", level=5, division_id="d1")
        next_grade = SimpleNamespace(id="g2", level=6, division_id="d1")
        mock_objects.filter.return_value.order_by.return_value.first.return_value = (
            next_grade
        )

        result = resolve_next_grade_level(grade, YearEndOutcome.PROMOTED)
        self.assertEqual(result, next_grade)
        mock_objects.filter.assert_called_once_with(
            active=True,
            division_id="d1",
            level=6,
        )


class CloseEnrollmentYearTests(SimpleTestCase):
    @patch("students.services.enrollment_lifecycle.resolve_current_enrollment")
    def test_promote_closes_year_and_sets_next_grade(self, mock_resolve):
        grade = SimpleNamespace(id="g1", level=1, division_id="d1")
        next_grade = SimpleNamespace(id="g2", level=2, division_id="d1")
        enrollment = SimpleNamespace(
            status=EnrollmentStatus.ENROLLED,
            grade_level=grade,
            save=MagicMock(),
        )
        student = SimpleNamespace(status=StudentStatus.ACTIVE, save=MagicMock())
        mock_resolve.return_value = enrollment

        with patch(
            "students.services.enrollment_lifecycle.resolve_next_grade_level",
            return_value=next_grade,
        ):
            result = close_enrollment_year(student, YearEndOutcome.PROMOTED)

        self.assertEqual(result.status, EnrollmentStatus.COMPLETED)
        self.assertEqual(result.year_end_outcome, YearEndOutcome.PROMOTED)
        self.assertEqual(result.next_grade_level, next_grade)
        enrollment.save.assert_called_once()
        self.assertFalse(
            compute_is_enrolled(student, current_enrollment=enrollment)
        )

    @patch("students.services.enrollment_lifecycle.resolve_current_enrollment")
    def test_requires_enrolled_status(self, mock_resolve):
        enrollment = SimpleNamespace(status=EnrollmentStatus.COMPLETED)
        student = SimpleNamespace(status=StudentStatus.ACTIVE, save=MagicMock())
        mock_resolve.return_value = enrollment

        with self.assertRaises(EnrollmentLifecycleError):
            close_enrollment_year(student, YearEndOutcome.PROMOTED)


class GraduateStudentTests(SimpleTestCase):
    @patch("students.services.enrollment_lifecycle.resolve_current_enrollment")
    def test_graduate_sets_lifecycle_and_closes_enrollment(self, mock_resolve):
        enrollment = SimpleNamespace(
            status=EnrollmentStatus.ENROLLED,
            grade_level=SimpleNamespace(id="g1", level=12, division_id="d1"),
            save=MagicMock(),
        )
        student = SimpleNamespace(
            status=StudentStatus.ACTIVE,
            date_of_graduation=None,
            save=MagicMock(),
        )
        mock_resolve.return_value = enrollment

        graduate_student(
            student,
            graduation_date=date(2026, 6, 1),
        )

        self.assertEqual(student.status, StudentStatus.GRADUATED)
        self.assertEqual(student.date_of_graduation, date(2026, 6, 1))
        self.assertEqual(enrollment.status, EnrollmentStatus.COMPLETED)
        self.assertEqual(enrollment.year_end_outcome, YearEndOutcome.GRADUATED)
        self.assertIsNone(enrollment.next_grade_level)


class TransferOutTests(SimpleTestCase):
    @patch("students.services.enrollment_lifecycle.resolve_current_enrollment")
    def test_transfer_out_updates_student_and_enrollment(self, mock_resolve):
        enrollment = SimpleNamespace(
            status=EnrollmentStatus.ENROLLED,
            save=MagicMock(),
        )
        student = SimpleNamespace(
            status=StudentStatus.ACTIVE,
            withdrawal_date=None,
            withdrawal_reason=None,
            save=MagicMock(),
        )
        mock_resolve.return_value = enrollment

        transfer_out_student(
            student,
            transfer_date=date(2026, 3, 1),
            reason="Moved abroad",
        )

        self.assertEqual(student.status, StudentStatus.TRANSFERRED)
        self.assertEqual(enrollment.status, EnrollmentStatus.WITHDRAWN)
        self.assertEqual(enrollment.year_end_outcome, YearEndOutcome.TRANSFERRED)
        self.assertIsNone(enrollment.next_grade_level)
