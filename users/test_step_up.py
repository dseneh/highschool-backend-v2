from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from users.step_up import (
    changed_fields,
    enforce_step_up_for_sensitive_changes,
    get_step_up_grant_policy,
    request_session_binding,
)


class StepUpSensitiveChangeTests(SimpleTestCase):
    def test_reusable_and_operation_grant_policies_have_expected_scope(self):
        self.assertEqual(
            get_step_up_grant_policy("bank_account_changes"),
            {"ttl_seconds": 3600, "reusable": True},
        )
        self.assertEqual(
            get_step_up_grant_policy("backup_restore"),
            {"ttl_seconds": 300, "reusable": False},
        )

    def test_request_session_binding_prefers_authentication_binding(self):
        request = SimpleNamespace(
            _step_up_session_binding="tenant:session-1",
            auth={"session_id": "jwt-session"},
        )

        self.assertEqual(request_session_binding(request), "tenant:session-1")

    def test_changed_fields_ignores_unsubmitted_and_equal_values(self):
        instance = SimpleNamespace(
            bank_name="Current Bank",
            opening_balance=100,
            status="active",
        )

        self.assertEqual(
            changed_fields(
                instance,
                {"bank_name": "Current Bank", "status": "active"},
            ),
            set(),
        )

    def test_changed_fields_compares_related_objects_by_primary_key(self):
        current_currency = SimpleNamespace(pk="currency-1")
        submitted_currency = SimpleNamespace(pk="currency-1")
        instance = SimpleNamespace(currency=current_currency)

        self.assertEqual(
            changed_fields(instance, {"currency": submitted_currency}),
            set(),
        )

    @patch("users.step_up.enforce_step_up")
    def test_non_sensitive_change_does_not_require_step_up(self, enforce_step_up):
        instance = SimpleNamespace(bank_name="Old Bank", status="active")

        changes = enforce_step_up_for_sensitive_changes(
            MagicMock(),
            action="bank_account_changes",
            context="bank-1",
            instance=instance,
            validated_data={"bank_name": "New Bank"},
            sensitive_fields={"status", "opening_balance"},
        )

        self.assertEqual(changes, set())
        enforce_step_up.assert_not_called()

    @patch("users.step_up.enforce_step_up")
    def test_sensitive_change_requires_step_up(self, enforce_step_up):
        request = MagicMock()
        instance = SimpleNamespace(bank_name="Old Bank", status="active")

        changes = enforce_step_up_for_sensitive_changes(
            request,
            action="bank_account_changes",
            context="bank-1",
            instance=instance,
            validated_data={"bank_name": "New Bank", "status": "closed"},
        )

        self.assertEqual(changes, {"status"})
        enforce_step_up.assert_called_once_with(
            request,
            action="bank_account_changes",
            context="bank-1",
            sensitive_fields={"status"},
        )

    def test_changed_fields_supports_mapping_snapshots(self):
        current = {
            "is_active": True,
            "permissions": (("roles.view", "all"),),
        }
        submitted = {
            "is_active": True,
            "permissions": (("roles.view", "all"),),
        }

        self.assertEqual(changed_fields(current, submitted), set())
