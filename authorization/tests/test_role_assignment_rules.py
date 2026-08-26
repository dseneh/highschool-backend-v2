from types import SimpleNamespace
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from authorization.services import validate_role_for_account_type


class RoleAssignmentRulesTests(SimpleTestCase):
    def test_student_account_accepts_student_role(self):
        student = SimpleNamespace(pk="student-1", account_type="student")
        student_role = SimpleNamespace(
            pk="role-student",
            is_active=True,
            system_key="student",
        )

        validate_role_for_account_type(user=student, role=student_role)

    def test_student_account_rejects_staff_role(self):
        student = SimpleNamespace(pk="student-1", account_type="student")
        staff_role = SimpleNamespace(is_active=True, system_key="staff")

        with self.assertRaisesMessage(
            ValidationError,
            "Student accounts must use the student role.",
        ):
            validate_role_for_account_type(user=student, role=staff_role)

    def test_parent_account_rejects_custom_role(self):
        parent = SimpleNamespace(pk="parent-1", account_type="parent")
        custom_role = SimpleNamespace(is_active=True, system_key=None)

        with self.assertRaisesMessage(
            ValidationError,
            "Parent accounts must use the parent role.",
        ):
            validate_role_for_account_type(user=parent, role=custom_role)