from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from accounting.views.cash_transaction import AccountingCashTransactionViewSet
from employee_benefits.permissions import user_can_manage_employee_benefit_assignments


class ActiveRoleReplacementTests(SimpleTestCase):
    @patch("authorization.runtime.user_has_permission")
    def test_accounting_completion_uses_complete_permission(self, has_permission):
        has_permission.side_effect = lambda _user, code: code == "finance.transactions.complete"
        user = SimpleNamespace()
        view = AccountingCashTransactionViewSet()

        self.assertTrue(view._can_complete_transaction(user))
        has_permission.assert_called_with(user, "finance.transactions.complete")

    @patch("authorization.runtime.user_has_permission")
    def test_accounting_warning_override_uses_approve_permission(self, has_permission):
        has_permission.side_effect = lambda _user, code: code == "finance.transactions.approve"
        user = SimpleNamespace()
        view = AccountingCashTransactionViewSet()

        self.assertTrue(view._can_override_limit_warning(user))
        has_permission.assert_called_with(user, "finance.transactions.approve")

    @patch("employee_benefits.permissions.user_has_permission")
    def test_benefit_management_uses_hr_manage_permission(self, has_permission):
        has_permission.return_value = True
        user = SimpleNamespace(is_authenticated=True)

        self.assertTrue(user_can_manage_employee_benefit_assignments(user))
        has_permission.assert_called_once_with(user, "hr.manage")

    @patch("employee_benefits.permissions.user_has_permission")
    def test_benefit_management_denies_missing_permission(self, has_permission):
        has_permission.return_value = False
        user = SimpleNamespace(is_authenticated=True)

        self.assertFalse(user_can_manage_employee_benefit_assignments(user))
