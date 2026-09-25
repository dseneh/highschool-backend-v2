from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from users.step_up import (
    changed_fields,
    enforce_step_up_for_sensitive_changes,
    enforce_step_up,
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

    @patch("users.step_up.schema_context", return_value=nullcontext())
    @patch("users.step_up.transaction.atomic", return_value=nullcontext())
    @patch("users.step_up.connection")
    @patch("users.models.StepUpAuthorization")
    def test_reusable_grant_is_resolved_from_bound_session_without_bearer_token(
        self,
        authorization_model,
        connection,
        _atomic,
        _schema_context,
    ):
        connection.schema_name = "school"
        proof = SimpleNamespace(pk="proof-1", reusable=True)
        base_query = MagicMock()
        reusable_query = MagicMock()
        reusable_query.first.return_value = proof
        base_query.filter.return_value = reusable_query
        authorization_model.objects.select_for_update.return_value.filter.return_value = base_query
        request = SimpleNamespace(
            headers={},
            user=SimpleNamespace(pk="user-1", security_version=3),
            _step_up_session_binding="tenant:session-1",
        )

        enforce_step_up(
            request,
            action="bank_account_changes",
            context="bank-1",
            required=True,
        )

        base_query.filter.assert_called_once_with(reusable=True)
        authorization_model.objects.filter.assert_called_once_with(pk="proof-1")
        update_values = authorization_model.objects.filter.return_value.update.call_args.kwargs
        self.assertIn("last_used_at", update_values)
        self.assertIn("use_count", update_values)
        self.assertNotIn("used_at", update_values)
