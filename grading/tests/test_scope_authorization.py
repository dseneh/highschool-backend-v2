from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase
from django_tenants.test.cases import TenantTestCase

from grading.services.scope_authorization import (
    accessible_student_ids,
    filter_gradebooks_for_view_scope,
    user_can_view_grade,
    user_can_view_section_grades,
)
from students.models import Student, StudentGuardian
from users.models import User


class GradingScopeAuthorizationTests(SimpleTestCase):
    def setUp(self):
        self.request = SimpleNamespace(user=SimpleNamespace(id_number="USR-1"))

    @patch("grading.services.scope_authorization.grading_view_scope", return_value="all")
    def test_all_scope_keeps_gradebook_queryset(self, _scope):
        queryset = Mock()

        self.assertIs(filter_gradebooks_for_view_scope(queryset, self.request), queryset)

    @patch("grading.services.scope_authorization.get_teacher_gradebook_scope")
    @patch("grading.services.scope_authorization.grading_view_scope", return_value="assigned")
    def test_assigned_scope_filters_gradebooks_to_teacher_assignments(
        self,
        _scope,
        teacher_scope,
    ):
        teacher_scope.return_value = {
            "explicit_section_subject_ids": {"ss-1"},
            "general_subject_ids": {"subject-1"},
            "section_ids": {"section-1"},
        }
        queryset = Mock()
        filtered = Mock()
        queryset.filter.return_value.distinct.return_value = filtered

        result = filter_gradebooks_for_view_scope(queryset, self.request)

        self.assertIs(result, filtered)
        queryset.filter.assert_called_once()

    @patch("grading.services.scope_authorization.accessible_student_ids")
    @patch("grading.services.scope_authorization.grading_view_scope", return_value="own")
    def test_own_scope_filters_gradebooks_to_linked_students(
        self,
        _scope,
        student_ids,
    ):
        student_ids.return_value = {"student-1"}
        queryset = Mock()
        filtered = Mock()
        queryset.filter.return_value.distinct.return_value = filtered

        result = filter_gradebooks_for_view_scope(queryset, self.request)

        self.assertIs(result, filtered)
        queryset.filter.assert_called_once_with(
            assessments__grades__student_id__in={"student-1"}
        )

    @patch("grading.services.scope_authorization.grading_view_scope", return_value=None)
    def test_missing_scope_fails_closed(self, _scope):
        queryset = Mock()
        denied = Mock()
        queryset.none.return_value = denied

        self.assertIs(filter_gradebooks_for_view_scope(queryset, self.request), denied)

    @patch("grading.services.scope_authorization.accessible_student_ids")
    @patch("grading.services.scope_authorization.grading_view_scope", return_value="own")
    def test_own_grade_access_requires_linked_student(self, _scope, student_ids):
        student_ids.return_value = {"student-1"}
        grade = SimpleNamespace(
            student_id="student-1",
            section_id="section-1",
            subject_id="subject-1",
        )

        self.assertTrue(user_can_view_grade(grade, self.request))
        grade.student_id = "student-2"
        self.assertFalse(user_can_view_grade(grade, self.request))

    @patch("grading.services.scope_authorization.get_teacher_allowed_section_ids")
    @patch("grading.services.scope_authorization.grading_view_scope", return_value="assigned")
    def test_assigned_section_access_requires_teacher_assignment(
        self,
        _scope,
        section_ids,
    ):
        section_ids.return_value = {"section-1"}

        self.assertTrue(user_can_view_section_grades("section-1", self.request))
        self.assertFalse(user_can_view_section_grades("section-2", self.request))

    @patch("grading.services.scope_authorization.grading_view_scope", return_value="own")
    def test_own_scope_cannot_view_section_grades(self, _scope):
        self.assertFalse(user_can_view_section_grades("section-1", self.request))


class GradingOwnershipScopeTests(TenantTestCase):
    @classmethod
    def get_test_schema_name(cls):
        return "grading_ownership_scope"

    @classmethod
    def get_test_tenant_domain(cls):
        return "grading-ownership-scope.tenant.test.com"

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.name = "Grading Ownership Scope Test School"
        tenant.id_number = "GOS001"
        tenant.owner, _ = User.objects.get_or_create(
            email="grading-scope-owner@example.com",
            defaults={
                "username": "grading-scope-owner",
                "id_number": "GRADING-SCOPE-OWNER-001",
                "account_type": "staff",
            },
        )

    def create_student(self, *, id_number, sequence, user_id_number=None):
        return Student.objects.create(
            first_name="Scope",
            last_name=f"Student {sequence}",
            id_number=id_number,
            user_account_id_number=user_id_number,
            entry_as="new",
            school_code=1,
            student_seq=sequence,
        )

    def test_student_account_resolves_only_linked_student(self):
        user = User.objects.create(
            email="grading-scope-student@example.com",
            username="grading-scope-student",
            id_number="GRADING-SCOPE-STUDENT-001",
            account_type="student",
        )
        linked = self.create_student(
            id_number="81001",
            sequence=81001,
            user_id_number=user.id_number,
        )
        self.create_student(id_number="81002", sequence=81002)

        self.assertEqual(accessible_student_ids(user), {linked.id})

    def test_guardian_account_resolves_only_linked_children(self):
        user = User.objects.create(
            email="grading-scope-parent@example.com",
            username="grading-scope-parent",
            id_number="GRADING-SCOPE-PARENT-001",
            account_type="parent",
        )
        child = self.create_student(id_number="82001", sequence=82001)
        other = self.create_student(id_number="82002", sequence=82002)
        StudentGuardian.objects.create(
            student=child,
            first_name="Scope",
            last_name="Parent",
            user_account_id_number=user.id_number,
            active=True,
        )

        student_ids = accessible_student_ids(user)

        self.assertIn(child.id, student_ids)
        self.assertNotIn(other.id, student_ids)
