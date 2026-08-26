"""Authentication must reject accounts that hold no explicitly assigned role."""

from django.core.exceptions import ValidationError as DjangoValidationError
from django_tenants.test.cases import TenantTestCase
from django_tenants.utils import get_public_schema_name, schema_context

from authorization.exceptions import NoAssignedRole
from authorization.models import Role, TenantMembership
from authorization.services import NO_ASSIGNED_ROLE_CODE, get_assigned_role, has_assigned_role
from users.serializers import MultiFieldTokenObtainPairSerializer
from users.tenant_access import user_has_tenant_workspace_access

PASSWORD = "role-required-pass-123"


class RoleRequiredLoginTests(TenantTestCase):
    @classmethod
    def setup_tenant(cls, tenant):
        from users.models import User

        tenant.name = "Role Required School"
        tenant.short_name = "roles"
        tenant.owner, _ = User.objects.get_or_create(
            email="role-required-owner@example.com",
            defaults={
                "username": "role-required-owner",
                "id_number": "ROLE-REQUIRED-OWNER",
                "account_type": "staff",
                "first_name": "Role",
                "last_name": "Owner",
            },
        )

    def _user(self, suffix, *, platform_superuser=False):
        from users.models import User

        user = User.objects.create(
            email=f"{suffix}@example.com",
            username=suffix,
            id_number=suffix.upper(),
            first_name="Test",
            last_name="User",
            account_type="staff",
            is_active=True,
            is_platform_superuser=platform_superuser,
        )
        user.set_password(PASSWORD)
        user.save(update_fields=["password"])
        return user

    def _login(self, user):
        serializer = MultiFieldTokenObtainPairSerializer(
            data={"username": user.username, "password": PASSWORD}
        )
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data

    def _grant(self, user, system_key="staff"):
        from authorization.services import assign_user_role

        self.tenant.add_user(user)
        role = Role.objects.get(system_key=system_key)
        assign_user_role(user=user, role=role)
        return role

    def test_login_is_rejected_when_no_role_is_assigned(self):
        user = self._user("no-role-user")
        self.tenant.add_user(user)

        self.assertIsNone(get_assigned_role(user))
        self.assertFalse(has_assigned_role(user))
        with self.assertRaises(NoAssignedRole) as raised:
            self._login(user)
        self.assertEqual(raised.exception.error_code, NO_ASSIGNED_ROLE_CODE)

    def test_rejected_login_issues_no_credentials(self):
        user = self._user("no-token-user")
        self.tenant.add_user(user)

        serializer = MultiFieldTokenObtainPairSerializer(
            data={"username": user.username, "password": PASSWORD}
        )
        with self.assertRaises(NoAssignedRole):
            serializer.is_valid(raise_exception=True)
        self.assertFalse(getattr(serializer, "_validated_data", None))

    def test_tenant_membership_is_never_seeded_with_a_default_role(self):
        user = self._user("no-default-role-user")
        self.tenant.add_user(user)

        self.assertFalse(TenantMembership.objects.filter(user=user).exists())

    def test_inactive_membership_is_not_a_usable_role(self):
        user = self._user("inactive-membership-user")
        self._grant(user)
        membership = TenantMembership.objects.get(user=user)
        membership.is_active = False
        membership.save(update_fields=["is_active"])

        self.assertIsNone(get_assigned_role(user))
        with self.assertRaises(NoAssignedRole):
            self._login(user)

    def test_login_succeeds_and_returns_the_assigned_role(self):
        user = self._user("assigned-role-user")
        role = self._grant(user)

        payload = self._login(user)
        self.assertIn("access", payload)
        self.assertEqual(payload["user"]["rbac_role"]["system_key"], role.system_key)

    def test_platform_superadmin_signs_in_on_its_explicit_platform_grant(self):
        user = self._user("platform-superadmin-user", platform_superuser=True)

        self.assertTrue(has_assigned_role(user))
        payload = self._login(user)
        self.assertIn("access", payload)
        self.assertTrue(payload["user"]["is_platform_superuser"])

    def test_platform_superadmin_is_seeded_with_the_superadmin_role(self):
        from authorization.services import ensure_tenant_user_membership

        user = self._user("seeded-superadmin-user", platform_superuser=True)
        ensure_tenant_user_membership(user)

        role = get_assigned_role(user)
        self.assertIsNotNone(role)
        self.assertEqual(role.system_key, "superadmin")

    def test_superadmin_role_cannot_be_assigned_to_anyone(self):
        from authorization.services import assign_user_role

        user = self._user("escalation-attempt-user")
        self.tenant.add_user(user)
        superadmin_role = Role.objects.get(system_key="superadmin")

        with self.assertRaises(DjangoValidationError):
            assign_user_role(user=user, role=superadmin_role)

    def test_workspace_access_requires_an_assigned_role(self):
        user = self._user("workspace-access-user")
        self._grant(user)

        self.assertTrue(user_has_tenant_workspace_access(user, self.tenant))

        TenantMembership.objects.filter(user=user).delete()
        self.assertFalse(user_has_tenant_workspace_access(user, self.tenant))

    def test_central_login_requires_a_role_in_at_least_one_workspace(self):
        user = self._user("central-login-user")
        self._grant(user)
        tenant_schema = self.tenant.schema_name

        with schema_context(get_public_schema_name()):
            self.assertTrue(has_assigned_role(user))

        with schema_context(tenant_schema):
            TenantMembership.objects.filter(user=user).delete()
        with schema_context(get_public_schema_name()):
            self.assertFalse(has_assigned_role(user))

    def test_deactivated_role_removes_every_assignment_that_uses_it(self):
        user = self._user("deactivated-role-user")
        self._grant(user)
        custom_role = Role.objects.create(
            name="Temporary Reviewer",
            description="Custom role used to verify deactivation handling.",
        )
        membership = TenantMembership.objects.get(user=user)
        membership.role = custom_role
        membership.save(update_fields=["role"])
        self.assertEqual(get_assigned_role(user), custom_role)

        custom_role.is_active = False
        custom_role.save(update_fields=["is_active"])

        self.assertIsNone(get_assigned_role(user))
        with self.assertRaises(NoAssignedRole):
            self._login(user)
