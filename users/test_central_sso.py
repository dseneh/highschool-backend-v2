"""Central identity is reusable; workspace permissions remain independently checked."""
from types import SimpleNamespace
from unittest.mock import patch
from django.test import SimpleTestCase
from django.utils import timezone
from datetime import timedelta
from rest_framework.test import APIRequestFactory, force_authenticate
from users.sso_views import SsoBootstrapView, resolve_sso_user


class CentralIdentityTests(SimpleTestCase):
    def test_parent_authentication_can_bootstrap_identity_and_reuse_browser_session(self):
        user = SimpleNamespace(pk="user", is_authenticated=True)
        central = SimpleNamespace(pk="central", expires_at=timezone.now()+timedelta(hours=1))
        request = APIRequestFactory().post('/api/v1/sso/bootstrap/', {}, format='json')
        request.COOKIES['ezyschool_sso'] = 'opaque-secret'
        force_authenticate(request, user=user, token={'parent_workspace': True})
        with patch('users.sso_views.CentralAuthSession.objects.filter') as existing:
            existing.return_value.first.return_value = central
            response = SsoBootstrapView.as_view()(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['session_id'], 'opaque-secret')
        self.assertEqual(existing.call_args.kwargs['user'], user)

    def test_source_role_state_is_not_carried_into_destination_identity(self):
        source = SimpleNamespace(pk='user', is_authenticated=True, _active_role_selection='parent-only')
        identity = SimpleNamespace(pk='user')
        with patch('users.models.User.objects.filter') as users:
            users.return_value.first.return_value = identity
            user, central = resolve_sso_user(SimpleNamespace(user=source, COOKIES={}))
        self.assertIs(user, identity)
        self.assertIsNone(central)
        users.assert_called_once_with(pk='user', is_active=True, status='active')

    def test_expired_revoked_and_inactive_central_sessions_are_filtered(self):
        request = SimpleNamespace(user=None, COOKIES={'ezyschool_sso':'opaque'})
        with patch('users.sso_views.CentralAuthSession.objects.select_related') as sessions:
            sessions.return_value.filter.return_value.first.return_value = None
            self.assertEqual(resolve_sso_user(request), (None, None))
        filters = sessions.return_value.filter.call_args.kwargs
        self.assertTrue(filters['revoked_at__isnull'])
        self.assertTrue(filters['user__is_active'])
        self.assertEqual(filters['user__status'], 'active')
        self.assertIn('expires_at__gt', filters)
