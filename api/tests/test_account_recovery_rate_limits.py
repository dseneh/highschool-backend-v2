"""Account-aware password reset rate-limit tests."""

from types import SimpleNamespace
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings
from django_tenants.utils import get_public_schema_name, schema_context
from rest_framework.test import APIRequestFactory, force_authenticate

from users.models import AuthenticationAuditEvent, User
from users.security_views import EmailMFARecoveryStartView
from users.views import PasswordResetRequestView


@override_settings(
    PASSWORD_RESET_ACCOUNT_LIMIT_PER_HOUR=3,
    PASSWORD_RESET_REQUEST_COOLDOWN_SECONDS=60,
    EMAIL_MFA_PRIVILEGED_ENABLED=True,
    MFA_RECOVERY_ACCOUNT_LIMIT_PER_HOUR=1,
    MFA_RECOVERY_REQUEST_COOLDOWN_SECONDS=60,
)
class AccountRecoveryRateLimitTests(TestCase):
    def setUp(self):
        cache.clear()
        self.factory = APIRequestFactory()
        self.user = User.objects.create(
            email="reset-user@example.com",
            username="reset-user",
            id_number="RESET-USER",
            account_type="staff",
            is_active=True,
        )

    @patch("common.audit_utils.log_auth_event")
    @patch("common.email_service.send_password_reset_email", return_value=True)
    def test_account_limit_and_cooldown_keep_generic_response(
        self, send_email, log_auth_event
    ):
        responses = [
            PasswordResetRequestView.as_view()(
                self.factory.post(
                    "/api/v1/auth/password/forgot/",
                    {"user_identifier": self.user.email},
                    format="json",
                    REMOTE_ADDR=f"192.0.2.{index}",
                )
            )
            for index in range(1, 5)
        ]

        self.assertTrue(
            all(response.status_code == 200 for response in responses),
            [
                {"status": response.status_code, "data": response.data}
                for response in responses
            ],
        )
        self.assertTrue(
            all(response.data == responses[0].data for response in responses[1:])
        )
        self.assertEqual(send_email.call_count, 1)
        reasons = [
            call.kwargs.get("details", {}).get("reason")
            for call in log_auth_event.call_args_list
        ]
        self.assertIn("resend_cooldown", reasons)
        self.assertIn("account_hourly_limit", reasons)

    @patch("common.email_service.send_password_reset_email", return_value=True)
    def test_unknown_and_existing_accounts_receive_same_response(self, _send_email):
        existing = PasswordResetRequestView.as_view()(
            self.factory.post(
                "/api/v1/auth/password/forgot/",
                {"user_identifier": self.user.email},
                format="json",
                REMOTE_ADDR="198.51.100.10",
            )
        )
        unknown = PasswordResetRequestView.as_view()(
            self.factory.post(
                "/api/v1/auth/password/forgot/",
                {"user_identifier": "missing@example.com"},
                format="json",
                REMOTE_ADDR="198.51.100.11",
            )
        )

        self.assertEqual(existing.status_code, 200, existing.data)
        self.assertEqual(unknown.status_code, 200, unknown.data)
        self.assertEqual(existing.data, unknown.data)

    @patch(
        "common.email_service.send_email_mfa_recovery_code",
        return_value=True,
    )
    def test_account_limit_applies_across_ip_addresses(self, _send_email):
        target = User.objects.create(
            email="mfa-limit-target@example.com",
            username="mfa-limit-target",
            id_number="MFA-LIMIT-TARGET",
            account_type="staff",
            is_active=True,
        )
        actor = User.objects.create(
            email="mfa-limit-platform@example.com",
            username="mfa-limit-platform",
            id_number="MFA-LIMIT-PLATFORM",
            account_type="staff",
            is_active=True,
            is_platform_superuser=True,
        )
        payload = {
            "user_id": str(target.pk),
            "new_email": "mfa-limit-recovered@example.com",
        }
        role = SimpleNamespace(system_key="admin", is_active=True)
        with (
            patch("authorization.services.get_assigned_role", return_value=role),
            patch("users.mfa.requires_email_mfa", return_value=True),
        ):
            first_request = self.factory.post(
                "/api/v1/auth/security/mfa-recovery/",
                payload,
                format="json",
                REMOTE_ADDR="203.0.113.10",
            )
            force_authenticate(first_request, user=actor)
            first = EmailMFARecoveryStartView.as_view()(first_request)

            second_request = self.factory.post(
                "/api/v1/auth/security/mfa-recovery/",
                payload,
                format="json",
                REMOTE_ADDR="203.0.113.11",
            )
            force_authenticate(second_request, user=actor)
            second = EmailMFARecoveryStartView.as_view()(second_request)

        self.assertEqual(first.status_code, 202, first.data)
        self.assertEqual(second.status_code, 429, second.data)
        with schema_context(get_public_schema_name()):
            event = AuthenticationAuditEvent.objects.filter(
                event_type="mfa_recovery_throttled",
                user=target,
            ).latest("created_at")
        self.assertEqual(event.metadata["reason"], "account_hourly_limit")
