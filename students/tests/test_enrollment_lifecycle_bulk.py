from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from common.status import EnrollmentStatus, YearEndOutcome
from students.services.enrollment_lifecycle import EnrollmentLifecycleError
from students.services.enrollment_lifecycle_bulk import (
    BULK_MAX_STUDENTS,
    CONFIRM_PHRASE,
    apply_bulk,
    check_eligibility,
    preview_bulk,
)

DEFAULT_RULES = {
    "allow_year_closure": True,
    "year_closure_min_overall_average": None,
    "year_closure_require_approved_grades": True,
    "allow_mid_year_promotion": False,
    "mid_year_promotion_min_overall_average": None,
}


class CheckEligibilityTests(SimpleTestCase):
    @patch("students.services.enrollment_lifecycle_bulk.get_promotion_rules")
    def test_complete_year_requires_enrolled(self, mock_rules):
        mock_rules.return_value = DEFAULT_RULES
        student = SimpleNamespace(id="s1")
        enrollment = SimpleNamespace(
            status=EnrollmentStatus.PENDING,
            grade_level=SimpleNamespace(level=1, division_id="d1"),
        )
        with patch(
            "students.services.enrollment_lifecycle_bulk.resolve_current_enrollment",
            return_value=enrollment,
        ):
            ok, reason, _avg = check_eligibility(
                student, "complete_year", outcome=YearEndOutcome.PROMOTED
            )
        self.assertFalse(ok)
        self.assertIn("Only enrolled", reason or "")


class PreviewBulkTests(SimpleTestCase):
    @patch("students.services.enrollment_lifecycle_bulk.get_promotion_rules")
    @patch("students.services.enrollment_lifecycle_bulk.build_candidate_queryset")
    def test_preview_counts_eligible(self, mock_build, mock_rules):
        mock_rules.return_value = DEFAULT_RULES
        student_ok = SimpleNamespace(
            id="1",
            id_number="ST001",
            grade_level=None,
            section=None,
        )
        student_ok.get_full_name = lambda: "Ada Lovelace"
        student_bad = SimpleNamespace(
            id="2",
            id_number="ST002",
            grade_level=None,
            section=None,
        )
        student_bad.get_full_name = lambda: "Bad Student"

        mock_qs = MagicMock()
        mock_qs.count.return_value = 2
        mock_qs.__getitem__ = lambda self, s: mock_qs
        mock_qs.__iter__ = lambda self: iter([student_ok, student_bad])
        mock_build.return_value = mock_qs

        def eligibility(student, action, outcome=None, rules=None):
            if student.id == "1":
                return True, None, 88.5
            return False, "Not enrolled", None

        with patch(
            "students.services.enrollment_lifecycle_bulk.check_eligibility",
            side_effect=eligibility,
        ), patch(
            "students.services.enrollment_lifecycle_bulk._enrollment_snapshot",
            return_value=("Grade 1", "A", EnrollmentStatus.ENROLLED),
        ):
            result = preview_bulk(
                action="graduate",
                selection_mode="filters",
                grade_level="gl-1",
                section="sec-1",
            )

        self.assertEqual(result["eligible_count"], 1)
        self.assertEqual(result["skipped_count"], 1)
        self.assertEqual(len(result["students"]), 2)


class ApplyBulkTests(SimpleTestCase):
    @patch("students.services.enrollment_lifecycle_bulk.preview_bulk")
    @patch("students.models.Student.objects")
    def test_apply_requires_confirm_phrase(self, mock_objects, mock_preview):
        mock_preview.return_value = {
            "truncated": False,
            "eligible_count": 1,
            "students": [{"id": "1", "eligible": True}],
        }

        with self.assertRaises(EnrollmentLifecycleError):
            apply_bulk(
                action="graduate",
                selection_mode="ids",
                student_ids=["ST001"],
                expected_eligible_count=1,
                confirm_phrase="WRONG",
            )

    @patch("students.services.enrollment_lifecycle_bulk.graduate_student")
    @patch("students.services.enrollment_lifecycle_bulk.preview_bulk")
    @patch("students.models.Student.objects")
    def test_apply_with_valid_confirmation(
        self, mock_objects, mock_preview, mock_graduate
    ):
        mock_preview.return_value = {
            "truncated": False,
            "eligible_count": 1,
            "students": [
                {
                    "id": "1",
                    "id_number": "ST001",
                    "eligible": True,
                    "full_name": "Ada",
                }
            ],
        }
        student = SimpleNamespace(
            id="1", id_number="ST001", get_full_name=lambda: "Ada"
        )
        mock_objects.filter.return_value = [student]

        result = apply_bulk(
            action="graduate",
            selection_mode="ids",
            student_ids=["ST001"],
            expected_eligible_count=1,
            confirm_phrase=CONFIRM_PHRASE,
        )

        self.assertEqual(result["applied_count"], 1)
        mock_graduate.assert_called_once()

    @patch("students.services.enrollment_lifecycle_bulk.close_enrollment_year")
    @patch("students.services.enrollment_lifecycle_bulk.preview_bulk")
    @patch("students.models.Student.objects")
    def test_apply_all_class_via_filters(
        self, mock_objects, mock_preview, mock_close_year
    ):
        mock_preview.return_value = {
            "truncated": False,
            "eligible_count": 2,
            "students": [
                {
                    "id": "1",
                    "id_number": "ST001",
                    "eligible": True,
                    "full_name": "Ada",
                    "projected_outcome": YearEndOutcome.PROMOTED,
                },
                {
                    "id": "2",
                    "id_number": "ST002",
                    "eligible": True,
                    "full_name": "Bob",
                    "projected_outcome": YearEndOutcome.REPEATED,
                },
            ],
        }
        students = [
            SimpleNamespace(id="1", id_number="ST001", get_full_name=lambda: "Ada"),
            SimpleNamespace(id="2", id_number="ST002", get_full_name=lambda: "Bob"),
        ]
        mock_objects.filter.return_value = students

        result = apply_bulk(
            action="complete_year",
            selection_mode="filters",
            grade_level="gl-1",
            section="sec-1",
            outcome="auto",
            expected_eligible_count=2,
            confirm_phrase=CONFIRM_PHRASE,
        )

        self.assertEqual(result["applied_count"], 2)
        self.assertEqual(mock_close_year.call_count, 2)
        mock_preview.assert_called_once()
        call_kwargs = mock_preview.call_args.kwargs
        self.assertEqual(call_kwargs["selection_mode"], "filters")
        self.assertEqual(call_kwargs["grade_level"], "gl-1")
        self.assertEqual(call_kwargs["section"], "sec-1")


class UndoPromotionTests(SimpleTestCase):
    @patch("students.services.enrollment_lifecycle_bulk.undo_year_end_promotion")
    @patch("students.services.enrollment_lifecycle_bulk.resolve_current_enrollment")
    @patch("students.models.Student.objects")
    def test_undo_year_end_promoted(
        self, mock_objects, mock_resolve, mock_undo
    ):
        student = SimpleNamespace(
            id="1",
            id_number="ST001",
            get_full_name=lambda: "Ada",
        )
        enrollment = SimpleNamespace(
            status=EnrollmentStatus.COMPLETED,
            year_end_outcome=YearEndOutcome.PROMOTED,
        )
        mock_objects.filter.return_value.distinct.return_value = [student]
        mock_resolve.return_value = enrollment

        from students.services.enrollment_lifecycle_bulk import undo_promotions

        result = undo_promotions(student_ids=["ST001"])

        self.assertEqual(result["undone_count"], 1)
        mock_undo.assert_called_once_with(student)


class AutoYearEndOutcomeTests(SimpleTestCase):
    @patch("students.services.enrollment_lifecycle_bulk.get_promotion_rules")
    @patch(
        "students.services.enrollment_lifecycle_bulk.get_student_overall_average",
        return_value=55.0,
    )
    @patch(
        "students.services.enrollment_lifecycle_bulk.resolve_current_enrollment",
    )
    def test_resolve_repeat_when_below_minimum(
        self, mock_resolve, _mock_avg, mock_rules
    ):
        mock_rules.return_value = {**DEFAULT_RULES, "year_closure_min_overall_average": 60.0}
        enrollment = SimpleNamespace(
            status=EnrollmentStatus.ENROLLED,
            grade_level=SimpleNamespace(level=2, division_id="d1"),
        )
        mock_resolve.return_value = enrollment
        student = SimpleNamespace(id="s1")

        from students.services.enrollment_lifecycle_bulk import (
            resolve_year_end_projected_outcome,
        )

        projected, average, reason = resolve_year_end_projected_outcome(student)
        self.assertEqual(projected, YearEndOutcome.REPEATED)
        self.assertEqual(average, 55.0)
        self.assertIsNone(reason)


class ListPromotedTests(SimpleTestCase):
    def test_list_requires_grade_and_section(self):
        from students.services.enrollment_lifecycle_bulk import list_promoted_students

        with self.assertRaises(EnrollmentLifecycleError):
            list_promoted_students(grade_level="", section="sec-1")
