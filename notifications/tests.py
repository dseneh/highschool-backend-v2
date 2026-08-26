from django.test import SimpleTestCase
from unittest.mock import MagicMock, patch

from rest_framework.exceptions import PermissionDenied

from notifications.services.teacher_scope import assert_teacher_can_target_audience


class TeacherScopeTest(SimpleTestCase):
    @patch("notifications.services.teacher_scope.user_has_permission")
    def test_class_sender_denied_school_wide(self, mock_has_permission):
        mock_has_permission.side_effect = lambda _user, code: code == "notifications.send_class"
        user = MagicMock()
        with patch(
            "notifications.services.teacher_scope.get_teacher_section_ids",
            return_value={},
        ):
            with self.assertRaises(PermissionDenied):
                assert_teacher_can_target_audience(user, {"scope": "all"})

    @patch("notifications.services.teacher_scope.user_has_permission")
    def test_school_wide_sender_is_not_assignment_limited(self, mock_has_permission):
        mock_has_permission.side_effect = lambda _user, code: code == "notifications.send"

        assert_teacher_can_target_audience(MagicMock(), {"scope": "all"})

    @patch("notifications.services.teacher_scope.user_has_permission", return_value=False)
    def test_user_without_send_permission_is_denied(self, _mock_has_permission):
        with self.assertRaises(PermissionDenied):
            assert_teacher_can_target_audience(MagicMock(), {"scope": "all"})
