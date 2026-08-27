from datetime import date

from django_tenants.test.cases import TenantTestCase
from django_tenants.utils import get_public_schema_name, schema_context
from rest_framework.test import APIRequestFactory, force_authenticate


PASSWORD = "Workspace-role-pass-123"


class PlatformLifecycleHardeningTests(TenantTestCase):
    @classmethod
    def setup_tenant(cls, tenant):
        from users.models import User

        tenant.name = "Platform Lifecycle School"
        tenant.short_name = "platform-lifecycle"
        tenant.owner, _ = User.objects.get_or_create(
            email="platform-lifecycle-owner@example.com",
            defaults={
                "username": "platform-lifecycle-owner",
                "id_number": "PLATFORM-LIFECYCLE-OWNER",
                "account_type": "staff",
            },
        )

    def _user(self, suffix, *, superadmin=False):
        from users.models import User

        with schema_context(get_public_schema_name()):
            user = User.objects.create(
                email=f"{suffix}@example.com",
                username=suffix,
                id_number=suffix.upper(),
                account_type="other",
                account_scope="tenant",
                is_active=True,
                is_platform_superuser=superadmin,
            )
            user.set_password(PASSWORD)
            user.save(update_fields=["password"])
            return user

    def _tenant_role(self, user):
        from authorization.models import Role
        from authorization.services import assign_user_role

        self.tenant.add_user(user)
        with schema_context(self.tenant.schema_name):
            role = Role.objects.create(name=f"Tenant Role {user.id_number}")
            assign_user_role(user=user, role=role)
            return role

    def _request(self, method, path, actor, data=None):
        factory = APIRequestFactory()
        request = getattr(factory, method)(path, data or {}, format="json")
        force_authenticate(request, user=actor)
        return request

    def test_platform_access_rejects_self_management(self):
        from users.access_views import PlatformAccessView

        actor = self._user("self-manager", superadmin=True)
        request = self._request(
            "post",
            f"/auth/users/{actor.id_number}/platform-access/",
            actor,
            {"role": "ignored"},
        )
        response = PlatformAccessView.as_view()(request, id_number=actor.id_number)
        self.assertEqual(response.status_code, 403)

    def test_platform_access_rejects_superadmin_target(self):
        from users.access_views import PlatformAccessView

        actor = self._user("superadmin-actor", superadmin=True)
        target = self._user("superadmin-target", superadmin=True)
        request = self._request(
            "post",
            f"/auth/users/{target.id_number}/platform-access/",
            actor,
            {"role": "ignored"},
        )
        response = PlatformAccessView.as_view()(request, id_number=target.id_number)
        self.assertEqual(response.status_code, 403)

    def test_duplicate_platform_employee_number_is_rejected(self):
        from users.access_views import PlatformEmploymentView
        from users.models import PlatformEmployee

        actor = self._user("employment-actor", superadmin=True)
        existing = self._user("existing-employee")
        target = self._user("new-employee")
        with schema_context(get_public_schema_name()):
            PlatformEmployee.objects.create(
                user=existing,
                employee_number="EZY-9001",
                status=PlatformEmployee.EmploymentStatus.ACTIVE,
            )

        request = self._request(
            "post",
            f"/auth/users/{target.id_number}/platform-employment/",
            actor,
            {"employee_number": "ezy-9001", "hire_date": "2026-08-27"},
        )
        response = PlatformEmploymentView.as_view()(request, id_number=target.id_number)
        self.assertEqual(response.status_code, 409)

    def test_termination_before_hire_date_is_rejected(self):
        from users.access_views import PlatformEmploymentView
        from users.models import PlatformEmployee

        actor = self._user("termination-actor", superadmin=True)
        target = self._user("termination-target")
        with schema_context(get_public_schema_name()):
            PlatformEmployee.objects.create(
                user=target,
                employee_number="EZY-9002",
                hire_date=date(2026, 8, 27),
                status=PlatformEmployee.EmploymentStatus.ACTIVE,
            )

        request = self._request(
            "delete",
            f"/auth/users/{target.id_number}/platform-employment/",
            actor,
            {"termination_date": "2026-08-26", "revoke_access": False},
        )
        response = PlatformEmploymentView.as_view()(request, id_number=target.id_number)
        self.assertEqual(response.status_code, 400)

    def test_already_terminated_employment_cannot_be_terminated_again(self):
        from users.access_views import PlatformEmploymentView
        from users.models import PlatformEmployee

        actor = self._user("terminated-actor", superadmin=True)
        target = self._user("terminated-target")
        with schema_context(get_public_schema_name()):
            PlatformEmployee.objects.create(
                user=target,
                employee_number="EZY-9003",
                hire_date=date(2026, 1, 1),
                termination_date=date(2026, 8, 1),
                status=PlatformEmployee.EmploymentStatus.TERMINATED,
            )

        request = self._request(
            "delete",
            f"/auth/users/{target.id_number}/platform-employment/",
            actor,
            {"termination_date": "2026-08-27"},
        )
        response = PlatformEmploymentView.as_view()(request, id_number=target.id_number)
        self.assertEqual(response.status_code, 409)

    def test_normal_user_create_rejects_legacy_global_persona(self):
        from users.serializers import UserCreateSerializer

        serializer = UserCreateSerializer(
            data={
                "email": "legacy-global-create@example.com",
                "username": "legacy-global-create",
                "id_number": "LEGACY-GLOBAL-CREATE",
                "first_name": "Legacy",
                "last_name": "Global",
                "account_type": "global",
                "is_active": True,
            }
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("account_type", serializer.errors)

    def test_normal_user_update_rejects_legacy_global_persona(self):
        from users.serializers import UserUpdateSerializer

        target = self._user("legacy-global-update")
        serializer = UserUpdateSerializer(
            target,
            data={"account_type": "global"},
            partial=True,
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("account_type", serializer.errors)

    def test_tenant_only_role_cannot_login_to_public_workspace(self):
        from authorization.exceptions import NoAssignedRole
        from users.serializers import MultiFieldTokenObtainPairSerializer

        user = self._user("tenant-only-public-login")
        self._tenant_role(user)

        with schema_context(get_public_schema_name()):
            serializer = MultiFieldTokenObtainPairSerializer(
                data={"username": user.username, "password": PASSWORD}
            )
            with self.assertRaises(NoAssignedRole):
                serializer.is_valid(raise_exception=True)

    def test_tenant_role_can_login_to_its_tenant_workspace(self):
        from users.serializers import MultiFieldTokenObtainPairSerializer

        user = self._user("tenant-workspace-login")
        role = self._tenant_role(user)

        with schema_context(self.tenant.schema_name):
            serializer = MultiFieldTokenObtainPairSerializer(
                data={"username": user.username, "password": PASSWORD}
            )
            serializer.is_valid(raise_exception=True)
            payload = serializer.validated_data
            self.assertEqual(payload["user"]["rbac_role"]["id"], str(role.pk))
