import base64
import hashlib
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIRequestFactory

from core.models import Tenant
from users.models import AuthorizationCode, OAuthClient, OAuthRedirectURI, ParentProfile, TenantSession, User
from users.sso_utils import hash_value
from users.sso_views import SsoTokenExchangeView


class ParentSsoExchangeTests(TestCase):
    def test_parent_session_creation_and_code_replay(self):
        user = User.objects.create(username="parent-sso-test", email="parent-sso@example.invalid", status="active", is_active=True)
        ParentProfile.objects.create(user=user)
        tenant, _ = Tenant.objects.get_or_create(schema_name="public", defaults={
            "name": "Public", "id_number": "SSO-PUBLIC", "owner": user, "active": True, "status": "active",
        })
        client = OAuthClient.objects.create(client_id="parent-sso-test", name="Test", require_pkce=True)
        uri = "http://parent.lvh.me:3000/auth/callback"
        OAuthRedirectURI.objects.create(client=client, redirect_uri=uri)
        verifier = "parent-test-verifier-which-is-at-least-forty-three-characters"
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        code = AuthorizationCode.objects.create(
            code_hash=hash_value("parent-test-code"), user=user, tenant=tenant, client=client,
            redirect_uri=uri, code_challenge=challenge, requested_scopes=["parent_workspace"],
            expires_at=timezone.now() + timedelta(minutes=1),
        )
        def exchange():
            request = APIRequestFactory().post("/api/v1/sso/token/", {
                "grant_type": "authorization_code", "code": "parent-test-code", "client_id": client.client_id,
                "redirect_uri": uri, "code_verifier": verifier,
            }, format="json")
            return SsoTokenExchangeView.as_view()(request)

        response = exchange()
        self.assertEqual(response.status_code, 200, response.data.get("detail"))
        self.assertTrue(response.data["parent_workspace"])
        session = TenantSession.objects.get(pk=response.data["tenant_session_id"])
        self.assertEqual(session.device_metadata, {})
        self.assertEqual(session.roles, ["parent_workspace"])
        code.refresh_from_db()
        self.assertIsNotNone(code.consumed_at)
        replay = exchange()
        self.assertEqual(replay.status_code, 400)
        self.assertEqual(replay.data["error_code"], "CODE_CONSUMED")
