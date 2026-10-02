"""Regression tests for linking accounts to tenant records and notifying them."""

import uuid
from datetime import date
from unittest.mock import patch

from django.test import SimpleTestCase
from django_tenants.test.cases import TenantTestCase
from rest_framework.parsers import JSONParser
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from common.account_link import filter_by_user_account
from common.status import UserAccountType
from users.viewsets import UserViewSet


class AccountLinkFilterTests(SimpleTestCase):
    def test_unknown_values_leave_the_queryset_untouched(self):
        sentinel = object()
        self.assertIs(filter_by_user_account(sentinel, None), sentinel)
        self.assertIs(filter_by_user_account(sentinel, ""), sentinel)
        self.assertIs(filter_by_user_account(sentinel, "maybe"), sentinel)


class AccountProvisioningTests(TenantTestCase):
    """Runs inside a real tenant schema so record lookups behave like production."""

    @classmethod
    def setup_tenant(cls, tenant):
        from users.models import User

        tenant.name = "Account Provisioning School"
        tenant.short_name = "acct"
        tenant.owner, _ = User.objects.get_or_create(
            email="account-provisioning-owner@example.com",
            defaults={
                "username": "account-provisioning-owner",
                "id_number": "ACCOUNT-PROVISIONING-OWNER",
                "account_type": "staff",
                "first_name": "Account",
                "last_name": "Owner",
            },
        )

    def setUp(self):
        super().setUp()
        self.factory = APIRequestFactory()

    # -- fixtures -----------------------------------------------------

    def _student(self, *, email, linked=False):
        from students.models import Student
        if linked:
            from users.models import User
            User.objects.create(id_number="EXISTING-STUDENT-ACCOUNT", username="linked-student", email=email)

        return Student.objects.create(
            first_name="Sam",
            last_name="Student",
            email=email,
            date_of_birth=date(2010, 5, 1),
            gender="male",
            entry_as="new",
            user_account_id_number="EXISTING-STUDENT-ACCOUNT" if linked else None,
        )

    def _employee(self, *, email, linked=False):
        from hr.models import Employee
        if linked:
            from users.models import User
            User.objects.create(id_number="EXISTING-EMPLOYEE-ACCOUNT", username="linked-employee", email=email)

        suffix = uuid.uuid4().hex[:8]
        return Employee.objects.create(
            employee_number=f"EMP-{suffix}",
            id_number=f"EMPID-{suffix}",
            first_name="Erin",
            last_name="Employee",
            email=email,
            date_of_birth=date(1990, 2, 3),
            gender="female",
            user_account_id_number="EXISTING-EMPLOYEE-ACCOUNT" if linked else None,
        )

    def _create_user_request(self, payload):
        http_request = self.factory.post("/api/v1/users/", payload, format="json")
        request = Request(http_request, parsers=[JSONParser()])
        view = UserViewSet()
        view.request = request
        view.format_kwarg = None
        return view.create(request)

    # -- 1. exclusion from selection ----------------------------------

    def test_students_with_an_account_are_excluded_from_selection(self):
        from students.models import Student

        unlinked = self._student(email="unlinked-student@example.com")
        linked = self._student(email="linked-student@example.com", linked=True)

        selectable = filter_by_user_account(Student.objects.all(), "false")
        already_linked = filter_by_user_account(Student.objects.all(), "true")

        self.assertIn(unlinked, selectable)
        self.assertNotIn(linked, selectable)
        self.assertIn(linked, already_linked)
        self.assertNotIn(unlinked, already_linked)

    def test_employees_with_an_account_are_excluded_from_selection(self):
        from hr.employee_filters import apply_employee_list_filters
        from hr.models import Employee

        unlinked = self._employee(email="unlinked-employee@example.com")
        linked = self._employee(email="linked-employee@example.com", linked=True)

        selectable = apply_employee_list_filters(
            Employee.objects.all(), {"has_user_account": "false"}
        )

        self.assertIn(unlinked, selectable)
        self.assertNotIn(linked, selectable)

    # -- 2. linking + 3. welcome email --------------------------------

    def test_creating_a_user_links_the_selected_student_and_sends_the_welcome_email(self):
        from users.models import User

        student = self._student(email="new-student-account@example.com")

        with patch("common.email_service.send_account_created_email", return_value=True) as send_email, self.captureOnCommitCallbacks(execute=True):
            response = self._create_user_request(
                {
                    "account_type": UserAccountType.STUDENT,
                    "id_number": student.id_number,
                }
            )

        self.assertEqual(response.status_code, 201)
        student.refresh_from_db()
        user = User.objects.get(id_number=student.id_number)
        self.assertEqual(student.user_account_id_number, user.id_number)
        self.assertEqual(user.email, "new-student-account@example.com")
        self.assertTrue(user.is_default_password)

        send_email.assert_called_once()
        kwargs = send_email.call_args.kwargs
        self.assertEqual(kwargs["user"], user)
        self.assertEqual(kwargs["temporary_password"], student.id_number)
        self.assertIn("/login", kwargs["login_url"])
        self.assertEqual(kwargs["school"].schema_name, self.tenant.schema_name)

    def test_creating_a_user_links_the_selected_employee(self):
        from users.models import User

        employee = self._employee(email="new-employee-account@example.com")

        with patch("common.email_service.send_account_created_email", return_value=True):
            response = self._create_user_request(
                {
                    "account_type": UserAccountType.STAFF,
                    "id_number": employee.id_number,
                    "role": "staff",
                }
            )

        self.assertEqual(response.status_code, 201)
        employee.refresh_from_db()
        user = User.objects.get(id_number=employee.id_number)
        self.assertEqual(employee.user_account_id_number, user.id_number)
        self.assertEqual(user.account_type, UserAccountType.STAFF)

    def test_staff_account_creation_requires_an_explicit_role(self):
        employee = self._employee(email="roleless-employee@example.com")

        response = self._create_user_request(
            {
                "account_type": UserAccountType.STAFF,
                "id_number": employee.id_number,
            }
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("role", response.data["errors"])

    def test_created_account_receives_the_requested_role(self):
        from authorization.services import get_assigned_role
        from users.models import User

        employee = self._employee(email="registrar-employee@example.com")

        with patch("common.email_service.send_account_created_email", return_value=True):
            response = self._create_user_request(
                {
                    "account_type": UserAccountType.STAFF,
                    "id_number": employee.id_number,
                    "role": "registrar",
                }
            )

        self.assertEqual(response.status_code, 201)
        user = User.objects.get(id_number=employee.id_number)
        self.assertEqual(get_assigned_role(user).system_key, "registrar")

    def test_superadmin_role_cannot_be_requested_at_creation(self):
        employee = self._employee(email="escalation-employee@example.com")

        response = self._create_user_request(
            {
                "account_type": UserAccountType.STAFF,
                "id_number": employee.id_number,
                "role": "superadmin",
            }
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("role", response.data["errors"])

    def test_notification_can_be_suppressed(self):
        student = self._student(email="quiet-student@example.com")

        with patch("common.email_service.send_account_created_email", return_value=True) as send_email:
            response = self._create_user_request(
                {
                    "account_type": UserAccountType.STUDENT,
                    "id_number": student.id_number,
                    "notify_user": False,
                }
            )

        self.assertEqual(response.status_code, 201)
        send_email.assert_not_called()

    def _shared_user(self, email, *, account_type="staff", active=True):
        from users.models import User
        tag = uuid.uuid4().hex
        user = User.objects.create(
            username=f"shared-{tag}", id_number=f"SHARED-{tag}", email=email,
            first_name="Original", last_name="Identity", account_type=account_type,
            is_active=active, status="active" if active else "suspended",
        )
        user.set_password("Existing-password-123")
        user.save(update_fields=["password"])
        return user

    def test_staff_reuses_existing_account_and_keeps_credentials_and_parent_role(self):
        from authorization.models import Role, TenantRoleAssignment
        from authorization.services import assign_user_role
        from users.models import User, ParentProfile
        employee = self._employee(email="Shared-Parent@example.com")
        user = self._shared_user("shared-parent@example.com", account_type="parent")
        password = user.password
        profile = ParentProfile.objects.create(user=user)
        self.tenant.add_user(user)
        assign_user_role(user=user, role=Role.objects.get(system_key="parent"))
        before = User.objects.count()
        payload = {"account_type": "staff", "id_number": employee.id_number, "role": "teacher", "username": "must-not-replace"}
        with patch("common.email_service.send_account_created_email") as mail:
            for _ in range(2):
                response = self._create_user_request(payload)
                self.assertEqual(response.status_code, 200, response.data)
                self.assertTrue(response.data["linked_existing"])
            mail.assert_not_called()
        employee.refresh_from_db(); user.refresh_from_db()
        self.assertEqual(employee.user_account_id_number, user.id_number)
        self.assertEqual(employee.email, user.email)
        self.assertEqual(User.objects.count(), before)
        self.assertEqual(user.password, password)
        self.assertEqual(user.account_type, "parent")
        self.assertEqual(user.first_name, "Original")
        self.assertNotEqual(user.username, "must-not-replace")
        self.assertEqual(ParentProfile.objects.get(pk=profile.pk).user_id, user.pk)
        self.assertEqual(set(TenantRoleAssignment.objects.filter(membership__user=user, is_active=True).values_list("role__system_key", flat=True)), {"parent", "teacher"})

    def test_staff_links_account_with_different_global_id(self):
        user = self._shared_user("another-school@example.com")
        employee = self._employee(email=user.email)
        with patch("common.email_service.send_account_created_email") as mail:
            response = self._create_user_request({"account_type": "staff", "id_number": employee.id_number, "role": "staff"})
            self.assertEqual(response.status_code, 200, response.data)
            mail.assert_not_called()
        employee.refresh_from_db()
        self.assertEqual(employee.user_account_id_number, user.id_number)
        self.assertTrue(user.tenants.filter(pk=self.tenant.pk).exists())

    def test_disabled_existing_account_is_not_reactivated(self):
        user = self._shared_user("disabled-staff@example.com", active=False)
        employee = self._employee(email=user.email)
        response = self._create_user_request({"account_type": "staff", "id_number": employee.id_number, "role": "teacher"})
        self.assertEqual(response.status_code, 400, response.data)
        employee.refresh_from_db(); user.refresh_from_db()
        self.assertFalse(user.is_active)
        self.assertFalse(employee.user_account_id_number)
        self.assertFalse(user.tenants.filter(pk=self.tenant.pk).exists())

    def test_conflicting_live_reference_is_not_replaced(self):
        user = self._shared_user("original-link@example.com")
        other = self._shared_user("different-email@example.com")
        employee = self._employee(email=other.email)
        employee.user_account_id_number = user.id_number
        employee.save(update_fields=["user_account_id_number"])
        response = self._create_user_request({"account_type": "staff", "id_number": employee.id_number, "role": "teacher"})
        self.assertEqual(response.status_code, 400, response.data)
        employee.refresh_from_db()
        self.assertEqual(employee.user_account_id_number, user.id_number)
        self.assertFalse(other.tenants.filter(pk=self.tenant.pk).exists())

    def test_role_failure_rolls_back_tenant_membership_and_link(self):
        from django.core.exceptions import ValidationError
        user = self._shared_user("rollback-link@example.com")
        employee = self._employee(email=user.email)
        with patch("users.account_provisioning.assign_user_role", side_effect=ValidationError("Cannot assign this role")):
            response = self._create_user_request({"account_type": "staff", "id_number": employee.id_number, "role": "teacher"})
        self.assertEqual(response.status_code, 400, response.data)
        employee.refresh_from_db()
        self.assertFalse(employee.user_account_id_number)
        self.assertFalse(user.tenants.filter(pk=self.tenant.pk).exists())

    def test_matching_school_id_does_not_claim_unrelated_global_account(self):
        from users.models import User
        employee = self._employee(email="new-person@example.com")
        unrelated = self._shared_user("unrelated-person@example.com")
        unrelated.id_number = employee.id_number
        unrelated.save(update_fields=["id_number"])
        response = self._create_user_request({"account_type": "staff", "id_number": employee.id_number, "role": "teacher", "notify_user": False})
        self.assertEqual(response.status_code, 201, response.data)
        employee.refresh_from_db()
        self.assertNotEqual(employee.user_account_id_number, unrelated.id_number)
        self.assertEqual(User.objects.get(id_number=employee.user_account_id_number).email, employee.email)

    def test_student_does_not_claim_parent_email_account(self):
        parent = self._shared_user("household@example.com", account_type="parent")
        student = self._student(email=parent.email)
        response = self._create_user_request({"account_type": "student", "id_number": student.id_number})
        self.assertEqual(response.status_code, 400, response.data)
        student.refresh_from_db()
        self.assertFalse(student.user_account_id_number)


class ExistingAccountResolutionTests(SimpleTestCase):
    def test_ambiguous_case_variant_email_fails_closed(self):
        from types import SimpleNamespace
        from rest_framework.exceptions import ValidationError
        from users.account_provisioning import resolve_existing_account
        record = SimpleNamespace(user_account_id_number=None, id_number="SCHOOL-ID")
        with patch("users.account_provisioning.User.objects.select_for_update") as users:
            users.return_value.filter.return_value = [object(), object()]
            with self.assertRaises(ValidationError):
                resolve_existing_account(record, "same@example.com", "staff")

    def test_stale_deleted_account_reference_can_be_repaired_by_staff_provisioning(self):
        from types import SimpleNamespace
        from users.account_provisioning import resolve_existing_account
        record = SimpleNamespace(user_account_id_number="DELETED", id_number="SCHOOL-ID")
        user = SimpleNamespace(pk="live", id_number="LIVE", email="same@example.com", is_active=True, status="active")
        with patch("users.account_provisioning.User.objects.select_for_update") as users:
            users.return_value.filter.return_value.first.return_value = None
            users.return_value.filter.return_value.__getitem__.return_value = [user]
            self.assertIs(resolve_existing_account(record, "same@example.com", "staff"), user)
