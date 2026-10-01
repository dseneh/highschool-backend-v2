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

    def test_student_account_accepts_additional_staff_role(self):
        student = SimpleNamespace(pk="student-1", account_type="student")
        staff_role = SimpleNamespace(is_active=True, system_key="staff")

        validate_role_for_account_type(user=student, role=staff_role)

    def test_parent_account_accepts_additional_custom_role(self):
        parent = SimpleNamespace(pk="parent-1", account_type="parent")
        custom_role = SimpleNamespace(is_active=True, system_key=None)

        validate_role_for_account_type(user=parent, role=custom_role)


class AccountCreationRoleTests(SimpleTestCase):
    def test_student_role_is_fixed_even_without_identifier(self):
        from unittest.mock import patch
        from authorization.services import resolve_assignable_role
        role = SimpleNamespace(system_key="student")
        with patch("authorization.services.Role.objects.get", return_value=role) as lookup:
            self.assertIs(resolve_assignable_role(None, account_type="STUDENT"), role)
            lookup.assert_called_once_with(system_key="student")

    def test_staff_creation_resolves_selected_role(self):
        from unittest.mock import patch
        from authorization.services import resolve_assignable_role
        role = SimpleNamespace(system_key="teacher")
        with patch("authorization.services.Role.objects.filter") as lookup:
            lookup.return_value.first.return_value = role
            self.assertIs(resolve_assignable_role("teacher", account_type="staff"), role)
            lookup.assert_called_once_with(system_key="teacher", is_active=True)

    def test_staff_creation_still_requires_a_role(self):
        from authorization.services import resolve_assignable_role
        with self.assertRaisesMessage(ValidationError, "A role is required."):
            resolve_assignable_role(None, account_type="staff")
