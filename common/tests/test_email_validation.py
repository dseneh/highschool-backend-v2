from django.test import SimpleTestCase

from common.email_validation import (
    DEFAULT_REQUIRED_EMAIL_MESSAGE,
    is_valid_email,
    require_valid_email,
)


class EmailValidationTests(SimpleTestCase):
    def test_require_valid_email_accepts_valid_email(self):
        email = require_valid_email("  user@example.org  ")
        self.assertEqual(email, "user@example.org")

    def test_require_valid_email_rejects_missing_email(self):
        with self.assertRaisesMessage(ValueError, DEFAULT_REQUIRED_EMAIL_MESSAGE):
            require_valid_email("")

    def test_require_valid_email_rejects_invalid_email(self):
        with self.assertRaisesMessage(ValueError, DEFAULT_REQUIRED_EMAIL_MESSAGE):
            require_valid_email("not-an-email")

    def test_is_valid_email_checks_format(self):
        self.assertTrue(is_valid_email("valid.user@example.org"))
        self.assertFalse(is_valid_email(""))
        self.assertFalse(is_valid_email("invalid"))
