from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase
from rest_framework.exceptions import PermissionDenied

from grading.services.grade_access import enforce_grade_access


class GradeAccessTests(SimpleTestCase):
    @patch("settings.models.GradingSettings.objects.first")
    @patch("students.services.balance.get_student_effective_outstanding_balance")
    def test_blocks_academic_downloads_when_balance_setting_is_disabled(
        self,
        mock_balance,
        mock_settings,
    ):
        mock_settings.return_value = SimpleNamespace(
            allow_grade_view_with_outstanding_balance=False,
        )
        mock_balance.return_value = Decimal("500.00")

        with self.assertRaises(PermissionDenied) as raised:
            enforce_grade_access(SimpleNamespace(), None)

        self.assertEqual(
            raised.exception.detail["code"],
            "grades_restricted_outstanding_balance",
        )

    @patch("settings.models.GradingSettings.objects.first")
    @patch("students.services.balance.get_student_effective_outstanding_balance")
    def test_allows_academic_downloads_when_setting_is_enabled(
        self,
        mock_balance,
        mock_settings,
    ):
        mock_settings.return_value = SimpleNamespace(
            allow_grade_view_with_outstanding_balance=True,
        )
        mock_balance.return_value = Decimal("500.00")

        enforce_grade_access(SimpleNamespace(), None)