from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import TestCase
from rest_framework.exceptions import PermissionDenied

from grading.services.authorization import (
    GRADE_ASSIGNMENT_DENIED_MESSAGE,
    enforce_teacher_grade_access,
)
from grading.views.grade import GradeDetailView


class GradeAssignmentAccessTests(TestCase):
    def setUp(self):
        self.user = SimpleNamespace(is_authenticated=True)
        self.grade = Mock(
            section_id="section-1",
            subject_id="subject-1",
            status="draft",
            assessment=SimpleNamespace(max_score=100),
        )
        self.request = SimpleNamespace(
            user=self.user,
            data={"score": "85", "condition_status": "graded"},
        )

    @patch("grading.services.authorization.get_teacher_allowed_section_ids_for_subject")
    def test_assigned_teacher_is_allowed(self, mock_allowed_sections):
        mock_allowed_sections.return_value = {"section-1"}

        enforce_teacher_grade_access(self.user, "section-1", "subject-1")

    @patch("grading.services.authorization.get_teacher_allowed_section_ids_for_subject")
    def test_unassigned_teacher_is_denied(self, mock_allowed_sections):
        mock_allowed_sections.return_value = {"section-2"}

        with self.assertRaisesMessage(PermissionDenied, GRADE_ASSIGNMENT_DENIED_MESSAGE):
            enforce_teacher_grade_access(self.user, "section-1", "subject-1")

    @patch("grading.views.grade.enforce_teacher_grade_access")
    @patch("grading.views.grade.initialize_request_authorization")
    @patch("grading.views.grade.get_object")
    def test_direct_update_requires_rbac_permission(
        self,
        mock_get_object,
        mock_initialize,
        mock_enforce_assignment,
    ):
        mock_get_object.return_value = self.grade
        mock_initialize.return_value.require_permission.side_effect = PermissionDenied()

        with self.assertRaises(PermissionDenied):
            GradeDetailView().put(self.request, "grade-1")

        mock_enforce_assignment.assert_not_called()
        self.grade.save.assert_not_called()

    @patch("grading.views.grade.enforce_teacher_grade_access")
    @patch("grading.views.grade.initialize_request_authorization")
    @patch("grading.views.grade.get_object")
    def test_direct_update_requires_assignment_after_permission(
        self,
        mock_get_object,
        mock_initialize,
        mock_enforce_assignment,
    ):
        mock_get_object.return_value = self.grade
        mock_enforce_assignment.side_effect = PermissionDenied(
            GRADE_ASSIGNMENT_DENIED_MESSAGE
        )

        with self.assertRaisesMessage(PermissionDenied, GRADE_ASSIGNMENT_DENIED_MESSAGE):
            GradeDetailView().put(self.request, "grade-1")

        mock_initialize.return_value.require_permission.assert_called_once_with(
            "grades.enter"
        )
        self.grade.save.assert_not_called()

    @patch("grading.views.grade.enforce_teacher_grade_access")
    @patch("grading.views.grade.initialize_request_authorization")
    @patch("grading.views.grade.get_object")
    @patch("grading.views.grade.GradeOut")
    def test_assigned_permitted_teacher_can_update(
        self,
        mock_grade_out,
        mock_get_object,
        mock_initialize,
        mock_enforce_assignment,
    ):
        mock_get_object.return_value = self.grade
        mock_grade_out.return_value.data = {"id": "grade-1", "score": "85"}

        response = GradeDetailView().put(self.request, "grade-1")

        self.assertEqual(response.status_code, 200)
        mock_initialize.return_value.require_permission.assert_called_once_with(
            "grades.enter"
        )
        mock_enforce_assignment.assert_called_once_with(
            self.user,
            "section-1",
            "subject-1",
        )
        self.grade.save.assert_called_once()