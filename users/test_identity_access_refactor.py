"""Regression coverage for single-identity, multi-scope access behavior."""

from datetime import date

from django.core.exceptions import PermissionDenied
from django_tenants.test.cases import TenantTestCase
from django_tenants.utils import get_public_schema_name, schema_context

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
            return User.objects.create(
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

    def test_public_schema_profile_helpers_do_not_query_tenant_tables(self):
        user = self._user("schema-safe-profile")
        with schema_context(get_public_schema_name()):
            self.assertIsNone(user.get_staff())
            self.assertIsNone(user.get_student())
            self.assertIsNone(user.get_guardian_records())
