from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase
from django.utils import timezone
from rest_framework.test import APIRequestFactory

from api.authentication import TenantSessionAuthentication


class TenantSessionAuthenticationTests(SimpleTestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.auth = TenantSessionAuthentication()

    @patch("api.authentication.TenantSession.objects.select_related")
    def test_authenticates_with_valid_tenant_session(self, mock_select_related):
        user = SimpleNamespace(id="user-1", is_authenticated=True)
        tenant = SimpleNamespace(schema_name="dujar")
        session_obj = SimpleNamespace(
            user=user,
            tenant=tenant,
            revoked_at=None,
            expires_at=timezone.now() + timedelta(hours=1),
        )

        mock_select_related.return_value.filter.return_value.first.return_value = session_obj

        request = self.factory.get(
            "/api/v1/students/",
            HTTP_X_TENANT_SESSION="opaque-session-id",
            HTTP_X_TENANT="dujar",
        )

        result = self.auth.authenticate(request)
        self.assertIsNotNone(result)
        self.assertEqual(result[0], user)

    @patch("api.authentication.TenantSession.objects.select_related")
    def test_rejects_when_tenant_header_mismatch(self, mock_select_related):
        user = SimpleNamespace(id="user-1", is_authenticated=True)
        tenant = SimpleNamespace(schema_name="dujar")
        session_obj = SimpleNamespace(
            user=user,
            tenant=tenant,
            revoked_at=None,
            expires_at=timezone.now() + timedelta(hours=1),
        )

        mock_select_related.return_value.filter.return_value.first.return_value = session_obj

        request = self.factory.get(
            "/api/v1/students/",
            HTTP_X_TENANT_SESSION="opaque-session-id",
            HTTP_X_TENANT="other-school",
        )

        result = self.auth.authenticate(request)
        self.assertIsNone(result)

    def test_returns_none_without_header(self):
        request = self.factory.get("/api/v1/students/")
        result = self.auth.authenticate(request)
        self.assertIsNone(result)
