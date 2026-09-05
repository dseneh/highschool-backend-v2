from django.test import SimpleTestCase
from rest_framework.permissions import AllowAny, IsAuthenticated

from common.permissions import IsSuperAdmin
from core.views import PublicSchoolSearchView, TenantViewSet


class PublicEndpointSecurityTests(SimpleTestCase):
    def test_school_search_is_intentionally_public(self):
        self.assertEqual(PublicSchoolSearchView.permission_classes, [AllowAny])

    def test_tenant_read_is_public_but_mutations_require_superadmin(self):
        view = TenantViewSet()

        for action in ("list", "retrieve"):
            with self.subTest(action=action):
                view.action = action
                permissions = view.get_permissions()
                self.assertEqual(len(permissions), 1)
                self.assertIsInstance(permissions[0], AllowAny)

        for action in ("create", "update", "partial_update", "destroy"):
            with self.subTest(action=action):
                view.action = action
                permissions = view.get_permissions()
                self.assertEqual(len(permissions), 2)
                self.assertIsInstance(permissions[0], IsAuthenticated)
                self.assertIsInstance(permissions[1], IsSuperAdmin)
