from types import SimpleNamespace
from unittest.mock import patch
from django.test import SimpleTestCase
from rest_framework.exceptions import PermissionDenied
from users.parent_workspace import bind_parent_request


class ParentWorkspaceScopeTests(SimpleTestCase):
    def setUp(self):
        self.user = SimpleNamespace(id_number="P001", email="parent@example.com")

    def request(self, path, method="GET", data=None, school="public"):
        return SimpleNamespace(path=path, method=method, data=data or {}, META={"HTTP_X_ROLE_ASSIGNMENT": "platform"}, tenant=SimpleNamespace(schema_name=school))

    def test_global_parent_cannot_access_platform_endpoints_or_change_security_fields(self):
        for path, method, data in [("/api/v1/tenants/", "GET", {}), ("/api/v1/auth/users/P001/", "PATCH", {"is_platform_superuser": True}), ("/api/v1/auth/users/P001/", "PATCH", {"email": "other@example.com"})]:
            with self.assertRaises(PermissionDenied):
                bind_parent_request(self.request(path, method, data), self.user)

    def test_global_parent_can_read_own_profile_but_not_another_profile(self):
        request = self.request("/api/v1/auth/users/P001/")
        bind_parent_request(request, self.user)
        self.assertNotEqual(request.META["HTTP_X_ROLE_ASSIGNMENT"], "platform")
        with self.assertRaises(PermissionDenied):
            bind_parent_request(self.request("/api/v1/auth/users/P002/"), self.user)

    def test_school_context_forces_parent_assignment_and_denies_missing_role(self):
        request = self.request("/api/v1/students/1001/", school="school-a")
        with patch("users.parent_portal.parent_assignment", return_value=SimpleNamespace(pk="parent-role")):
            bind_parent_request(request, self.user)
        self.assertEqual(request.META["HTTP_X_ROLE_ASSIGNMENT"], "parent-role")
        with patch("users.parent_portal.parent_assignment", return_value=None), self.assertRaises(PermissionDenied):
            bind_parent_request(request, self.user)

    def test_parent_server_session_cannot_bypass_parent_scope(self):
        from api.authentication import TenantSessionAuthentication
        session = SimpleNamespace(user=self.user, tenant=SimpleNamespace(schema_name="public"), roles=["parent_workspace"], global_session_id=None)
        request = self.request("/api/v1/tenants/")
        request.META["HTTP_X_TENANT_SESSION"] = "opaque-parent-session"
        with patch("api.authentication.TenantSession.objects") as sessions:
            sessions.select_related.return_value.filter.return_value.first.return_value = session
            with self.assertRaises(PermissionDenied):
                TenantSessionAuthentication().authenticate(request)

    def test_parent_role_discovery_is_allowed_but_selection_is_not(self):
        bind_parent_request(self.request("/api/v1/auth/parent/roles/"), self.user)
        with self.assertRaises(PermissionDenied):
            bind_parent_request(self.request("/api/v1/authorization/me/roles/", "POST"), self.user)

    def test_role_discovery_lists_only_callers_active_assignments_across_schools(self):
        from contextlib import nullcontext
        from unittest.mock import MagicMock
        from rest_framework.test import APIRequestFactory, force_authenticate
        from users.parent_workspace import ParentWorkspaceRolesView
        user = MagicMock(is_active=True, pk="role-discovery-test")
        schools = [SimpleNamespace(schema_name="school_a", name="School A"), SimpleNamespace(schema_name="school_b", name="School B")]
        user.tenants.filter.return_value.exclude.return_value.order_by.return_value = schools
        records = [SimpleNamespace(pk="staff"), SimpleNamespace(pk="parent"), SimpleNamespace(pk="disabled")]
        def role(record):
            return SimpleNamespace(pk=record.pk, name=record.pk.title(), system_key=record.pk, is_active=record.pk != "disabled")
        with patch("users.parent_workspace.parent_identity", return_value=True), patch("django_tenants.utils.schema_context", side_effect=lambda schema: nullcontext()), patch("authorization.models.TenantRoleAssignment.objects.filter") as assignments, patch("authorization.multiple_roles.assignment_role", side_effect=role):
            assignments.return_value.select_related.return_value = records
            request = APIRequestFactory().get("/api/v1/auth/parent/roles/")
            force_authenticate(request, user=user)
            response = ParentWorkspaceRolesView.as_view()(request)
            self.assertEqual(response.status_code, 200)
            self.assertEqual([a["id"] for a in response.data["assignments"]], ["staff", "parent", "staff", "parent"])
            self.assertEqual({a["school"]["schema_name"] for a in response.data["assignments"]}, {"school_a", "school_b"})
            assignments.assert_called_with(membership__user=user, membership__is_active=True, is_active=True)
            user.tenants.filter.assert_called_once_with(active=True, status="active")
