import uuid
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from notifications.services.audience import user_wants_email


class NotificationAudienceEmailRequirementTests(SimpleTestCase):
    def test_user_wants_email_false_for_invalid_email(self):
        user_id = uuid.uuid4()

        with patch("notifications.services.audience.schema_context", side_effect=lambda _schema: nullcontext()):
            with patch("notifications.services.audience.User.objects.get", return_value=SimpleNamespace(email="invalid")):
                result = user_wants_email(user_id, "announcement")

        self.assertFalse(result)

    def test_user_wants_email_true_for_valid_email_without_preference(self):
        user_id = uuid.uuid4()
        pref_qs = MagicMock()
        pref_qs.first.return_value = None

        with patch("notifications.services.audience.schema_context", side_effect=lambda _schema: nullcontext()):
            with patch("notifications.services.audience.User.objects.get", return_value=SimpleNamespace(email="user@example.org")):
                with patch("notifications.models.UserNotificationPreference.objects.filter", return_value=pref_qs):
                    result = user_wants_email(user_id, "announcement")

        self.assertTrue(result)
