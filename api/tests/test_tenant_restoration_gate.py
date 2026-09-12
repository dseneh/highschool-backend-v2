from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from api.middleware import HeaderBasedTenantMiddleware


class TenantRestorationGateTests(SimpleTestCase):
    def setUp(self):
        self.middleware = HeaderBasedTenantMiddleware(lambda request: None)

    def test_restore_blocks_every_tenant_user_before_admin_overrides(self):
        request = SimpleNamespace(
            path="/api/v1/students/",
            tenant=SimpleNamespace(
                schema_name="demo",
                active=False,
                status="active",
                maintenance_mode=True,
                restoration_in_progress=True,
            ),
        )

        response = self.middleware._enforce_tenant_runtime_controls(request)

        self.assertEqual(response.status_code, 423)
        self.assertIn(b"TENANT_RESTORE_IN_PROGRESS", response.content)
        self.assertEqual(response["Retry-After"], "10")

    def test_runtime_status_endpoint_remains_available_for_polling(self):
        request = SimpleNamespace(
            path="/api/v1/tenants/current/",
            tenant=SimpleNamespace(
                schema_name="demo",
                restoration_in_progress=True,
            ),
        )

        self.assertIsNone(self.middleware._enforce_tenant_runtime_controls(request))


    @patch("api.middleware.Tenant.objects.get")
    def test_runtime_status_endpoint_honors_tenant_header(self, get_tenant):
        tenant = SimpleNamespace(schema_name="demo")
        get_tenant.return_value = tenant
        self.middleware.request = SimpleNamespace(
            path="/api/v1/tenants/current/",
            META={"HTTP_X_TENANT": "demo"},
        )

        resolved = self.middleware.get_tenant(SimpleNamespace(), "api.staging.myezyschool.com")

        self.assertIs(resolved, tenant)
        get_tenant.assert_called_once_with(schema_name="demo")
