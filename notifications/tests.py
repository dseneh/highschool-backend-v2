from django.test import SimpleTestCase
from unittest.mock import MagicMock, patch

from rest_framework.exceptions import PermissionDenied

from notifications.services.teacher_scope import assert_teacher_can_target_audience


class TeacherScopeTest(SimpleTestCase):
    def test_teacher_denied_school_wide(self):
        user = MagicMock()
        user.role = "teacher"
        with patch(
            "notifications.services.teacher_scope.get_teacher_section_ids",
            return_value={},
        ):
            with self.assertRaises(PermissionDenied):
                assert_teacher_can_target_audience(user, {"scope": "all"})
