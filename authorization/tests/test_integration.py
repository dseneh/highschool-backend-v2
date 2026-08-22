from types import SimpleNamespace
from unittest.mock import patch

from django.core.management import call_command
from django.core.exceptions import ValidationError
from django.core.cache import cache
from django.db import connection
from django_tenants.test.cases import TenantTestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from authorization.models import Role, RolePermission, TenantMembership
from authorization.registry import get_permission_registry
from authorization.runtime import (
    initialize_request_authorization,
    resolve_authorization_context,
)
from authorization.services import replace_role_permissions
from authorization.views import PermissionCatalogView, RoleViewSet, UserRoleView
from users.models import User


class AuthorizationPersistenceTests(TenantTestCase):
    @classmethod
    def get_test_schema_name(cls):
        return "authorization_test"

    @classmethod
    def get_test_tenant_domain(cls):
        return "authorization.tenant.test.com"

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.name = "Authorization Test School"
        tenant.id_number = "AUTH001"
        tenant.owner, _ = User.objects.get_or_create(
            email="authorization-owner@example.com",
            defaults={
                "username": "authorization-owner",
                "id_number": "AUTHORIZATION-OWNER-001",
                "role": "admin",
                "first_name": "Authorization",
                "last_name": "Owner",
            },
        )

    def setUp(self):
        super().setUp()
        cache.clear()
        self.factory = APIRequestFactory()

    def _request(self, method, path, data=None):
        request = getattr(self.factory, method)(path, data or {}, format="json")
        request.tenant = self.tenant
        force_authenticate(request, user=self.tenant.owner)
        return request

    def _set_owner_role(self, role):
        membership = TenantMembership.objects.get(user=self.tenant.owner)
        membership.role = role
        membership.is_active = True
        membership.save()
        return membership

    def test_sync_seeds_system_roles_and_is_idempotent(self):
        call_command(
            "sync_permissions",
            schema=self.tenant.schema_name,
            verbosity=0,
        )

        self.assertEqual(Role.objects.filter(is_system_role=True).count(), 8)
        admin = Role.objects.get(system_key="admin")
        self.assertEqual(
            admin.permission_grants.count(),
            len(get_permission_registry().permissions),
        )
        original_version = admin.permission_version

        call_command(
            "sync_permissions",
            schema=self.tenant.schema_name,
            verbosity=0,
        )

        admin.refresh_from_db()
        self.assertEqual(admin.permission_version, original_version)

    def test_new_tenant_schema_is_seeded_automatically(self):
        self.assertEqual(Role.objects.filter(is_system_role=True).count(), 8)

    def test_custom_role_accepts_valid_scoped_permission(self):
        role = Role.objects.create(name="Senior Teacher")
        original_version = role.permission_version

        role = replace_role_permissions(
            role,
            {
                "grades.view": "assigned",
                "grades.enter": "assigned",
            },
        )

        self.assertEqual(
            dict(
                role.permission_grants.values_list("permission_code", "scope")
            ),
            {"grades.view": "assigned", "grades.enter": "assigned"},
        )
        self.assertEqual(role.permission_version, original_version + 1)

    def test_custom_role_rejects_missing_permission_dependency(self):
        role = Role.objects.create(name="Incomplete Teacher")

        with self.assertRaisesMessage(ValidationError, "requires: grades.view"):
            replace_role_permissions(role, {"grades.enter": "assigned"})

    def test_system_roles_reject_queryset_mutations(self):
        admin = Role.objects.get(system_key="admin")

        with self.assertRaises(ValidationError):
            Role.objects.filter(pk=admin.pk).update(name="Changed Admin")
        with self.assertRaises(ValidationError):
            Role.objects.filter(pk=admin.pk).delete()
        with self.assertRaises(ValidationError):
            RolePermission.objects.filter(role=admin).delete()
        with self.assertRaises(ValidationError):
            Role.objects.filter(pk=admin.pk).update(permission_version=1)

    def test_deferred_system_role_rejects_instance_mutation(self):
        admin = Role.objects.only("id").get(system_key="admin")
        admin.name = "Changed Admin"

        with self.assertRaises(ValidationError):
            admin.save(update_fields=("name",))

    def test_grant_edit_cannot_break_existing_dependencies(self):
        role = Role.objects.create(name="Dependency Test Role")
        replace_role_permissions(
            role,
            {
                "grades.view": "assigned",
                "grades.enter": "assigned",
            },
        )
        view_grant = role.permission_grants.get(permission_code="grades.view")
        view_grant.permission_code = "students.view"

        with self.assertRaises(ValidationError):
            view_grant.save()

    def test_grant_cannot_be_reassigned_between_roles(self):
        source = Role.objects.create(name="Grant Source")
        destination = Role.objects.create(name="Grant Destination")
        grant = RolePermission.objects.create(
            role=source,
            permission_code="students.view",
            scope="all",
        )
        grant.role = destination

        with self.assertRaises(ValidationError):
            grant.save()

    def test_membership_owner_cannot_be_reassigned(self):
        role = Role.objects.create(name="Membership Owner Role")
        membership = self._set_owner_role(role)
        other_user, _ = User.objects.get_or_create(
            email="authorization-other@example.com",
            defaults={
                "username": "authorization-other",
                "id_number": "AUTHORIZATION-OTHER-001",
                "role": "viewer",
            },
        )
        membership.user = other_user

        with self.assertRaises(ValidationError):
            membership.save(update_fields=("user",))

    @patch("authorization.runtime._has_outer_transaction", return_value=False)
    def test_warm_authorization_uses_zero_database_queries(self, mock_outer):
        role = Role.objects.create(name="Cached Teacher")
        replace_role_permissions(
            role,
            {
                "students.view": "assigned",
                "grades.view": "assigned",
                "grades.enter": "assigned",
            },
        )
        self._set_owner_role(role)

        # django-tenants emits a SET search_path before each SELECT.
        with self.assertNumQueries(4):
            cold_context = resolve_authorization_context(self.tenant.owner)
        with self.assertNumQueries(0):
            warm_context = resolve_authorization_context(self.tenant.owner)

        self.assertTrue(cold_context.can("grades.enter"))
        self.assertFalse(cold_context.cache_hit)
        self.assertTrue(warm_context.can("grades.enter"))
        self.assertTrue(warm_context.cache_hit)

    @patch("authorization.runtime._has_outer_transaction", return_value=False)
    def test_request_facade_resolves_once_per_request(self, mock_outer):
        role = Role.objects.create(name="Request Cached Teacher")
        replace_role_permissions(role, {"students.view": "all"})
        self._set_owner_role(role)
        request = SimpleNamespace(
            tenant=self.tenant,
            user=self.tenant.owner,
        )
        facade = initialize_request_authorization(request, self.tenant.owner)

        with self.assertNumQueries(4):
            self.assertTrue(facade.can("students.view"))
        with self.assertNumQueries(0):
            self.assertTrue(request.can("students.view"))
            self.assertEqual(request.permission_scope("students.view"), "all")
            self.assertTrue(request.can_any("grades.view", "students.view"))

    @patch("authorization.runtime._has_outer_transaction", return_value=False)
    def test_role_permission_change_invalidates_warm_cache_after_commit(
        self,
        mock_outer,
    ):
        role = Role.objects.create(name="Invalidated Teacher")
        replace_role_permissions(role, {"students.view": "all"})
        self._set_owner_role(role)
        self.assertTrue(resolve_authorization_context(self.tenant.owner).can("students.view"))

        with self.captureOnCommitCallbacks(execute=True):
            replace_role_permissions(role, {"grades.view": "all"})

        refreshed = resolve_authorization_context(self.tenant.owner)
        self.assertFalse(refreshed.can("students.view"))
        self.assertTrue(refreshed.can("grades.view"))

    @patch("authorization.runtime._has_outer_transaction", return_value=False)
    def test_membership_role_change_invalidates_warm_cache_after_commit(
        self,
        mock_outer,
    ):
        first_role = Role.objects.create(name="First Cached Role")
        second_role = Role.objects.create(name="Second Cached Role")
        replace_role_permissions(first_role, {"students.view": "all"})
        replace_role_permissions(second_role, {"grades.view": "all"})
        membership = self._set_owner_role(first_role)
        self.assertTrue(resolve_authorization_context(self.tenant.owner).can("students.view"))

        membership.role = second_role
        with self.captureOnCommitCallbacks(execute=True):
            membership.save(update_fields=("role",))

        refreshed = resolve_authorization_context(self.tenant.owner)
        self.assertFalse(refreshed.can("students.view"))
        self.assertTrue(refreshed.can("grades.view"))

    def test_missing_membership_fails_closed_without_persisting_stale_state(self):
        other_user, _ = User.objects.get_or_create(
            email="authorization-no-membership@example.com",
            defaults={
                "username": "authorization-no-membership",
                "id_number": "AUTHORIZATION-NO-MEMBER-001",
                "role": "viewer",
            },
        )

        with self.assertNumQueries(2):
            first = resolve_authorization_context(other_user)
        with self.assertNumQueries(2):
            second = resolve_authorization_context(other_user)

        self.assertFalse(first.active)
        self.assertFalse(second.active)
        self.assertEqual(connection.schema_name, self.tenant.schema_name)

    def test_outer_transaction_does_not_publish_authorization_cache(self):
        role = Role.objects.create(name="Transactional Cache Role")
        replace_role_permissions(role, {"students.view": "all"})
        self._set_owner_role(role)

        with self.assertNumQueries(4):
            first = resolve_authorization_context(self.tenant.owner)
        with self.assertNumQueries(4):
            second = resolve_authorization_context(self.tenant.owner)

        self.assertTrue(first.can("students.view"))
        self.assertFalse(first.cache_hit)
        self.assertFalse(second.cache_hit)

    def test_permission_catalog_api_returns_grouped_scopes_and_risk(self):
        response = PermissionCatalogView.as_view()(
            self._request("get", "/api/v1/authorization/permissions/")
        )

        self.assertEqual(response.status_code, 200)
        students = next(
            module for module in response.data["modules"] if module["code"] == "students"
        )
        view_permission = next(
            item for item in students["permissions"] if item["code"] == "students.view"
        )
        self.assertEqual(view_permission["risk"], "medium")
        self.assertEqual(view_permission["allowed_scopes"], ["own", "assigned", "all"])

    def test_role_api_create_edit_clone_permissions_and_delete(self):
        create_view = RoleViewSet.as_view({"post": "create"})
        create_response = create_view(
            self._request(
                "post",
                "/api/v1/authorization/roles/",
                {
                    "name": "Grade Reviewer",
                    "description": "Reviews assigned grades",
                    "permissions": [
                        {"code": "grades.view", "scope": "assigned"},
                        {"code": "grades.review", "scope": "assigned"},
                    ],
                },
            )
        )
        self.assertEqual(create_response.status_code, 201, create_response.data)
        role_id = create_response.data["id"]
        self.assertEqual(len(create_response.data["permissions"]), 2)

        update_response = RoleViewSet.as_view({"patch": "partial_update"})(
            self._request(
                "patch",
                f"/api/v1/authorization/roles/{role_id}/",
                {"name": "Senior Grade Reviewer"},
            ),
            pk=role_id,
        )
        self.assertEqual(update_response.status_code, 200, update_response.data)
        self.assertEqual(update_response.data["name"], "Senior Grade Reviewer")

        clone_response = RoleViewSet.as_view({"post": "clone"})(
            self._request(
                "post",
                f"/api/v1/authorization/roles/{role_id}/clone/",
                {"name": "Junior Grade Reviewer"},
            ),
            pk=role_id,
        )
        self.assertEqual(clone_response.status_code, 201, clone_response.data)
        self.assertFalse(clone_response.data["is_system_role"])
        self.assertEqual(len(clone_response.data["permissions"]), 2)

        delete_response = RoleViewSet.as_view({"delete": "destroy"})(
            self._request(
                "delete",
                f"/api/v1/authorization/roles/{clone_response.data['id']}/",
            ),
            pk=clone_response.data["id"],
        )
        self.assertEqual(delete_response.status_code, 204)

    def test_superadmin_can_delegate_arbitrary_scopes(self):
        from authorization.services import validate_permission_delegation

        superadmin = User.objects.create(
            email="platform-superadmin@example.com",
            username="platform-superadmin",
            id_number="SUPER-001",
            role="superadmin",
            first_name="Platform",
            last_name="Superadmin",
        )
        grants = {"grades.view": "own", "grades.review": "all", "students.view": "assigned"}
        validate_permission_delegation(superadmin, grants)

    def test_system_role_api_is_cloneable_but_not_editable_or_deletable(self):
        teacher = Role.objects.get(system_key="teacher")
        update_response = RoleViewSet.as_view({"patch": "partial_update"})(
            self._request(
                "patch",
                f"/api/v1/authorization/roles/{teacher.pk}/",
                {"name": "Changed Teacher"},
            ),
            pk=teacher.pk,
        )
        delete_response = RoleViewSet.as_view({"delete": "destroy"})(
            self._request(
                "delete",
                f"/api/v1/authorization/roles/{teacher.pk}/",
            ),
            pk=teacher.pk,
        )

        self.assertEqual(update_response.status_code, 400)
        self.assertEqual(delete_response.status_code, 400)

    def test_user_role_api_assigns_exactly_one_tenant_role(self):
        target, _ = User.objects.get_or_create(
            email="authorization-role-target@example.com",
            defaults={
                "username": "authorization-role-target",
                "id_number": "AUTH-ROLE-TARGET-001",
                "role": "viewer",
            },
        )
        self.tenant.add_user(target)
        staff_role = Role.objects.get(system_key="staff")

        response = UserRoleView.as_view()(
            self._request(
                "put",
                f"/api/v1/authorization/users/{target.id_number}/role/",
                {"role_id": str(staff_role.pk)},
            ),
            id_number=target.id_number,
        )

        self.assertEqual(response.status_code, 200, response.data)
        membership = TenantMembership.objects.get(user=target)
        self.assertEqual(membership.role, staff_role)
        self.assertEqual(TenantMembership.objects.filter(user=target).count(), 1)

    def test_membership_version_changes_with_role(self):
        teacher = Role.objects.create(name="Versioned Teacher")
        registrar = Role.objects.create(name="Versioned Registrar")
        membership = self._set_owner_role(teacher)

        original_version = membership.membership_version
        membership.role = registrar
        membership.save(update_fields=("role",))

        self.assertEqual(membership.membership_version, original_version + 1)

    def test_membership_has_exactly_one_role_per_user_in_schema(self):
        teacher = Role.objects.create(name="Teacher Clone")
        registrar = Role.objects.create(name="Registrar Clone")
        self._set_owner_role(teacher)

        with self.assertRaises(ValidationError):
            TenantMembership.objects.create(
                user=self.tenant.owner,
                role=registrar,
            )
