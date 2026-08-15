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
    get_year_end_outcome_options,
    resolve_year_end_placement,
    transfer_out_student,
)
from students.services.student_status import compute_is_enrolled


class ResolveNextGradeLevelTests(SimpleTestCase):
    @patch(
        "students.services.enrollment_lifecycle.resolve_next_grade_level",
        side_effect=[None, None],
    )
    def test_highest_grade_only_allows_repeat_or_graduate(self, _mock_next_grade):
        grade = SimpleNamespace(id="g12", pk="g12", level=12, name="Grade 12")

        options = get_year_end_outcome_options(grade)

        self.assertEqual(
            [option["value"] for option in options],
            [YearEndOutcome.REPEATED, YearEndOutcome.GRADUATED],
        )
        self.assertEqual(options[0]["next_grade_level"], grade)
        self.assertIsNone(options[1]["next_grade_level"])

    @patch(
        "students.services.enrollment_lifecycle.resolve_next_grade_level",
        side_effect=[
            SimpleNamespace(id="g12", pk="g12", level=12, name="Grade 12"),
            None,
        ],
    )
    def test_second_highest_grade_allows_only_single_promotion(self, _mock_next_grade):
        grade = SimpleNamespace(id="g11", pk="g11", level=11, name="Grade 11")

        options = get_year_end_outcome_options(grade)

        self.assertEqual(
            [option["value"] for option in options],
            [
                YearEndOutcome.REPEATED,
                YearEndOutcome.GRADUATED,
                YearEndOutcome.PROMOTED,
            ],
        )
        self.assertEqual(options[-1]["next_grade_level"].name, "Grade 12")

    def test_repeat_returns_same_grade(self):
        grade = SimpleNamespace(id="g1", level=5, division_id="d1")
        result = resolve_next_grade_level(grade, YearEndOutcome.REPEATED)
        self.assertEqual(result, grade)

    @patch("students.services.enrollment_lifecycle.GradeLevel.objects")
    def test_promote_returns_next_configured_level(self, mock_objects):
        grade = SimpleNamespace(id="g1", level=5, division_id="d1")
        next_grade = SimpleNamespace(id="g2", level=6, division_id="d1")
        mock_objects.filter.return_value.order_by.return_value = [next_grade]

        result = resolve_next_grade_level(grade, YearEndOutcome.PROMOTED)
        self.assertEqual(result, next_grade)
        mock_objects.filter.assert_called_once_with(
            active=True,
            level__gt=5,
        )

    @patch("students.services.enrollment_lifecycle.GradeLevel.objects")
    def test_double_promotion_returns_second_configured_grade(self, mock_objects):
        grade = SimpleNamespace(id="g8", level=8)
        grade_nine = SimpleNamespace(id="g9", level=9)
        grade_ten = SimpleNamespace(id="g10", level=10)
        mock_objects.filter.return_value.order_by.return_value = [grade_nine, grade_ten]

        result = resolve_next_grade_level(grade, YearEndOutcome.DOUBLE_PROMOTED)

        self.assertEqual(result, grade_ten)

    @patch("students.services.enrollment_lifecycle.resolve_next_grade_level", return_value=None)
    def test_double_promotion_requires_two_higher_configured_grades(self, _mock_next_grade):
        grade = SimpleNamespace(id="g11", level=11)

        with self.assertRaisesRegex(
            EnrollmentLifecycleError,
            "Double promotion requires at least two higher configured grade levels",
        ):
            resolve_year_end_placement(grade, YearEndOutcome.DOUBLE_PROMOTED)

    @patch("students.services.enrollment_lifecycle.resolve_next_grade_level", return_value=None)
    def test_final_grade_promotion_becomes_graduation(self, _mock_next_grade):
        grade = SimpleNamespace(id="g12", level=12, division_id="d1")

        outcome, next_grade = resolve_year_end_placement(
            grade, YearEndOutcome.PROMOTED
        )

        self.assertEqual(outcome, YearEndOutcome.GRADUATED)
        self.assertIsNone(next_grade)

    @patch("students.services.enrollment_lifecycle.GradeLevel.objects")
    def test_promotion_allows_active_higher_grade_override(self, mock_objects):
        grade = SimpleNamespace(pk="g9", level=9)
        selected_next_grade = SimpleNamespace(pk="g11", level=11)
        mock_objects.filter.return_value.first.return_value = selected_next_grade

        outcome, next_grade = resolve_year_end_placement(
            grade,
            YearEndOutcome.PROMOTED,
            next_grade_level_id="g11",
        )

        self.assertEqual(outcome, YearEndOutcome.PROMOTED)
        self.assertEqual(next_grade, selected_next_grade)
        mock_objects.filter.assert_called_once_with(
            pk="g11",
            active=True,
            level__gt=9,
        )

    def test_repeat_rejects_different_next_grade_override(self):
        grade = SimpleNamespace(pk="g9", level=9)

        with self.assertRaises(EnrollmentLifecycleError):
            resolve_year_end_placement(
                grade,
                YearEndOutcome.REPEATED,
                next_grade_level_id="g10",
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
