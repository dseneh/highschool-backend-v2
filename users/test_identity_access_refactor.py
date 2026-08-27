"""Regression coverage for single-identity, multi-scope access behavior."""

from datetime import date
from types import SimpleNamespace

from django.core.exceptions import PermissionDenied
from django.http import QueryDict
from django_tenants.test.cases import TenantTestCase
from django_tenants.utils import get_public_schema_name, schema_context
from rest_framework.test import APIRequestFactory, force_authenticate

from common.status import UserAccountScope
from users.access_service import (
    disable_platform_access,
    enable_platform_access,
    has_any_assigned_role,
    has_platform_role,
    hire_platform_employee,
    sync_account_scope,
    terminate_platform_employee,
)

PASSWORD = "Identity-access-pass-123"


class IdentityAccessRefactorTests(TenantTestCase):
    @classmethod
    def setup_tenant(cls, tenant):
        from users.models import User

        tenant.name = "Identity Refactor School"
        tenant.short_name = "identity"
        tenant.owner, _ = User.objects.get_or_create(
            email="identity-owner@example.com",
            defaults={
                "username": "identity-owner",
                "id_number": "IDENTITY-OWNER",
                "account_type": "staff",
                "first_name": "Identity",
                "last_name": "Owner",
            },
        )

    def _user(self, suffix, *, superadmin=False, account_type="staff"):
        from users.models import User

        with schema_context(get_public_schema_name()):
            user = User.objects.create(
                email=f"{suffix}@example.com",
                username=suffix,
                id_number=suffix.upper(),
                first_name="Test",
                last_name="User",
                account_type=account_type,
                account_scope=UserAccountScope.TENANT.value,
                is_active=True,
                is_platform_superuser=superadmin,
            )
            user.set_password(PASSWORD)
            user.save(update_fields=["password"])
            return user

    def _public_role(self, name="Platform Support"):
        from core.models import SharedRole

        with schema_context(get_public_schema_name()):
            return SharedRole.objects.create(
                role_type=SharedRole.RoleType.CUSTOM,
                scope=SharedRole.Scope.PUBLIC,
                name=name,
                description="Test public role",
                permissions=[],
                is_active=True,
            )

    def _tenant_role(self, user):
        from authorization.models import Role
        from authorization.services import assign_user_role

        self.tenant.add_user(user)
        with schema_context(self.tenant.schema_name):
            role = Role.objects.create(name=f"Tenant Role {user.id_number}")
            assign_user_role(user=user, role=role)
        return role

    def test_platform_role_is_independent_of_primary_persona(self):
        actor = self._user("platform-admin", superadmin=True)
        user = self._user("existing-school-staff", account_type="staff")
        role = self._public_role()

        enable_platform_access(user=user, role=role.pk, actor=actor)
        with schema_context(get_public_schema_name()):
            user.refresh_from_db()
            self.assertEqual(user.account_type, "staff")
            self.assertEqual(user.account_scope, UserAccountScope.PLATFORM.value)
            self.assertTrue(has_platform_role(user))
            self.assertTrue(has_any_assigned_role(user))

    def test_platform_only_user_can_login_with_public_role(self):
        from users.serializers import MultiFieldTokenObtainPairSerializer

        actor = self._user("login-admin", superadmin=True)
        user = self._user("platform-only-login", account_type="other")
        role = self._public_role("Platform Login Role")
        enable_platform_access(user=user, role=role.pk, actor=actor)

        with schema_context(get_public_schema_name()):
            serializer = MultiFieldTokenObtainPairSerializer(
                data={"username": user.username, "password": PASSWORD}
            )
            serializer.is_valid(raise_exception=True)
            payload = serializer.validated_data
            self.assertIn("access", payload)
            self.assertEqual(payload["user"]["account_scope"], UserAccountScope.PLATFORM.value)
            self.assertEqual(payload["user"]["rbac_role"]["id"], str(role.pk))

    def test_platform_and_tenant_roles_produce_combined_scope(self):
        actor = self._user("combined-admin", superadmin=True)
        user = self._user("combined-user")
        self._tenant_role(user)
        role = self._public_role("Combined Platform Role")

        enable_platform_access(user=user, role=role.pk, actor=actor)
        sync_account_scope(user)

        with schema_context(get_public_schema_name()):
            user.refresh_from_db()
            self.assertEqual(user.account_scope, UserAccountScope.PLATFORM_AND_TENANT.value)

    def test_revoking_platform_access_preserves_tenant_access(self):
        actor = self._user("revoke-admin", superadmin=True)
        user = self._user("tenant-preserved")
        self._tenant_role(user)
        role = self._public_role("Temporary Platform Role")
        enable_platform_access(user=user, role=role.pk, actor=actor)

        disable_platform_access(user=user, actor=actor)

        with schema_context(get_public_schema_name()):
            user.refresh_from_db()
            self.assertEqual(user.account_scope, UserAccountScope.TENANT.value)
            self.assertFalse(has_platform_role(user))
            self.assertTrue(has_any_assigned_role(user))

    def test_platform_operator_does_not_leak_into_normal_tenant_user_list(self):
        from users.scoped_viewset import ScopedUserViewSet

        tenant_viewer = self._user("tenant-viewer")
        self._tenant_role(tenant_viewer)

        operator = self._user("platform-operator", account_type="other")
        self._tenant_role(operator)
        platform_role = self._public_role("Cross Tenant Support")
        platform_admin = self._user("list-platform-admin", superadmin=True)
        enable_platform_access(user=operator, role=platform_role.pk, actor=platform_admin)

        with schema_context(self.tenant.schema_name):
            view = ScopedUserViewSet()
            view.request = SimpleNamespace(user=tenant_viewer, query_params=QueryDict(""))
            view.action = "list"
            visible_ids = set(view.get_queryset().values_list("id_number", flat=True))
            self.assertNotIn(operator.id_number, visible_ids)
            self.assertIn(tenant_viewer.id_number, visible_ids)

            superadmin_view = ScopedUserViewSet()
            superadmin_view.request = SimpleNamespace(user=platform_admin, query_params=QueryDict(""))
            superadmin_view.action = "list"
            superadmin_ids = set(
                superadmin_view.get_queryset().values_list("id_number", flat=True)
            )
            self.assertIn(operator.id_number, superadmin_ids)

    def test_platform_and_tenant_user_remains_visible_in_public_admin_list(self):
        from users.scoped_viewset import ScopedUserViewSet

        actor = self._user("public-list-admin", superadmin=True)
        user = self._user("public-combined-user")
        self._tenant_role(user)
        role = self._public_role("Public Combined Role")
        enable_platform_access(user=user, role=role.pk, actor=actor)

        with schema_context(get_public_schema_name()):
            view = ScopedUserViewSet()
            view.request = SimpleNamespace(user=actor, query_params=QueryDict(""))
            view.action = "list"
            visible_ids = set(view.get_queryset().values_list("id_number", flat=True))
            self.assertIn(user.id_number, visible_ids)

    def test_new_platform_user_is_not_created_as_global_or_superadmin(self):
        from users.access_views import PlatformUserCreateView
        from users.models import User

        actor = self._user("create-platform-admin", superadmin=True)
        role = self._public_role("New Platform User Role")
        request = APIRequestFactory().post(
            "/auth/users/global/",
            {
                "email": "new-platform-user@example.com",
                "first_name": "Platform",
                "last_name": "User",
                "gender": "female",
                "role": str(role.pk),
                "notify_user": False,
            },
            format="json",
        )
        force_authenticate(request, user=actor)
        response = PlatformUserCreateView.as_view()(request)

        self.assertEqual(response.status_code, 201)
        with schema_context(get_public_schema_name()):
            created = User.objects.get(email="new-platform-user@example.com")
            self.assertEqual(created.account_type, "other")
            self.assertEqual(created.account_scope, UserAccountScope.PLATFORM.value)
            self.assertFalse(created.is_platform_superuser)
            self.assertTrue(has_platform_role(created))

    def test_platform_employment_does_not_replace_tenant_persona(self):
        actor = self._user("employment-admin", superadmin=True)
        user = self._user("teacher-hired-by-platform", account_type="staff")

        employment = hire_platform_employee(
            user=user,
            actor=actor,
            employee_number="EZY-1001",
            position="Support Engineer",
            department="Technology",
            hire_date=date(2026, 8, 27),
        )

        with schema_context(get_public_schema_name()):
            user.refresh_from_db()
            employment.refresh_from_db()
            self.assertEqual(user.account_type, "staff")
            self.assertEqual(employment.status, "active")
            self.assertEqual(employment.position, "Support Engineer")

    def test_termination_keeps_platform_employment_history(self):
        actor = self._user("termination-admin", superadmin=True)
        user = self._user("departing-platform-employee")
        employment = hire_platform_employee(
            user=user,
            actor=actor,
            employee_number="EZY-1002",
            hire_date=date(2026, 1, 1),
        )

        terminate_platform_employee(
            user=user,
            actor=actor,
            termination_date=date(2026, 8, 27),
            revoke_access=False,
        )

        with schema_context(get_public_schema_name()):
            employment.refresh_from_db()
            self.assertEqual(employment.status, "terminated")
            self.assertEqual(employment.termination_date, date(2026, 8, 27))
            self.assertTrue(type(employment).objects.filter(pk=employment.pk).exists())

    def test_normal_user_cannot_grant_platform_access(self):
        actor = self._user("ordinary-actor")
        target = self._user("privilege-target")
        role = self._public_role("Protected Platform Role")

        with self.assertRaises(PermissionDenied):
            enable_platform_access(user=target, role=role.pk, actor=actor)

    def test_normal_user_serializers_cannot_set_platform_superuser(self):
        from users.serializers import UserCreateSerializer, UserUpdateSerializer

        create = UserCreateSerializer(data={
            "email": "serializer-protected@example.com",
            "username": "serializer-protected",
            "id_number": "SERIALIZER-PROTECTED",
            "first_name": "Protected",
            "last_name": "User",
            "gender": "male",
            "account_type": "other",
            "is_active": True,
            "is_platform_superuser": True,
        })
        create.is_valid(raise_exception=True)
        created = create.save()
        self.assertFalse(created.is_platform_superuser)

        update = UserUpdateSerializer(
            created,
            data={"is_platform_superuser": True},
            partial=True,
        )
        update.is_valid(raise_exception=True)
        updated = update.save()
        self.assertFalse(updated.is_platform_superuser)

    def test_public_schema_profile_helpers_do_not_query_tenant_tables(self):
        user = self._user("schema-safe-profile")
        with schema_context(get_public_schema_name()):
            self.assertIsNone(user.get_staff())
            self.assertIsNone(user.get_student())
            self.assertIsNone(user.get_guardian_records())
