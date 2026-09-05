from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from users.sso_utils import verify_pkce_s256
from users.sso_views import SsoAuthorizeView
from users.sso_views import GlobalLogoutView
from users.sso_views import SsoRefreshView
from users.sso_views import SsoTokenExchangeView
from users.sso_views import TenantLogoutView
from users.sso_views import is_valid_tenant_redirect_uri
from users.utils import build_frontend_url


class SsoPkceUtilsTests(SimpleTestCase):
	def test_verify_pkce_s256_accepts_valid_verifier(self):
		verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
		challenge = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
		self.assertTrue(verify_pkce_s256(verifier, challenge))

	def test_verify_pkce_s256_rejects_invalid_verifier(self):
		verifier = "not-the-right-verifier"
		challenge = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
		self.assertFalse(verify_pkce_s256(verifier, challenge))


class SsoTokenExchangeViewTests(TestCase):
	def setUp(self):
		self.factory = APIRequestFactory()
		self.view = SsoTokenExchangeView.as_view()
		self.now = timezone.now()

	def _build_code(self, challenge):
		code_obj = SimpleNamespace()
		code_obj.code_hash = "abc"
		code_obj.consumed_at = None
		code_obj.revoked_at = None
		code_obj.expires_at = self.now + timedelta(seconds=50)
		code_obj.redirect_uri = "https://dujar.myezyschool.com/auth/callback"
		code_obj.code_challenge = challenge
		code_obj.code_challenge_method = "S256"
		code_obj.client = SimpleNamespace(client_id="ezyschool-web")
		code_obj.tenant = SimpleNamespace(id="tenant-1", active=True, status="active")
		code_obj.auth_session = None
		code_obj.user = SimpleNamespace(is_active=True, status="active")
		code_obj.save = MagicMock()
		return code_obj

	@patch("users.sso_views.AuthenticationAuditEvent.objects.create")
	@patch("users.sso_views.RefreshTokenRecord.objects.create")
	@patch("users.sso_views.TenantSession.objects.create")
	@patch("users.sso_views.RefreshTokenFamily.objects.create")
	@patch("users.sso_views.user_has_tenant_workspace_access")
	@patch("users.sso_views.OAuthRedirectURI.objects.filter")
	@patch("users.sso_views.AuthorizationCode.objects.select_for_update")
	@patch("users.sso_views.RefreshToken.for_user")
	def test_token_exchange_success(
		self,
		mock_for_user,
		mock_select_for_update,
		mock_redirect_filter,
		mock_has_access,
		mock_family_create,
		mock_session_create,
		_mock_refresh_record_create,
		_mock_audit_create,
	):
		verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
		challenge = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
		code_obj = self._build_code(challenge)

		mock_select_for_update.return_value.select_related.return_value.filter.return_value.first.return_value = code_obj
		mock_redirect_filter.return_value.exists.return_value = True
		mock_has_access.return_value = True
		mock_family_create.return_value = SimpleNamespace(id="fam-1")
		mock_session_create.return_value = SimpleNamespace(id="sess-1")

		class FakeAccessToken(dict):
			lifetime = timedelta(minutes=60)

			def __str__(self):
				return "access-token"

		fake_access = FakeAccessToken()
		fake_refresh = MagicMock()
		fake_refresh.access_token = fake_access
		fake_refresh.lifetime = timedelta(days=7)
		fake_refresh.__str__.return_value = "refresh-token"
		mock_for_user.return_value = fake_refresh

		request = self.factory.post(
			"/api/v1/sso/token/",
			{
				"grant_type": "authorization_code",
				"code": "one-time-code",
				"client_id": "ezyschool-web",
				"redirect_uri": "https://dujar.myezyschool.com/auth/callback",
				"code_verifier": verifier,
			},
			format="json",
		)
		response = self.view(request)

		self.assertEqual(response.status_code, 200)
		self.assertIn("access", response.data)
		self.assertIn("refresh", response.data)
		self.assertEqual(response.data["tenant_session_id"], "sess-1")
		code_obj.save.assert_called_once()

	@patch("users.sso_views.OAuthRedirectURI.objects.filter")
	@patch("users.sso_views.AuthorizationCode.objects.select_for_update")
	def test_token_exchange_rejects_invalid_pkce(self, mock_select_for_update, mock_redirect_filter):
		code_obj = self._build_code("E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM")
		mock_select_for_update.return_value.select_related.return_value.filter.return_value.first.return_value = code_obj
		mock_redirect_filter.return_value.exists.return_value = True

		request = self.factory.post(
			"/api/v1/sso/token/",
			{
				"grant_type": "authorization_code",
				"code": "one-time-code",
				"client_id": "ezyschool-web",
				"redirect_uri": "https://dujar.myezyschool.com/auth/callback",
				"code_verifier": "invalid-verifier",
			},
			format="json",
		)
		response = self.view(request)

		self.assertEqual(response.status_code, 400)
		self.assertEqual(response.data.get("error_code"), "INVALID_CODE_VERIFIER")


class SsoAuthorizeViewTests(SimpleTestCase):
	def setUp(self):
		self.factory = APIRequestFactory()
		self.view = SsoAuthorizeView.as_view()
		self.user = SimpleNamespace(
			pk="user-1",
			id="user-1",
			is_authenticated=True,
			is_active=True,
			status="active",
		)

	@patch("users.sso_views.AuthenticationAuditEvent.objects.create")
	@patch("users.sso_views.AuthorizationCode.objects.create")
	@patch("users.sso_views.resolve_sso_user")
	@patch("users.sso_views.user_has_tenant_workspace_access")
	@patch("users.sso_views.Domain.objects.select_related")
	@patch("users.sso_views.Tenant.objects.filter")
	@patch("users.sso_views.OAuthRedirectURI.objects.filter")
	@patch("users.sso_views.OAuthClient.objects.filter")
	def test_authorize_success_redirects_with_code_and_state(
		self,
		mock_client_filter,
		mock_redirect_filter,
		mock_tenant_filter,
		mock_domain_select_related,
		mock_membership,
		mock_resolve_user,
		mock_code_create,
		_mock_audit,
	):
		client = SimpleNamespace(client_id="ezyschool-web")
		tenant = SimpleNamespace(schema_name="dujar", active=True, status="active")

		mock_client_filter.return_value.first.return_value = client
		mock_redirect_filter.return_value.exists.return_value = True
		mock_tenant_filter.return_value.first.return_value = tenant
		mock_domain_select_related.return_value.filter.return_value.order_by.return_value.first.return_value = None
		mock_resolve_user.return_value = (self.user, None)
		mock_membership.return_value = True

		request = self.factory.get(
			"/api/v1/sso/authorize/",
			{
				"client_id": "ezyschool-web",
				"redirect_uri": "https://dujar.myezyschool.com/auth/callback",
				"tenant": "dujar",
				"state": "abc123",
				"code_challenge": "challenge",
				"code_challenge_method": "S256",
				"return_to": "/dashboard",
			},
		)
		force_authenticate(request, user=self.user)

		response = self.view(request)

		self.assertEqual(response.status_code, 302)
		self.assertIn("state=abc123", response["Location"])
		self.assertIn("code=", response["Location"])
		mock_code_create.assert_called_once()

	@patch("users.sso_views.user_has_tenant_workspace_access")
	@patch("users.sso_views.resolve_sso_user")
	@patch("users.sso_views.Domain.objects.select_related")
	@patch("users.sso_views.Tenant.objects.filter")
	@patch("users.sso_views.OAuthRedirectURI.objects.filter")
	@patch("users.sso_views.OAuthClient.objects.filter")
	def test_authorize_denies_user_without_tenant_membership(
		self,
		mock_client_filter,
		mock_redirect_filter,
		mock_tenant_filter,
		mock_domain_select_related,
		mock_resolve_user,
		mock_membership,
	):
		client = SimpleNamespace(client_id="ezyschool-web")
		tenant = SimpleNamespace(schema_name="dujar", active=True, status="active")

		mock_client_filter.return_value.first.return_value = client
		mock_redirect_filter.return_value.exists.return_value = True
		mock_tenant_filter.return_value.first.return_value = tenant
		mock_domain_select_related.return_value.filter.return_value.order_by.return_value.first.return_value = None
		mock_resolve_user.return_value = (self.user, None)
		mock_membership.return_value = False

		request = self.factory.get(
			"/api/v1/sso/authorize/",
			{
				"client_id": "ezyschool-web",
				"redirect_uri": "https://dujar.myezyschool.com/auth/callback",
				"tenant": "dujar",
				"state": "abc123",
				"code_challenge": "challenge",
				"code_challenge_method": "S256",
			},
		)
		force_authenticate(request, user=self.user)

		response = self.view(request)

		self.assertEqual(response.status_code, 403)
		self.assertEqual(response.data.get("error_code"), "TENANT_ACCESS_DENIED")

	@patch("users.sso_views.resolve_sso_user")
	@patch("users.sso_views.Domain.objects.select_related")
	@patch("users.sso_views.Tenant.objects.filter")
	@patch("users.sso_views.OAuthRedirectURI.objects.filter")
	@patch("users.sso_views.OAuthClient.objects.filter")
	def test_authorize_requires_auth_or_central_session(
		self,
		mock_client_filter,
		mock_redirect_filter,
		mock_tenant_filter,
		mock_domain_select_related,
		mock_resolve_user,
	):
		client = SimpleNamespace(client_id="ezyschool-web")
		tenant = SimpleNamespace(schema_name="dujar", active=True, status="active")

		mock_client_filter.return_value.first.return_value = client
		mock_redirect_filter.return_value.exists.return_value = True
		mock_tenant_filter.return_value.first.return_value = tenant
		mock_domain_select_related.return_value.filter.return_value.order_by.return_value.first.return_value = None
		mock_resolve_user.return_value = (None, None)

		request = self.factory.get(
			"/api/v1/sso/authorize/",
			{
				"client_id": "ezyschool-web",
				"redirect_uri": "https://dujar.myezyschool.com/auth/callback",
				"tenant": "dujar",
				"state": "abc123",
				"code_challenge": "challenge",
				"code_challenge_method": "S256",
			},
		)
		response = self.view(request)

		self.assertEqual(response.status_code, 401)
		self.assertEqual(response.data.get("error_code"), "AUTH_REQUIRED")

	@patch("users.sso_views.AuthenticationAuditEvent.objects.create")
	@patch("users.sso_views.AuthorizationCode.objects.create")
	@patch("users.sso_views.resolve_sso_user")
	@patch("users.sso_views.user_has_tenant_workspace_access")
	@patch("users.sso_views.Domain.objects.select_related")
	@patch("users.sso_views.Tenant.objects.filter")
	@patch("users.sso_views.OAuthRedirectURI.objects.filter")
	@patch("users.sso_views.OAuthClient.objects.filter")
	def test_authorize_resolves_tenant_by_domain_prefix(
		self,
		mock_client_filter,
		mock_redirect_filter,
		mock_tenant_filter,
		mock_domain_select_related,
		mock_membership,
		mock_resolve_user,
		_mock_code_create,
		_mock_audit,
	):
		client = SimpleNamespace(client_id="ezyschool-web")
		tenant = SimpleNamespace(schema_name="dujar_school", active=True, status="active")
		domain_obj = SimpleNamespace(tenant=tenant)

		mock_client_filter.return_value.first.return_value = client
		mock_redirect_filter.return_value.exists.return_value = True
		mock_tenant_filter.return_value.first.return_value = None
		mock_domain_select_related.return_value.filter.return_value.order_by.return_value.first.return_value = domain_obj
		mock_resolve_user.return_value = (self.user, None)
		mock_membership.return_value = True

		request = self.factory.get(
			"/api/v1/sso/authorize/",
			{
				"client_id": "ezyschool-web",
				"redirect_uri": "https://dujar.myezyschool.com/auth/callback",
				"tenant": "dujar",
				"state": "abc123",
				"code_challenge": "challenge",
				"code_challenge_method": "S256",
			},
		)
		force_authenticate(request, user=self.user)

		response = self.view(request)

		self.assertEqual(response.status_code, 302)
		self.assertIn("state=abc123", response["Location"])


class SsoRefreshViewTests(TestCase):
	def setUp(self):
		self.factory = APIRequestFactory()
		self.view = SsoRefreshView.as_view()

	@patch("users.sso_views.AuthenticationAuditEvent.objects.create")
	@patch("users.sso_views.RefreshTokenRecord.objects.create")
	@patch("users.sso_views.RefreshTokenRecord.objects.select_for_update")
	@patch("users.sso_views.RefreshToken.for_user")
	def test_refresh_rotates_token(
		self,
		mock_for_user,
		mock_select_for_update,
		_mock_record_create,
		_mock_audit,
	):
		now = timezone.now()
		family = SimpleNamespace(revoked_at=None)
		family.save = MagicMock()
		tenant = SimpleNamespace(id="tenant-1")
		user = SimpleNamespace(id="user-1")
		session = SimpleNamespace(
			id="sess-1",
			user=user,
			tenant=tenant,
			membership_id="",
			permission_version=1,
			revoked_at=None,
			save=MagicMock(),
		)
		refresh_record = SimpleNamespace(
			family=family,
			tenant_session=session,
			reuse_detected=False,
			rotated_at=None,
			revoked_at=None,
			expires_at=now + timedelta(days=1),
			save=MagicMock(),
		)
		mock_select_for_update.return_value.select_related.return_value.filter.return_value.first.return_value = refresh_record

		class FakeAccessToken(dict):
			lifetime = timedelta(minutes=60)

			def __str__(self):
				return "new-access"

		fake_refresh = MagicMock()
		fake_refresh.access_token = FakeAccessToken()
		fake_refresh.__str__.return_value = "new-refresh"
		mock_for_user.return_value = fake_refresh

		request = self.factory.post(
			"/api/v1/sso/refresh/",
			{"grant_type": "refresh_token", "refresh_token": "r1"},
			format="json",
		)
		response = self.view(request)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.data.get("refresh"), "new-refresh")
		refresh_record.save.assert_called_once()

	@patch("users.sso_views.AuthenticationAuditEvent.objects.create")
	@patch("users.sso_views.SessionRevocation.objects.create")
	@patch("users.sso_views.RefreshTokenRecord.objects.filter")
	@patch("users.sso_views.RefreshTokenRecord.objects.select_for_update")
	def test_refresh_reuse_detected_revokes_family(
		self,
		mock_select_for_update,
		mock_filter,
		_mock_revocation_create,
		_mock_audit,
	):
		now = timezone.now()
		family = SimpleNamespace(revoked_at=None, global_session=None)
		family.save = MagicMock()
		tenant = SimpleNamespace(id="tenant-1")
		user = SimpleNamespace(id="user-1")
		session = SimpleNamespace(id="sess-1", user=user, tenant=tenant, revoked_at=None)
		session.save = MagicMock()
		refresh_record = SimpleNamespace(
			family=family,
			tenant_session=session,
			reuse_detected=True,
			rotated_at=now,
			revoked_at=None,
			expires_at=now + timedelta(days=1),
		)
		mock_select_for_update.return_value.select_related.return_value.filter.return_value.first.return_value = refresh_record
		mock_filter.return_value.update = MagicMock()

		request = self.factory.post(
			"/api/v1/sso/refresh/",
			{"grant_type": "refresh_token", "refresh_token": "r1"},
			format="json",
		)
		response = self.view(request)

		self.assertEqual(response.status_code, 403)
		self.assertEqual(response.data.get("error_code"), "REFRESH_TOKEN_REUSE")
		family.save.assert_called_once()
		session.save.assert_called_once()


class SsoLogoutViewTests(SimpleTestCase):
	def setUp(self):
		self.factory = APIRequestFactory()
		self.tenant_logout_view = TenantLogoutView.as_view()
		self.global_logout_view = GlobalLogoutView.as_view()
		self.user = SimpleNamespace(
			pk="user-1",
			id="user-1",
			is_authenticated=True,
			is_active=True,
			status="active",
		)

	@patch("users.sso_views.AuthenticationAuditEvent.objects.create")
	@patch("users.sso_views.SessionRevocation.objects.create")
	@patch("users.sso_views.RefreshTokenRecord.objects.filter")
	@patch("users.sso_views.TenantSession.objects.filter")
	def test_tenant_logout_revokes_active_session(
		self,
		mock_session_filter,
		mock_refresh_filter,
		_mock_revocation,
		_mock_audit,
	):
		session = SimpleNamespace(
			id="sess-1",
			tenant=SimpleNamespace(id="tenant-1"),
			refresh_token_family=SimpleNamespace(id="fam-1"),
			global_session=None,
			revoked_at=None,
			save=MagicMock(),
		)
		mock_session_filter.return_value.order_by.return_value.first.return_value = session
		mock_refresh_filter.return_value.update = MagicMock()

		request = self.factory.post("/api/v1/sso/tenant/logout/", {}, format="json")
		force_authenticate(request, user=self.user)
		response = self.tenant_logout_view(request)

		self.assertEqual(response.status_code, 200)
		session.save.assert_called_once()

	@patch("users.sso_views.AuthenticationAuditEvent.objects.create")
	@patch("users.sso_views.SessionRevocation.objects.create")
	@patch("users.sso_views.RefreshTokenFamily.objects.filter")
	@patch("users.sso_views.RefreshTokenRecord.objects.filter")
	@patch("users.sso_views.TenantSession.objects.filter")
	@patch("users.sso_views.CentralAuthSession.objects.filter")
	def test_global_logout_revokes_linked_sessions(
		self,
		mock_central_filter,
		mock_tenant_filter,
		mock_refresh_filter,
		mock_family_filter,
		_mock_revocation,
		_mock_audit,
	):
		central = SimpleNamespace(id="central-1", revoked_at=None, save=MagicMock())
		mock_central_filter.return_value.order_by.return_value.first.return_value = central

		session1 = SimpleNamespace(id="sess-1")
		session2 = SimpleNamespace(id="sess-2")
		tenant_queryset = MagicMock()
		tenant_queryset.__iter__.return_value = iter([session1, session2])
		tenant_queryset.update = MagicMock()
		mock_tenant_filter.return_value = tenant_queryset

		mock_refresh_filter.return_value.update = MagicMock()
		mock_family_filter.return_value.update = MagicMock()

		request = self.factory.post("/api/v1/sso/logout/", {}, format="json")
		force_authenticate(request, user=self.user)
		response = self.global_logout_view(request)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.data.get("revoked_tenant_sessions"), ["sess-1", "sess-2"])
		central.save.assert_called_once()


class TenantUrlGenerationTests(SimpleTestCase):
	"""Verifies tenant URLs are derived from APP_ROOT_DOMAIN via FRONTEND_SUBDOMAIN_BASE."""

	@override_settings(
		FRONTEND_DOMAIN="https://myezyschool.com",
		FRONTEND_SUBDOMAIN_BASE="myezyschool.com",
		FRONTEND_USE_SUBDOMAIN=True,
		FRONTEND_DEV_MODE=False,
	)
	def test_builds_tenant_subdomain_url_on_new_root_domain(self):
		url = build_frontend_url(school_workspace="dujar", path="/activate-account")
		self.assertEqual(url, "https://dujar.myezyschool.com/activate-account")

	@override_settings(
		FRONTEND_DOMAIN="https://myezyschool.com",
		FRONTEND_SUBDOMAIN_BASE="myezyschool.com",
		FRONTEND_USE_SUBDOMAIN=True,
		FRONTEND_DEV_MODE=False,
	)
	def test_builds_root_domain_url_without_workspace(self):
		url = build_frontend_url(school_workspace=None, path="/reset-password")
		self.assertEqual(url, "https://myezyschool.com/reset-password")

	@override_settings(
		FRONTEND_DOMAIN="http://localhost:3000",
		FRONTEND_SUBDOMAIN_BASE="",
		FRONTEND_USE_SUBDOMAIN=True,
		FRONTEND_DEV_MODE=True,
	)
	def test_falls_back_to_path_based_tenant_url_on_localhost(self):
		url = build_frontend_url(school_workspace="dujar", path="/activate-account")
		self.assertEqual(url, "http://localhost:3000/dujar/activate-account")


class SsoRedirectUriValidationTests(SimpleTestCase):
	"""Ensures the SSO redirect_uri validator is domain-agnostic (no ezyschool.app dependency)."""

	def test_accepts_tenant_subdomain_on_new_root_domain(self):
		self.assertTrue(
			is_valid_tenant_redirect_uri("https://dujar.myezyschool.com/auth/callback", "dujar")
		)

	def test_rejects_mismatched_tenant_subdomain(self):
		self.assertFalse(
			is_valid_tenant_redirect_uri("https://other.myezyschool.com/auth/callback", "dujar")
		)

	def test_accepts_localhost_path_based_redirect(self):
		self.assertTrue(
			is_valid_tenant_redirect_uri("http://localhost:3000/auth/callback", "dujar")
		)
