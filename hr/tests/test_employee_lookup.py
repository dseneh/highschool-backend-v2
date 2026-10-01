from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from django.test import SimpleTestCase
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from hr.employee_lookup import PROFILE_FIELDS, available_sources, can_read_source, lookup_profile
from hr.views import EmployeeViewSet
from authorization.drf import RBACPermission


class EmployeeLookupTests(SimpleTestCase):
    def setUp(self):
        self.tenant = SimpleNamespace(pk=uuid4(), schema_name="source_school", name="Source School")
        self.user = SimpleNamespace(pk=uuid4(), is_authenticated=True, is_active=True,
                                    is_platform_superuser=False, _active_role_selection="destination-role")
        self.payload = {"tenant_id": str(self.tenant.pk), "email": "person@example.com"}

    def test_requires_destination_create_permission(self):
        for action in ("lookup_sources", "lookup_profile"):
            view = EmployeeViewSet()
            view.action = action
            request = SimpleNamespace(user=self.user, method="POST")
            with patch("authorization.drf.initialize_request_authorization") as initialize:
                initialize.return_value.permission_scope.return_value = None
                self.assertFalse(RBACPermission().has_permission(request, view))
                initialize.return_value.permission_scope.assert_called_once_with("employees.create")

    def test_unauthorized_tenant_never_reads_employees(self):
        with patch("hr.employee_lookup.candidate_tenants", return_value=[]), patch("hr.employee_lookup.Employee.objects.filter") as query:
            with self.assertRaises(PermissionDenied):
                lookup_profile(self.user, self.payload)
            query.assert_not_called()

    def test_source_access_rechecked_before_each_lookup(self):
        with patch("hr.employee_lookup.candidate_tenants", return_value=[self.tenant]), patch("hr.employee_lookup.can_read_source", return_value=False), patch("hr.employee_lookup.Employee.objects.filter") as query:
            with self.assertRaises(PermissionDenied):
                lookup_profile(self.user, self.payload)
            query.assert_not_called()

    def test_only_permitted_sources_returned(self):
        other = SimpleNamespace(pk=uuid4(), name="Hidden")
        with patch("hr.employee_lookup.candidate_tenants", return_value=[self.tenant, other]), patch("hr.employee_lookup.can_read_source", side_effect=[True, False]):
            self.assertEqual(available_sources(self.user), [{"id": str(self.tenant.pk), "name": self.tenant.name}])

    def test_invalid_email_rejected_before_discovery(self):
        with patch("hr.employee_lookup.candidate_tenants") as candidates:
            with self.assertRaises(ValidationError):
                lookup_profile(self.user, {**self.payload, "email": "not-email"})
            candidates.assert_not_called()

    def test_exact_email_allowlist_and_ambiguous_matches(self):
        profile = {field: None for field in PROFILE_FIELDS}
        profile.update(first_name="Ada", email="person@example.com")
        with patch("hr.employee_lookup.candidate_tenants", return_value=[self.tenant]), patch("hr.employee_lookup.can_read_source", return_value=True), patch("hr.employee_lookup.schema_context", return_value=nullcontext()) as context, patch("hr.employee_lookup.Employee.objects.filter") as query:
            query.return_value.values.return_value = [profile]
            self.assertEqual(lookup_profile(self.user, self.payload)["employee"], profile)
            query.assert_called_with(email__iexact="person@example.com")
            query.return_value.values.assert_called_with(*PROFILE_FIELDS)
            context.assert_called_with("source_school")
            self.assertFalse(set(PROFILE_FIELDS) & {"user_account_id_number", "basic_salary", "bank_account_number", "id_number", "department_id", "position_id"})
            query.return_value.values.return_value = []
            with self.assertRaises(NotFound):
                lookup_profile(self.user, self.payload)
            query.return_value.values.return_value = [profile, profile]
            with self.assertRaises(ValidationError):
                lookup_profile(self.user, self.payload)

    def test_uses_one_source_assignment_without_promoting_platform_user(self):
        self.user.is_platform_superuser = True  # Currently using a tenant role.
        with patch("hr.employee_lookup.schema_context", return_value=nullcontext()), patch("hr.employee_lookup.selected_assignment", return_value=SimpleNamespace(pk="source-role")), patch("hr.employee_lookup.resolve_authorization_context") as resolve:
            resolve.return_value.permission_scope.return_value = "own"
            self.assertFalse(can_read_source(self.user, self.tenant))
            actor = resolve.call_args.args[0]
            self.assertFalse(actor.is_platform_superuser)
            self.assertEqual(actor._active_role_selection, "source-role")
            self.assertEqual(self.user._active_role_selection, "destination-role")
            resolve.return_value.permission_scope.return_value = "all"
            self.assertTrue(can_read_source(self.user, self.tenant))
