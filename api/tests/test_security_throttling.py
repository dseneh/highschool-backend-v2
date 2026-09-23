from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase
from rest_framework.test import APIRequestFactory

from api.throttling import (
    SensitiveEndpointRateThrottle,
    claim_fixed_window_rate_limit,
    opaque_rate_limit_subject,
)


class SensitiveEndpointRateThrottleTests(SimpleTestCase):
    def setUp(self):
        cache.clear()
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

    def test_sensitive_route_enforces_configured_limit(self):
        request = self.factory.post("/api/v1/auth/login/", {}, REMOTE_ADDR="192.0.2.10")
        rates = {**self.throttle.THROTTLE_RATES, "login": "2/min"}

        with patch.object(SensitiveEndpointRateThrottle, "THROTTLE_RATES", rates):
            self.assertTrue(self.throttle.allow_request(request, None))
            self.assertTrue(SensitiveEndpointRateThrottle().allow_request(request, None))
            self.assertFalse(SensitiveEndpointRateThrottle().allow_request(request, None))

    def test_regular_route_is_not_recorded_by_sensitive_throttle(self):
        request = self.factory.get("/api/v1/students/", REMOTE_ADDR="192.0.2.11")
        self.assertTrue(self.throttle.allow_request(request, None))

    def test_account_limit_is_enforced_across_requests(self):
        kwargs = {
            "namespace": "password-reset-account:school-a",
            "subject": "user:123",
            "limit": 3,
            "window_seconds": 3600,
        }

        self.assertTrue(claim_fixed_window_rate_limit(**kwargs))
        self.assertTrue(claim_fixed_window_rate_limit(**kwargs))
        self.assertTrue(claim_fixed_window_rate_limit(**kwargs))
        self.assertFalse(claim_fixed_window_rate_limit(**kwargs))

    def test_account_limits_are_tenant_and_subject_isolated(self):
        common = {"limit": 1, "window_seconds": 3600}

        self.assertTrue(
            claim_fixed_window_rate_limit(
                namespace="mfa-recovery-account:school-a",
                subject="user:123",
                **common,
            )
        )
        self.assertFalse(
            claim_fixed_window_rate_limit(
                namespace="mfa-recovery-account:school-a",
                subject="user:123",
                **common,
            )
        )
        self.assertTrue(
            claim_fixed_window_rate_limit(
                namespace="mfa-recovery-account:school-b",
                subject="user:123",
                **common,
            )
        )
        self.assertTrue(
            claim_fixed_window_rate_limit(
                namespace="mfa-recovery-account:school-a",
                subject="user:456",
                **common,
            )
        )

    def test_subject_digest_does_not_retain_email_address(self):
        digest = opaque_rate_limit_subject("Person@Example.com")

        self.assertNotIn("person", digest)
        self.assertNotIn("example", digest)
        self.assertEqual(len(digest), 64)
