"""Privileged email MFA integration tests."""

from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings
from django_tenants.test.cases import TenantTestCase
from rest_framework.test import APIClient

from authorization.models import Role
from authorization.services import assign_user_role
from users.models import EmailMFAChallenge, TenantSession, User

PASSWORD = "email-mfa-test-pass-123"


class EmailMFAHelperTests(SimpleTestCase):
    def test_email_mask_and_token_digest_do_not_expose_secrets(self):
        from users.mfa import mask_email, token_digest

        self.assertEqual(mask_email("admin@example.com"), "a****@example.com")
        self.assertEqual(mask_email("invalid"), "***")
        self.assertNotIn("challenge-secret", token_digest("challenge-secret"))


@override_settings(
    EMAIL_MFA_PRIVILEGED_ENABLED=True,
    EMAIL_MFA_CODE_TTL_SECONDS=600,
    EMAIL_MFA_MAX_ATTEMPTS=5,
    EMAIL_MFA_RESEND_COOLDOWN_SECONDS=60,
    EMAIL_MFA_MAX_RESENDS=5,
)
class PrivilegedEmailMFATests(TenantTestCase):
    @classmethod
    def setup_tenant(cls, tenant):
        tenant.name = "MFA Test School"
        tenant.short_name = "mfa"
        tenant.owner, _ = User.objects.get_or_create(
            email="mfa-owner@example.com",
            defaults={
                "username": "mfa-owner",
                "id_number": "MFA-OWNER",
                "account_type": "staff",
            },
        )

    def setUp(self):
        cache.clear()
        self.client = APIClient()

    def _user(self, name, role_key):
        user = User.objects.create(
            email=f"{name}@example.com",
            username=name,
            id_number=name.upper(),
            account_type="staff",
            is_active=True,
        )
        user.set_password(PASSWORD)
        user.save(update_fields=["password"])
        self.tenant.add_user(user)
        assign_user_role(user=user, role=Role.objects.get(system_key=role_key))
        return user

    def _login(self, user):
        captured = {}

        def record_code(_user, code, **_kwargs):
            captured["code"] = code
            return True

        with patch("common.email_service.send_email_mfa_code", side_effect=record_code):
            response = self.client.post(
                "/api/v1/auth/login/",
                {"username": user.username, "password": PASSWORD},
                format="json",
            )
        return response, captured

    def test_tenant_admin_receives_challenge_without_jwts(self):
        user = self._user("mfa-admin", "admin")
        response, captured = self._login(user)

        self.assertEqual(response.status_code, 202)
        self.assertTrue(response.data["mfa_required"])
        self.assertNotIn("access", response.data)
        self.assertNotIn("refresh", response.data)
        self.assertRegex(captured["code"], r"^\d{6}$")
        challenge = EmailMFAChallenge.objects.get(user=user)
        self.assertNotEqual(challenge.code_hash, captured["code"])
        self.assertNotEqual(challenge.token_hash, response.data["challenge_token"])

    def test_regular_staff_login_remains_single_step(self):
        user = self._user("mfa-staff", "staff")
        response, captured = self._login(user)

        self.assertEqual(response.status_code, 200)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)
        self.assertEqual(captured, {})
        self.assertEqual(TenantSession.objects.filter(user=user, revoked_at__isnull=True).count(), 1)

    def test_valid_code_issues_tokens_once(self):
        user = self._user("mfa-verify", "admin")
        login, captured = self._login(user)
        payload = {"challenge_token": login.data["challenge_token"], "code": captured["code"]}

        verified = self.client.post("/api/v1/auth/mfa/verify/", payload, format="json")
        replay = self.client.post("/api/v1/auth/mfa/verify/", payload, format="json")

        self.assertEqual(verified.status_code, 200)
        self.assertIn("access", verified.data)
        self.assertIn("refresh", verified.data)
        self.assertEqual(TenantSession.objects.filter(user=user, revoked_at__isnull=True).count(), 1)
        self.assertEqual(replay.status_code, 400)

    def test_user_can_list_and_revoke_one_device_session(self):
        user = self._user("mfa-devices", "staff")
        login, _captured = self._login(user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {login.data['access']}")

        listed = self.client.get("/api/v1/auth/security/sessions/")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.data["results"]), 1)
        self.assertTrue(listed.data["results"][0]["is_current"])

        session_id = listed.data["results"][0]["id"]
        revoked = self.client.delete(f"/api/v1/auth/security/sessions/{session_id}/")
        self.assertEqual(revoked.status_code, 200)
        self.assertTrue(revoked.data["current_session_revoked"])
        self.assertIsNotNone(TenantSession.objects.get(pk=session_id).revoked_at)

        denied = self.client.get("/api/v1/auth/security/sessions/")
        self.assertEqual(denied.status_code, 401)

    def test_platform_admin_can_recover_privileged_users_mfa_email(self):
        target = self._user("mfa-recovery-target", "admin")
        login, _captured = self._login(target)
        self.assertEqual(login.status_code, 202)

        actor = User.objects.create(
            email="platform-security@example.com",
            username="platform-security",
            id_number="PLATFORM-SECURITY",
            account_type="staff",
            is_active=True,
            is_platform_superuser=True,
        )
        self.client.force_authenticate(user=actor)
        captured = {}

        def record_recovery_code(**kwargs):
            captured["code"] = kwargs["code"]
            return True

        with patch(
            "common.email_service.send_email_mfa_recovery_code",
            side_effect=record_recovery_code,
        ):
            started = self.client.post(
                "/api/v1/auth/security/mfa-recovery/",
                {"user_id": str(target.pk), "new_email": "recovered@example.com"},
                format="json",
            )

        self.assertEqual(started.status_code, 202)
        self.assertRegex(captured["code"], r"^\d{6}$")

        self.client.force_authenticate(user=None)
        completed = self.client.post(
            "/api/v1/auth/security/mfa-recovery/verify/",
            {
                "challenge_token": started.data["challenge_token"],
                "code": captured["code"],
            },
            format="json",
        )

        self.assertEqual(completed.status_code, 200)
        target.refresh_from_db()
        self.assertEqual(target.email, "recovered@example.com")
        self.assertGreater(target.security_version, 1)

    def test_five_bad_codes_invalidate_challenge(self):
        user = self._user("mfa-attempts", "admin")
        login, _captured = self._login(user)
        payload = {"challenge_token": login.data["challenge_token"], "code": "000000"}

        for _ in range(5):
            response = self.client.post("/api/v1/auth/mfa/verify/", payload, format="json")

        self.assertEqual(response.status_code, 400)
        challenge = EmailMFAChallenge.objects.get(user=user)
        self.assertEqual(challenge.failed_attempts, 5)
        self.assertIsNotNone(challenge.invalidated_at)
