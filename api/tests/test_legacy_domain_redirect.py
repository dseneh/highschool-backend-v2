"""
Tests for LegacyDomainRedirectMiddleware.

Verifies that requests to the legacy `ezyschool.app` / `ezyschool.net` domains
are permanently redirected to the current APP_ROOT_DOMAIN, preserving the
tenant subdomain, full nested path, and query string.
"""

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from api.middleware import LegacyDomainRedirectMiddleware


def _get_response(request):
    return HttpResponse("ok")


@override_settings(APP_ROOT_DOMAIN="myezyschool.com", LEGACY_APP_DOMAINS=["ezyschool.app", "ezyschool.net"])
class LegacyDomainRedirectMiddlewareTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = LegacyDomainRedirectMiddleware(_get_response)

    def test_redirects_root_domain_to_new_root_domain(self):
        request = self.factory.get("/login", HTTP_HOST="ezyschool.app")
        response = self.middleware(request)

        self.assertEqual(response.status_code, 308)
        self.assertEqual(response["Location"], "http://myezyschool.com/login")

    def test_redirects_deep_nested_route_preserving_full_path(self):
        request = self.factory.get(
            "/students/123/grades", HTTP_HOST="ezyschool.app"
        )
        response = self.middleware(request)

        self.assertEqual(response.status_code, 308)
        self.assertEqual(response["Location"], "http://myezyschool.com/students/123/grades")

    def test_preserves_query_parameters_on_redirect(self):
        request = self.factory.get(
            "/students/123/grades?year=2026", HTTP_HOST="ezyschool.app"
        )
        response = self.middleware(request)

        self.assertEqual(response.status_code, 308)
        self.assertEqual(
            response["Location"],
            "http://myezyschool.com/students/123/grades?year=2026",
        )

    def test_redirects_tenant_subdomain_preserving_subdomain_path_and_query(self):
        request = self.factory.get(
            "/students/123/grades?year=2026", HTTP_HOST="dujar.ezyschool.app"
        )
        response = self.middleware(request)

        self.assertEqual(response.status_code, 308)
        self.assertEqual(
            response["Location"],
            "http://dujar.myezyschool.com/students/123/grades?year=2026",
        )

    def test_also_redirects_the_older_legacy_net_domain(self):
        request = self.factory.get("/login", HTTP_HOST="ezyschool.net")
        response = self.middleware(request)

        self.assertEqual(response.status_code, 308)
        self.assertEqual(response["Location"], "http://myezyschool.com/login")

    def test_does_not_redirect_requests_already_on_the_current_root_domain(self):
        request = self.factory.get("/login", HTTP_HOST="myezyschool.com")
        response = self.middleware(request)

        self.assertEqual(response.status_code, 200)

    def test_does_not_redirect_tenant_subdomains_on_the_current_root_domain(self):
        request = self.factory.get("/login", HTTP_HOST="dujar.myezyschool.com")
        response = self.middleware(request)

        self.assertEqual(response.status_code, 200)
