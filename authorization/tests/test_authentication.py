from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from api.authentication import RBACSessionAuthentication, TenantAwareJWTAuthentication
from authorization.runtime import (
    AuthorizationBindingError,
    initialize_request_authorization,
)


def authenticated_user(user_id="user-1"):
    return SimpleNamespace(
        pk=user_id,
        is_authenticated=True,
        is_active=True,
    )


class AuthenticationFacadeTests(SimpleTestCase):
    @patch("rest_framework.authentication.SessionAuthentication.authenticate")
    def test_django_session_authentication_attaches_facade(self, mock_authenticate):
        user = authenticated_user()
        mock_authenticate.return_value = (user, None)
        request = SimpleNamespace()

        result = RBACSessionAuthentication().authenticate(request)

        self.assertEqual(result, (user, None))
        self.assertTrue(callable(request.can))
        self.assertTrue(callable(request.permission_scope))

    @patch("rest_framework_simplejwt.authentication.JWTAuthentication.authenticate")
    def test_jwt_authentication_attaches_facade_to_drf_request(self, mock_authenticate):
        user = authenticated_user()
        token = object()
        mock_authenticate.return_value = (user, token)
        request = SimpleNamespace(_request=object())

        result = TenantAwareJWTAuthentication().authenticate(request)

        self.assertEqual(result, (user, token))
        self.assertTrue(callable(request.can))

    def test_request_cannot_be_rebound_to_another_user(self):
        request = SimpleNamespace()
        initialize_request_authorization(request, authenticated_user("user-1"))

        with self.assertRaises(AuthorizationBindingError):
            initialize_request_authorization(request, authenticated_user("user-2"))
