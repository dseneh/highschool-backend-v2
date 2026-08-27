from datetime import date

from django_tenants.test.cases import TenantTestCase
from django_tenants.utils import get_public_schema_name, schema_context
from rest_framework.test import APIRequestFactory, force_authenticate


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
            return User.objects.create(
                email=f"{suffix}@example.com",
                username=suffix,
                id_number=suffix.upper(),
                account_type="other",
                account_scope="tenant",
                is_active=True,
                is_platform_superuser=superadmin,
            )

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
