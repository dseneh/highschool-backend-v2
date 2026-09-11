from types import SimpleNamespace

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
