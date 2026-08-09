from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError

from staff.services.staff_service import StaffService


class StaffUserAccountEmailRequirementTests(SimpleTestCase):
    def _build_staff(self, email):
        staff = SimpleNamespace(
            id_number="EMP001",
            first_name="Ada",
            last_name="Lovelace",
            gender="female",
            email=email,
            school=SimpleNamespace(name="Test School"),
            user_account_id_number=None,
        )
        staff.save = MagicMock()
        return staff

    def test_create_user_account_requires_valid_staff_email(self):
        staff = self._build_staff("")

        duplicate_qs = MagicMock()
        duplicate_qs.exists.return_value = False

        with patch("users.models.User.objects.filter", return_value=duplicate_qs):
            with self.assertRaises(ValidationError) as ctx:
                StaffService._create_user_account(staff, data={}, user=SimpleNamespace(username="admin"))

        self.assertIn("email", ctx.exception.detail)

    def test_create_user_account_uses_staff_email_without_fallback(self):
        staff = self._build_staff("ada@example.org")

        duplicate_qs = MagicMock()
        duplicate_qs.exists.return_value = False

        created_user = SimpleNamespace(id_number="EMP001")
        created_user.set_password = MagicMock()
        created_user.save = MagicMock()

        with patch("users.models.User.objects.filter", return_value=duplicate_qs):
            with patch("users.models.User.objects.create_user", return_value=created_user) as mock_create_user:
                StaffService._create_user_account(staff, data={}, user=SimpleNamespace(username="admin"))

        self.assertEqual(mock_create_user.call_args.kwargs["email"], "ada@example.org")
