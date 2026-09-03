from django.test import SimpleTestCase
from rest_framework.test import APIRequestFactory

from api.throttling import SensitiveEndpointRateThrottle


class SensitiveEndpointRateThrottleTests(SimpleTestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.throttle = SensitiveEndpointRateThrottle()

    def test_login_uses_tight_scope(self):
        request = self.factory.post("/api/v1/auth/login/", {})
        self.assertEqual(self.throttle.get_scope(request), "login")

    def test_password_reset_uses_reset_scope(self):
        request = self.factory.post("/api/v1/auth/password/forgot/", {})
        self.assertEqual(self.throttle.get_scope(request), "password_reset")

    def test_activation_routes_share_activation_scope(self):
        for path in (
            "/api/v1/auth/account-activation/verify-code/",
            "/api/v1/auth/account-activation/resend-code/",
        ):
            with self.subTest(path=path):
                request = self.factory.post(path, {})
                self.assertEqual(self.throttle.get_scope(request), "activation")

    def test_public_school_search_has_own_scope(self):
        request = self.factory.get("/api/v1/public/schools/?query=test")
        self.assertEqual(self.throttle.get_scope(request), "public_search")

    def test_regular_api_route_has_no_sensitive_scope(self):
        request = self.factory.get("/api/v1/students/")
        self.assertIsNone(self.throttle.get_scope(request))
