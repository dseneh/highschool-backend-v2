from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from core.account_discovery import (
    MAX_VERIFY_ATTEMPTS,
    NormalizedIdentifier,
    allow_request,
    normalize_identifier,
    verify_challenge,
)


@override_settings(
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
)
class AccountDiscoverySecurityTests(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def test_normalizes_liberian_local_phone(self):
        self.assertEqual(
            normalize_identifier("077 123 4567"),
            NormalizedIdentifier("phone", "231771234567"),
        )

    def test_rejects_invalid_identifier(self):
        with self.assertRaises(ValueError):
            normalize_identifier("not an id!")

    def test_rate_limit_is_enforced(self):
        self.assertTrue(allow_request("test", "value", limit=2, window=60))
        self.assertTrue(allow_request("test", "value", limit=2, window=60))
        self.assertFalse(allow_request("test", "value", limit=2, window=60))

    def test_verification_is_single_use(self):
        import hashlib

        challenge_id = "challenge"
        code = "123456"
        cache.set(
            f"account-discovery:challenge:{challenge_id}",
            {
                "code_hash": hashlib.sha256(f"{challenge_id}:{code}".encode()).hexdigest(),
                "accounts": [{"workspace": "demo"}],
                "attempts": 0,
            },
            60,
        )
        self.assertIsNotNone(verify_challenge(challenge_id, code))
        self.assertIsNone(verify_challenge(challenge_id, code))

    def test_too_many_wrong_codes_invalidates_challenge(self):
        import hashlib

        challenge_id = "challenge"
        cache.set(
            f"account-discovery:challenge:{challenge_id}",
            {
                "code_hash": hashlib.sha256(f"{challenge_id}:123456".encode()).hexdigest(),
                "accounts": [],
                "attempts": 0,
            },
            60,
        )
        for _ in range(MAX_VERIFY_ATTEMPTS):
            self.assertIsNone(verify_challenge(challenge_id, "000000"))
        self.assertIsNone(verify_challenge(challenge_id, "123456"))
