from unittest.mock import patch

from django.test import SimpleTestCase

from users.mfa import generate_recovery_codes, generate_secret, hash_recovery_code, totp, verify_totp


class MFASecurityTests(SimpleTestCase):
    def test_generated_totp_verifies(self):
        secret = generate_secret()
        with patch("users.mfa.time.time", return_value=1_800_000_000):
            code = totp(secret)
            wrong_code = "000000" if code != "000000" else "999999"
            self.assertTrue(verify_totp(secret, code))
            self.assertFalse(verify_totp(secret, wrong_code))

    def test_recovery_codes_are_unique_and_hashable(self):
        codes, hashes = generate_recovery_codes()
        self.assertEqual(len(codes), 8)
        self.assertEqual(len(set(codes)), 8)
        self.assertEqual(len(hashes), 8)
        self.assertEqual(hash_recovery_code(codes[0]), hashes[0])
        self.assertNotIn(codes[0], hashes)
