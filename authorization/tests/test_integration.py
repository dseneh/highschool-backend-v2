from types import SimpleNamespace
from unittest.mock import patch

from django.core.management import call_command
from django.core.exceptions import ValidationError
from django.core.cache import cache
from django.db import connection
from django_tenants.utils import get_public_schema_name, schema_context
from django_tenants.test.cases import TenantTestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from authorization.models import Role, RolePermission, TenantMembership
from authorization.registry import get_permission_registry
from authorization.runtime import (
    initialize_request_authorization,
    resolve_authorization_context,
)
from authorization.services import (
    assign_user_role,
    get_unified_role_payloads,
    replace_role_permissions,
)
from authorization.views import (
    BulkUserRoleAssignmentView,
    PermissionCatalogView,
    RoleViewSet,
    UserRoleView,
)
from core.models import SharedRole
from users.models import User
from users.viewsets import UserViewSet


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

        self.assertEqual(Role.objects.filter(is_system_role=True).count(), 9)
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
        self.assertEqual(Role.objects.filter(is_system_role=True).count(), 9)

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

    def test_tenant_custom_role_name_cannot_duplicate_local_or_shared_role(self):
        with schema_context(get_public_schema_name()):
            SharedRole.objects.update_or_create(
                system_key="student",
                defaults={
                    "role_type": "SYSTEM",
                    "scope": "TENANT",
                    "name": "Student",
                    "description": "Student role",
                    "permissions": [],
                    "is_active": True,
                },
            )

        shared_collision = RoleViewSet.as_view({"post": "create"})(
            self._request(
                "post",
                "/api/v1/authorization/roles/",
                {"name": " student "},
            )
        )
        first = RoleViewSet.as_view({"post": "create"})(
            self._request(
                "post",
                "/api/v1/authorization/roles/",
                {"name": "Data   Entry"},
            )
        )
        duplicate = RoleViewSet.as_view({"post": "create"})(
            self._request(
                "post",
                "/api/v1/authorization/roles/",
                {"name": " data entry "},
            )
        )

        self.assertEqual(shared_collision.status_code, 400, shared_collision.data)
        self.assertEqual(first.status_code, 201, first.data)
        self.assertEqual(first.data["name"], "Data Entry")
        self.assertEqual(duplicate.status_code, 400, duplicate.data)

    def test_tenant_role_list_combines_shared_roles_and_custom_roles_without_duplicates(self):
        with schema_context(get_public_schema_name()):
            SharedRole.objects.update_or_create(
                system_key="accountant",
                defaults={
                    "role_type": "SYSTEM",
                    "scope": "TENANT",
                    "name": "Accountant",
                    "description": "Accountant role",
                    "permissions": [],
                    "is_active": True,
                },
            )
        Role.objects.create(name="Data Entry")

        response = RoleViewSet.as_view({"get": "list"})(
            self._request("get", "/api/v1/authorization/roles/")
        )
        names = [role["name"] for role in response.data["results"]]

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(names.count("Accountant"), 1)
        self.assertIn("Data Entry", names)
        roles_by_name = {role["name"]: role for role in response.data["results"]}
        self.assertEqual(roles_by_name["Accountant"]["source"], "shared")
        self.assertEqual(roles_by_name["Data Entry"]["source"], "tenant")
        self.assertEqual(roles_by_name["Data Entry"]["role_type"], "CUSTOM")
        self.assertTrue(
            all(role.get("role_type") != "SYSTEM" or role.get("scope") in {"TENANT", "GLOBAL"} for role in response.data["results"])
        )

        service_payload = get_unified_role_payloads(schema_name=connection.schema_name)
        self.assertEqual(response.data["results"], service_payload)

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
            first_name="Platform",
            last_name="Superadmin",
            is_platform_superuser=True,
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

    def test_user_role_api_assigns_applicable_shared_role_directly(self):
        target = User.objects.create(
            email="authorization-shared-role-target@example.com",
            username="authorization-shared-role-target",
            id_number="AUTH-SHARED-ROLE-TARGET",
        )
        self.tenant.add_user(target)
        with schema_context(get_public_schema_name()):
            shared_role = SharedRole.objects.create(
                role_type="SYSTEM",
                scope="TENANT",
                system_key="shared_staff",
                name="Shared Staff",
                description="Shared staff role",
                permissions=[{"code": "roles.view", "scope": "all"}],
                is_active=True,
            )

        response = UserRoleView.as_view()(
            self._request(
                "put",
                f"/api/v1/authorization/users/{target.id_number}/role/",
                {"role_id": str(shared_role.pk)},
            ),
            id_number=target.id_number,
        )

        self.assertEqual(response.status_code, 200, response.data)
        membership = TenantMembership.objects.get(user=target)
        self.assertIsNone(membership.role_id)
        self.assertEqual(membership.shared_role_id, shared_role.pk)
        self.assertEqual(response.data["role"]["id"], str(shared_role.pk))

    def test_tenant_access_role_endpoint_assigns_shared_and_custom_roles_by_id(self):
        target = User.objects.create(
            email="authorization-tenant-access-target@example.com",
            username="authorization-tenant-access-target",
            id_number="AUTH-TENANT-ACCESS-TARGET",
        )
        superadmin = User.objects.create(
            email="authorization-tenant-access-super@example.com",
            username="authorization-tenant-access-super",
            id_number="AUTH-TENANT-ACCESS-SUPER",
            is_platform_superuser=True,
        )
        self.tenant.add_user(target)
        custom_role = Role.objects.create(name="Tenant Access Custom")
        with schema_context(get_public_schema_name()):
            shared_role = SharedRole.objects.create(
                role_type="SYSTEM",
                scope="TENANT",
                system_key="tenant_access_shared",
                name="Tenant Access Shared",
                description="Tenant access shared role",
                permissions=[],
                is_active=True,
            )

        shared_request = self._request(
            "put",
            f"/api/v1/auth/users/{target.id_number}/tenants/{self.tenant.schema_name}/role/",
            {"role_id": str(shared_role.pk)},
        )
        force_authenticate(shared_request, user=superadmin)
        shared_response = UserViewSet.as_view({"put": "tenant_role"})(
            shared_request,
            id_number=target.id_number,
            schema_name=self.tenant.schema_name,
        )
        membership = TenantMembership.objects.get(user=target)

        self.assertEqual(shared_response.status_code, 200, shared_response.data)
        self.assertEqual(shared_response.data["role"]["id"], str(shared_role.pk))
        self.assertIsNone(membership.role_id)
        self.assertEqual(membership.shared_role_id, shared_role.pk)

        custom_request = self._request(
            "put",
            f"/api/v1/auth/users/{target.id_number}/tenants/{self.tenant.schema_name}/role/",
            {"role_id": str(custom_role.pk)},
        )
        force_authenticate(custom_request, user=superadmin)
        custom_response = UserViewSet.as_view({"put": "tenant_role"})(
            custom_request,
            id_number=target.id_number,
            schema_name=self.tenant.schema_name,
        )
        membership.refresh_from_db()

        self.assertEqual(custom_response.status_code, 200, custom_response.data)
        self.assertEqual(custom_response.data["role"]["id"], str(custom_role.pk))
        self.assertEqual(membership.role_id, custom_role.pk)
        self.assertIsNone(membership.shared_role_id)

    def test_tenant_role_management_allows_permission_or_admin_or_superadmin(self):
        staff_role = Role.objects.get(system_key="staff")
        admin_role = Role.objects.get(system_key="admin")
        RolePermission.objects.filter(
            role=admin_role,
            permission_code__in=["roles.create", "roles.assign_users"],
        ).application_delete()
        cache.clear()

        target = User.objects.create(
            email="authorization-admin-fallback-target@example.com",
            username="authorization-admin-fallback-target",
            id_number="AUTH-ADMIN-FALLBACK-TARGET",
        )
        staff_user = User.objects.create(
            email="authorization-admin-fallback-staff@example.com",
            username="authorization-admin-fallback-staff",
            id_number="AUTH-ADMIN-FALLBACK-STAFF",
        )
        superadmin = User.objects.create(
            email="authorization-admin-fallback-super@example.com",
            username="authorization-admin-fallback-super",
            id_number="AUTH-ADMIN-FALLBACK-SUPER",
            is_platform_superuser=True,
        )
        self.tenant.add_user(target)
        self.tenant.add_user(staff_user)
        self.tenant.add_user(superadmin)
        TenantMembership.objects.update_or_create(
            user=staff_user,
            defaults={"role": staff_role, "is_active": True},
        )

        create_response = RoleViewSet.as_view({"post": "create"})(
            self._request(
                "post",
                "/api/v1/authorization/roles/",
                {"name": "Admin Managed Role"},
            )
        )
        assign_response = UserRoleView.as_view()(
            self._request(
                "put",
                f"/api/v1/authorization/users/{target.id_number}/role/",
                {"role_id": str(staff_role.pk)},
            ),
            id_number=target.id_number,
        )

        denied_request = self.factory.post(
            "/api/v1/authorization/roles/",
            {"name": "Denied Staff Role"},
            format="json",
        )
        denied_request.tenant = self.tenant
        force_authenticate(denied_request, user=staff_user)
        denied_response = RoleViewSet.as_view({"post": "create"})(denied_request)

        super_request = self.factory.post(
            "/api/v1/authorization/roles/",
            {"name": "Super Admin Managed Role"},
            format="json",
        )
        super_request.tenant = self.tenant
        force_authenticate(super_request, user=superadmin)
        super_response = RoleViewSet.as_view({"post": "create"})(super_request)

        self.assertEqual(create_response.status_code, 201, create_response.data)
        self.assertEqual(assign_response.status_code, 200, assign_response.data)
        self.assertEqual(denied_response.status_code, 403, denied_response.data)
        self.assertEqual(super_response.status_code, 201, super_response.data)

    def test_bulk_user_role_api_assigns_one_role_to_multiple_users(self):
        first = User.objects.create(
            email="authorization-bulk-first@example.com",
            username="authorization-bulk-first",
            id_number="AUTH-BULK-001",
        )
        second = User.objects.create(
            email="authorization-bulk-second@example.com",
            username="authorization-bulk-second",
            id_number="AUTH-BULK-002",
        )
        self.tenant.add_user(first)
        self.tenant.add_user(second)
        role = Role.objects.get(system_key="staff")

        response = BulkUserRoleAssignmentView.as_view()(
            self._request(
                "post",
                "/api/v1/authorization/users/roles/bulk/",
                {"role_id": str(role.pk), "id_numbers": [first.id_number, second.id_number]},
            )
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(len(response.data["assignments"]), 2)
        self.assertEqual(
            set(TenantMembership.objects.filter(user__in=[first, second]).values_list("role_id", flat=True)),
            {role.pk},
        )

    def test_role_users_api_lists_current_memberships(self):
        role = Role.objects.get(system_key="staff")
        target = User.objects.create(
            email="authorization-role-list@example.com",
            username="authorization-role-list",
            id_number="AUTH-ROLE-LIST-001",
        )
        self.tenant.add_user(target)
        assign_user_role(user=target, role=role, actor=self.tenant.owner)

        response = RoleViewSet.as_view({"get": "users"})(
            self._request("get", f"/api/v1/authorization/roles/{role.pk}/users/"),
            pk=role.pk,
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["results"][0]["id_number"], target.id_number)

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
