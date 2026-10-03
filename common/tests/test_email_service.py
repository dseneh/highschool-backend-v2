"""Transactional email layout and inline asset delivery."""

import base64
from types import SimpleNamespace
from unittest.mock import patch

from django.core import mail
from django.template.loader import render_to_string
from django.test import SimpleTestCase, override_settings

from common.email_service import ResendEmailService, send_notification_email, send_system_message_email


class TransactionalEmailTests(SimpleTestCase):
    def setUp(self):
        self.context = {
            "user_name": "Ada",
            "username": "ada",
            "school_name": "Example School",
            "support_email": "support@example.org",
            "current_year": 2026,
            "login_url": "https://example.org/login",
            "reset_url": "https://example.org/reset",
            "timeout_hours": 1,
            "verification_code": "123456",
            "expiry_minutes": 10,
            "workspace_name": "Example School",
            "workspace_slug": "example",
            "activation_code": "ABC123",
            "activate_url": "https://example.org/activate",
            "temporary_password_hint": "Use your username",
            "device": "Browser",
            "operating_system": "macOS",
            "location": "Chicago",
            "ip_address": "192.0.2.1",
            "subject": "School update",
            "body": "An update from your school.",
            "category": "announcement",
            "action_url": "https://example.org/update",
        }

    def test_system_templates_share_shell_and_inline_logos(self):
        templates = [
            "account_created.html",
            "password_reset.html",
            "password_reset_success.html",
            "login_mfa_code.html",
            "mfa_recovery_code.html",
            "suspicious_login.html",
            "tenant_owner_activation.html",
            "signup_request_confirmation.html",
            "notifications/announcement.html",
            "notifications/system_message.html",
        ]
        for template in templates:
            with self.subTest(template=template):
                html = render_to_string(f"emails/{template}", self.context)
                self.assertIn("cid:ezyschool-logo-light", html)
                self.assertIn("cid:ezyschool-logo-dark", html)
                self.assertIn("prefers-color-scheme: dark", html)
                self.assertIn("Need help?", html)
                self.assertNotIn("logo_url", html)
                self.assertNotIn('<img src="http', html)

    @patch("common.email_service.ResendEmailService.send", return_value=True)
    def test_account_setup_verification_has_code_panel_without_portal_button(self, send):
        user = SimpleNamespace(email="ada@example.org", first_name="Ada", username="ada", pk=1)
        self.assertTrue(send_notification_email(
            user,
            "Your EzySchool account setup code",
            "Your verification code is 123456. It expires in 15 minutes.",
            category="verification",
            verification_code="123456",
            expiry_minutes=15,
        ))
        html = send.call_args.kwargs["html_body"]
        self.assertIn(">123456</td>", html)
        self.assertNotIn("View in EzySchool", html)
        self.assertEqual(html.count("123456"), 1)

    @override_settings(RESEND_API_KEY="test-key", DEBUG=False)
    @patch("common.email_service.requests.post")
    def test_resend_payload_embeds_both_logo_variants(self, post):
        post.return_value = SimpleNamespace(status_code=200)
        html = render_to_string("emails/login_mfa_code.html", self.context)
        sent = ResendEmailService().send(
            to=["ada@example.org"], subject="Verify", html_body=html, text_body="Code 123456"
        )
        self.assertTrue(sent)
        attachments = post.call_args.kwargs["json"]["attachments"]
        self.assertEqual({item["content_id"] for item in attachments}, {
            "ezyschool-logo-light", "ezyschool-logo-dark"
        })
        for attachment in attachments:
            self.assertTrue(base64.b64decode(attachment["content"]).startswith(b"\x89PNG"))
            self.assertEqual(attachment["content_type"], "image/png")

    @override_settings(RESEND_API_KEY="", EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_django_email_contains_related_inline_images(self):
        html = render_to_string("emails/password_reset.html", self.context)
        self.assertTrue(ResendEmailService().send(
            to=["ada@example.org"], subject="Reset", html_body=html, text_body="Reset your password"
        ))
        message = mail.outbox[0].message()
        self.assertEqual(message.get_content_type(), "multipart/related")
        images = [part for part in message.walk() if part.get_content_maintype() == "image"]
        self.assertEqual({part["Content-ID"] for part in images}, {
            "<ezyschool-logo-light>", "<ezyschool-logo-dark>"
        })
        self.assertTrue(all(part["Content-Disposition"].startswith("inline") for part in images))

    @override_settings(RESEND_API_KEY="", EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
    def test_system_notice_keeps_pdf_attachment_and_plain_text(self):
        sent = send_system_message_email(
            to=["ada@example.org"],
            subject="Transcript ready",
            body="Your official transcript is attached.",
            user_name="Ada",
            attachments=[("transcript.pdf", b"%PDF-example", "application/pdf")],
        )
        self.assertTrue(sent)
        self.assertEqual(mail.outbox[0].body, "Hi Ada,\n\nYour official transcript is attached.")
        parts = list(mail.outbox[0].message().walk())
        pdf = [part for part in parts if part.get_content_type() == "application/pdf"]
        self.assertEqual(len(pdf), 1)
        self.assertEqual(pdf[0].get_payload(decode=True), b"%PDF-example")

    @override_settings(RESEND_API_KEY="test-key", DEBUG=False)
    @patch("common.email_service.requests.post")
    def test_resend_keeps_document_attachment_with_inline_logos(self, post):
        post.return_value = SimpleNamespace(status_code=200)
        self.assertTrue(send_system_message_email(
            to=["ada@example.org"],
            subject="Transcript ready",
            body="Attached.",
            attachments=[("transcript.pdf", b"%PDF-example", "application/pdf")],
        ))
        attachments = post.call_args.kwargs["json"]["attachments"]
        pdf = [item for item in attachments if item["filename"] == "transcript.pdf"]
        self.assertEqual(len(pdf), 1)
        self.assertEqual(base64.b64decode(pdf[0]["content"]), b"%PDF-example")

    @override_settings(RESEND_API_KEY="test-key", DEBUG=False)
    @patch("common.email_service.requests.post")
    @patch("common.email_service._brand_image", side_effect=OSError("missing logo"))
    def test_missing_inline_asset_fails_without_sending_broken_email(self, _image, post):
        html = render_to_string("emails/login_mfa_code.html", self.context)
        self.assertFalse(ResendEmailService().send(
            to=["ada@example.org"], subject="Verify", html_body=html
        ))
        post.assert_not_called()
