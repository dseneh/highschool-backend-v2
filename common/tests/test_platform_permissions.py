from types import SimpleNamespace

from django.test import SimpleTestCase

from common.permissions import IsAdminOrSuperAdmin, IsSuperAdmin


class PlatformPermissionTests(SimpleTestCase):
    def request_for(self, *, platform_superuser=False, framework_superuser=False):
        return SimpleNamespace(
            user=SimpleNamespace(
                is_authenticated=True,
                is_platform_superuser=platform_superuser,
                is_superuser=framework_superuser,
            )
        )

    def test_platform_superuser_is_allowed(self):
        request = self.request_for(platform_superuser=True)

        self.assertTrue(IsSuperAdmin().has_permission(request, None))
        self.assertTrue(IsAdminOrSuperAdmin().has_permission(request, None))

    def test_framework_superuser_flag_does_not_grant_platform_access(self):
        request = self.request_for(framework_superuser=True)

        self.assertFalse(IsSuperAdmin().has_permission(request, None))
        self.assertFalse(IsAdminOrSuperAdmin().has_permission(request, None))