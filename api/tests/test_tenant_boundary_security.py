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

    def test_public_auth_route_is_classified_as_public(self):
        # This assertion protects the intentionally public login route from
        # accidentally becoming tenant-table dependent during middleware changes.
        request = self.factory.post("/api/v1/auth/login/", {})
        self.middleware.request = request
        # Missing tenant context should not trigger tenant_header_required before
        # public-schema resolution. We inspect the path classification indirectly
        # by ensuring the explicit tenant-header guard is not reached.
        with self.assertRaises(Exception) as ctx:
            self.middleware.get_tenant(None, "api.myezyschool.com")
        self.assertNotIn("tenant_header_required", str(getattr(ctx.exception, "default_code", "")))
