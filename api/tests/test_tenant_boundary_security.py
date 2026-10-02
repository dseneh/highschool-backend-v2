from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase
from rest_framework.exceptions import NotFound
from rest_framework.test import APIRequestFactory

from api.middleware import HeaderBasedTenantMiddleware


class TenantBoundarySecurityTests(SimpleTestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.middleware = HeaderBasedTenantMiddleware(lambda request: None)

    def test_tenant_scoped_api_requires_explicit_tenant_header(self):
        request = self.factory.get("/api/v1/students/")
        self.middleware.request = request
        with self.assertRaises(NotFound) as ctx:
            self.middleware.get_tenant(None, "api.myezyschool.com")
        self.assertIn("tenant", str(ctx.exception.detail).lower())

    def test_finance_api_requires_explicit_tenant_header(self):
        request = self.factory.get("/api/v1/finance/bank-accounts/")
        self.middleware.request = request
        with self.assertRaises(NotFound):
            self.middleware.get_tenant(None, "api.myezyschool.com")

    @patch("api.middleware.Tenant.objects.get")
    def test_public_auth_route_resolves_public_schema_without_tenant_header(self, mock_get):
        public_tenant = SimpleNamespace(schema_name="public")
        mock_get.return_value = public_tenant
        request = self.factory.post("/api/v1/auth/login/", {})
        self.middleware.request = request

        result = self.middleware.get_tenant(None, "api.myezyschool.com")

        self.assertIs(result, public_tenant)
        mock_get.assert_called_with(schema_name="public")

    @patch("api.middleware.Tenant.objects.get")
    def test_public_appearance_ignores_tenant_context(self, mock_get):
        public = SimpleNamespace(schema_name="public")
        mock_get.return_value = public
        for tenant in (None, "parent", "school-a", "unknown-school"):
            headers = {"HTTP_X_TENANT": tenant} if tenant else {}
            self.middleware.request = self.factory.get("/api/v1/public/auth-appearance/", **headers)
            self.assertIs(self.middleware.get_tenant(None, "api.myezyschool.com"), public)
            mock_get.assert_called_with(schema_name="public")
        self.assertTrue(self.middleware._is_blocked_tenant_path_allowed("/api/v1/public/auth-appearance/", "GET"))
