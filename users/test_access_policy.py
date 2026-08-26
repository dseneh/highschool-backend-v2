from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from users.access_policies import UserAccessPolicy


class UserAccessPolicyTests(SimpleTestCase):
    def setUp(self):
        self.policy = UserAccessPolicy()
        self.user = SimpleNamespace(
            is_authenticated=True,
            is_anonymous=False,
            is_platform_superuser=False,
        )

    @patch("authorization.runtime.initialize_request_authorization")
    def test_update_permission_does_not_allow_deactivation(self, mock_initialize):
        facade = Mock()
        facade.context.unrestricted = False
        facade.permission_scope.side_effect = lambda code: (
            "all" if code == "users.update" else None
        )
        mock_initialize.return_value = facade
        request = SimpleNamespace(user=self.user, method="PATCH")

        self.assertTrue(
            self.policy.has_permission(
                request, SimpleNamespace(action="update", kwargs={})
            )
        )
        self.assertFalse(
            self.policy.has_permission(
                request, SimpleNamespace(action="destroy", kwargs={})
            )
        )

    @patch("authorization.runtime.initialize_request_authorization")
    def test_deactivate_permission_does_not_allow_editing(self, mock_initialize):
        facade = Mock()
        facade.context.unrestricted = False
        facade.permission_scope.side_effect = lambda code: (
            "all" if code == "users.deactivate" else None
        )
        mock_initialize.return_value = facade
        request = SimpleNamespace(user=self.user, method="DELETE")

        self.assertTrue(
            self.policy.has_permission(
                request, SimpleNamespace(action="destroy", kwargs={})
            )
        )
        self.assertFalse(
            self.policy.has_permission(
                request, SimpleNamespace(action="update", kwargs={})
            )
        )

    def test_platform_superadmin_bypasses_user_action_permissions(self):
        request = SimpleNamespace(
            method="DELETE",
            user=SimpleNamespace(
                is_authenticated=True,
                is_anonymous=False,
                is_platform_superuser=True,
            )
        )

        self.assertTrue(
            self.policy.has_permission(
                request, SimpleNamespace(action="destroy", kwargs={})
            )
        )

    @patch("authorization.runtime.initialize_request_authorization")
    def test_current_user_endpoint_does_not_require_management_permission(
        self,
        mock_initialize,
    ):
        facade = Mock()
        facade.context.unrestricted = False
        facade.context.role_id = ""
        facade.permission_scope.return_value = None
        mock_initialize.return_value = facade
        request = SimpleNamespace(user=self.user, method="GET")

        self.assertTrue(
            self.policy.has_permission(
                request,
                SimpleNamespace(action="current", kwargs={}),
            )
        )