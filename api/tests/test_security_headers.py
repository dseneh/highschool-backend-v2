from django.http import HttpResponse, JsonResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from api.middleware import SecurityResponseHeadersMiddleware


class SecurityResponseHeadersMiddlewareTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _response(self, path, response=None):
        middleware = SecurityResponseHeadersMiddleware(
            lambda request: response or JsonResponse({"ok": True})
        )
        return middleware(self.factory.get(path))

    def test_api_response_has_restrictive_security_headers(self):
        response = self._response("/api/v1/students/")

        self.assertEqual(response["Referrer-Policy"], "no-referrer")
        self.assertEqual(
            response["Permissions-Policy"],
            "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
        )
        self.assertEqual(response["X-Permitted-Cross-Domain-Policies"], "none")
        self.assertEqual(
            response["Content-Security-Policy"],
            "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
        )

    def test_auth_response_is_not_cacheable(self):
        response = self._response("/api/v1/auth/login/")

        self.assertEqual(response["Cache-Control"], "no-store")
        self.assertEqual(response["Pragma"], "no-cache")

    def test_non_api_html_response_does_not_receive_api_csp(self):
        response = self._response("/admin/", HttpResponse("admin"))

        self.assertNotIn("Content-Security-Policy", response)
        self.assertIn("Permissions-Policy", response)

    @override_settings(
        SECURE_REFERRER_POLICY="same-origin",
        SECURITY_PERMISSIONS_POLICY="camera=(self)",
        API_CONTENT_SECURITY_POLICY="default-src 'self'",
    )
    def test_header_policies_are_configurable(self):
        response = self._response("/api/v1/students/")

        self.assertEqual(response["Referrer-Policy"], "same-origin")
        self.assertEqual(response["Permissions-Policy"], "camera=(self)")
        self.assertEqual(response["Content-Security-Policy"], "default-src 'self'")

    def test_existing_upstream_headers_are_not_overwritten(self):
        upstream = JsonResponse({"ok": True})
        upstream["Content-Security-Policy"] = "default-src 'self'"
        upstream["Cache-Control"] = "private"

        response = self._response("/api/v1/auth/login/", upstream)

        self.assertEqual(response["Content-Security-Policy"], "default-src 'self'")
        self.assertEqual(response["Cache-Control"], "private")
