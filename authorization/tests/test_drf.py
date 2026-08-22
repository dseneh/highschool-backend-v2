from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from authorization.drf import RBACPermission


class RBACPermissionTests(SimpleTestCase):
    def setUp(self):
        self.permission = RBACPermission()
        self.request = SimpleNamespace(
            user=SimpleNamespace(is_authenticated=True),
            method="GET",
        )

    def test_missing_permission_map_fails_closed(self):
        self.assertFalse(
            self.permission.has_permission(self.request, SimpleNamespace())
        )

    @patch("authorization.drf.initialize_request_authorization")
    def test_mapped_action_checks_exact_permission(self, mock_initialize):
        facade = Mock()
        facade.permission_scope.return_value = "all"
        mock_initialize.return_value = facade
        view = SimpleNamespace(
            action="list",
            permission_map={"list": "students.view"},
        )

        self.assertTrue(self.permission.has_permission(self.request, view))
        facade.permission_scope.assert_called_once_with("students.view")

    @patch("authorization.drf.initialize_request_authorization")
    def test_viewset_action_takes_precedence_over_http_method(self, mock_initialize):
        facade = Mock()
        facade.permission_scope.return_value = "all"
        mock_initialize.return_value = facade
        view = SimpleNamespace(
            action="approve",
            permission_map={
                "get": "grades.view",
                "approve": "grades.approve",
            },
        )

        self.permission.has_permission(self.request, view)

        facade.permission_scope.assert_called_once_with("grades.approve")

    @patch("authorization.drf.initialize_request_authorization")
    def test_api_view_uses_lowercase_http_method(self, mock_initialize):
        facade = Mock()
        facade.permission_scope.return_value = "all"
        mock_initialize.return_value = facade
        view = SimpleNamespace(permission_map={"get": "students.view"})

        self.assertTrue(self.permission.has_permission(self.request, view))

    @patch("authorization.drf.initialize_request_authorization")
    def test_scoped_list_requires_explicit_action_scope_hook(self, mock_initialize):
        facade = Mock()
        facade.permission_scope.return_value = "assigned"
        mock_initialize.return_value = facade
        view = SimpleNamespace(
            action="list",
            permission_map={"list": "students.view"},
        )

        self.assertFalse(self.permission.has_permission(self.request, view))

    @patch("authorization.drf.initialize_request_authorization")
    def test_scoped_list_can_use_domain_action_scope_hook(self, mock_initialize):
        facade = Mock()
        facade.permission_scope.return_value = "assigned"
        mock_initialize.return_value = facade
        scope_checker = Mock(return_value=True)
        view = SimpleNamespace(
            action="list",
            permission_map={"list": "students.view"},
            has_rbac_action_scope=scope_checker,
        )

        self.assertTrue(self.permission.has_permission(self.request, view))
        scope_checker.assert_called_once()

    @patch("authorization.drf.initialize_request_authorization")
    def test_object_scope_requires_domain_checker(self, mock_initialize):
        facade = Mock()
        facade.permission_scope.return_value = "assigned"
        mock_initialize.return_value = facade
        view = SimpleNamespace(
            action="retrieve",
            permission_map={"retrieve": "students.view"},
        )

        self.assertFalse(
            self.permission.has_object_permission(self.request, view, object())
        )

    @patch("authorization.drf.initialize_request_authorization")
    def test_all_scope_allows_object(self, mock_initialize):
        facade = Mock()
        facade.permission_scope.return_value = "all"
        mock_initialize.return_value = facade
        view = SimpleNamespace(
            action="retrieve",
            permission_map={"retrieve": "students.view"},
        )

        self.assertTrue(
            self.permission.has_object_permission(self.request, view, object())
        )

    @patch("authorization.drf.initialize_request_authorization")
    def test_evaluator_failure_fails_closed(self, mock_initialize):
        mock_initialize.side_effect = RuntimeError("cache failed")
        view = SimpleNamespace(
            action="list",
            permission_map={"list": "students.view"},
        )

        self.assertFalse(self.permission.has_permission(self.request, view))
