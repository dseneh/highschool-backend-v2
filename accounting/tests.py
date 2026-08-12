from decimal import Decimal
from contextlib import nullcontext
from unittest.mock import MagicMock, patch

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.http import HttpResponse
from django.test import SimpleTestCase, TestCase
from rest_framework.response import Response
from types import SimpleNamespace

from accounting.services.posting import post_cash_transaction_to_ledger
from accounting.services.post_all import execute_post_all
from accounting.services.bank_rules import (
    default_email_template,
    evaluate_transaction_limits,
    notification_balance_statuses,
    resolve_limit_amount,
    render_email_template,
    validate_template_placeholders,
)
from accounting.services.student_billing import (
    build_billing_lines_for_enrollment,
    get_enrollment_arrears_amount,
    sync_accounting_bill_concession_totals,
)
from accounting.views.base import AccountingErrorFormattingMixin
from accounting.views.cash_transaction import (
    AccountingBankAccountViewSet,
    AccountingCashTransactionViewSet,
)
from accounting.models import AccountingCashTransaction, AccountingJournalEntry
from accounting.serializers import AccountingSettingsSerializer


class AccountingBankRuleTemplateServiceTests(SimpleTestCase):
    def test_validate_template_placeholders_allows_supported_tokens(self):
        validate_template_placeholders(
            "Subject {{tenant_name}} {{rule_name}}",
            "Body {{account_name}} {{current_balance}} {{maximum_balance}}",
        )

    def test_validate_template_placeholders_rejects_unknown_tokens(self):
        with self.assertRaises(ValidationError):
            validate_template_placeholders("Hello {{unsupported_value}}")

    def test_render_email_template_replaces_placeholders(self):
        rendered = render_email_template(
            "Rule {{rule_name}} on {{account_name}}",
            {
                "rule_name": "Main Balance",
                "account_name": "Operations Account",
            },
        )

        self.assertEqual(rendered, "Rule Main Balance on Operations Account")

    def test_default_template_contains_required_sections(self):
        template = default_email_template()
        self.assertIn("{{rule_name}}", template["subject"])
        self.assertIn("{{current_balance}}", template["body"])


class AccountingBankRuleNotificationStatusTests(SimpleTestCase):
    def test_pending_trigger_uses_projected_statuses(self):
        self.assertEqual(notification_balance_statuses("pending"), ["pending", "approved", "completed"])

    def test_approved_trigger_uses_approved_and_completed_statuses(self):
        self.assertEqual(notification_balance_statuses("approved"), ["approved", "completed"])

    def test_completed_trigger_uses_completed_status_only(self):
        self.assertEqual(notification_balance_statuses("completed"), ["completed"])


class AccountingTransactionLimitScopeTests(SimpleTestCase):
    @patch("accounting.services.bank_rules.resolve_limit_amount", return_value=Decimal("90.00"))
    @patch("accounting.services.bank_rules.account_balance_for_statuses")
    @patch("accounting.services.bank_rules.AccountingSpendableAllocationRule.objects.filter")
    @patch("accounting.services.bank_rules.AccountingBankBalanceRule.objects.filter")
    def test_income_evaluates_max_balance_only(
        self,
        mock_balance_rule_filter,
        mock_spend_rule_filter,
        mock_balance_for_statuses,
        _mock_resolve_limit,
    ):
        rule = SimpleNamespace(
            name="Income Max Rule",
            limit_mode="fixed",
            fixed_maximum_balance=Decimal("90.00"),
            revenue_percentage=None,
            revenue_period="monthly",
            behavior="warn",
            alert_threshold_percentage=Decimal("90.00"),
            enable_email_alerts=False,
        )
        rule_qs = MagicMock()
        rule_qs.prefetch_related.return_value = [rule]
        mock_balance_rule_filter.return_value = rule_qs
        mock_balance_for_statuses.side_effect = [Decimal("100.00"), Decimal("100.00")]

        result = evaluate_transaction_limits(
            bank_account=SimpleNamespace(account_name="Ops Account"),
            transaction_type=SimpleNamespace(transaction_category="income", code="INCOME"),
            base_amount=Decimal("20.00"),
            persist_threshold_state=False,
        )

        self.assertTrue(result.requires_warning_confirmation)
        self.assertEqual(len(result.details), 1)
        self.assertEqual(result.details[0]["rule_name"], "Income Max Rule")
        self.assertIsNone(result.details[0].get("kind"))
        mock_spend_rule_filter.assert_not_called()

    @patch("accounting.services.bank_rules.resolve_limit_amount", return_value=Decimal("200.00"))
    @patch("accounting.services.bank_rules.resolve_revenue_basis", return_value=Decimal("100000.00"))
    @patch("accounting.services.bank_rules.AccountingCashTransaction.objects.filter")
    @patch("accounting.services.bank_rules.account_balance_for_statuses")
    @patch("accounting.services.bank_rules.AccountingSpendableAllocationRule.objects.filter")
    @patch("accounting.services.bank_rules.AccountingBankBalanceRule.objects.filter")
    def test_expense_evaluates_spendable_only(
        self,
        mock_balance_rule_filter,
        mock_spend_rule_filter,
        mock_balance_for_statuses,
        mock_cash_tx_filter,
        _mock_revenue_basis,
        _mock_resolve_limit,
    ):
        spend_rule_qs = MagicMock()
        spend_rule_qs.order_by.return_value.first.return_value = SimpleNamespace(
            name="Spendable Rule",
            limit_mode="fixed",
            fixed_allocation=Decimal("200.00"),
            revenue_percentage=None,
            revenue_period="monthly",
            behavior="warn",
        )
        mock_spend_rule_filter.return_value = spend_rule_qs
        mock_balance_for_statuses.side_effect = [Decimal("500.00"), Decimal("500.00")]
        mock_cash_tx_filter.return_value.aggregate.return_value = {"total": Decimal("100.00")}

        result = evaluate_transaction_limits(
            bank_account=SimpleNamespace(account_name="Ops Account"),
            transaction_type=SimpleNamespace(transaction_category="expense", code="EXPENSE"),
            base_amount=Decimal("50.00"),
            persist_threshold_state=False,
        )

        mock_balance_rule_filter.assert_not_called()
        self.assertEqual(len(result.details), 1)
        self.assertEqual(result.details[0]["kind"], "spendable_allocation")
        self.assertFalse(result.should_block)
        self.assertFalse(result.requires_warning_confirmation)

    @patch("accounting.services.bank_rules.resolve_limit_amount", return_value=Decimal("200.00"))
    @patch("accounting.services.bank_rules.resolve_revenue_basis", return_value=Decimal("100000.00"))
    @patch("accounting.services.bank_rules.AccountingCashTransaction.objects.filter")
    @patch("accounting.services.bank_rules.account_balance_for_statuses")
    @patch("accounting.services.bank_rules.AccountingSpendableAllocationRule.objects.filter")
    @patch("accounting.services.bank_rules.AccountingBankBalanceRule.objects.filter")
    def test_expense_zero_amount_still_returns_spendable_snapshot(
        self,
        mock_balance_rule_filter,
        mock_spend_rule_filter,
        mock_balance_for_statuses,
        mock_cash_tx_filter,
        _mock_revenue_basis,
        _mock_resolve_limit,
    ):
        spend_rule_qs = MagicMock()
        spend_rule_qs.order_by.return_value.first.return_value = SimpleNamespace(
            name="Spendable Rule",
            limit_mode="fixed",
            fixed_allocation=Decimal("200.00"),
            revenue_percentage=None,
            revenue_period="monthly",
            behavior="warn",
        )
        mock_spend_rule_filter.return_value = spend_rule_qs
        mock_balance_for_statuses.side_effect = [Decimal("500.00"), Decimal("500.00")]
        mock_cash_tx_filter.return_value.aggregate.return_value = {"total": Decimal("120.00")}

        result = evaluate_transaction_limits(
            bank_account=SimpleNamespace(account_name="Ops Account"),
            transaction_type=SimpleNamespace(transaction_category="expense", code="EXPENSE"),
            base_amount=Decimal("0.00"),
            persist_threshold_state=False,
        )

        mock_balance_rule_filter.assert_not_called()
        self.assertEqual(len(result.details), 1)
        self.assertEqual(result.details[0]["kind"], "spendable_allocation")
        self.assertEqual(result.details[0]["current_balance"], "120.00")
        self.assertEqual(result.details[0]["projected_balance"], "120.00")


class AccountingLimitPrecheckApiValidationTests(SimpleTestCase):
    @patch("accounting.views.cash_transaction.evaluate_transaction_limits")
    @patch("accounting.views.cash_transaction.AccountingTransactionType.objects.get")
    @patch("accounting.views.cash_transaction.AccountingBankAccount.objects.get")
    def test_expense_limit_precheck_allows_missing_amount(
        self,
        mock_bank_get,
        mock_type_get,
        mock_evaluate,
    ):
        viewset = AccountingCashTransactionViewSet()
        request = SimpleNamespace(data={"bank_account": "bank-1", "transaction_type": "tx-1"})
        viewset.request = request

        mock_bank_get.return_value = SimpleNamespace(id="bank-1")
        mock_type_get.return_value = SimpleNamespace(id="tx-1", transaction_category="expense", code="EXPENSE")
        mock_evaluate.return_value = SimpleNamespace(
            should_block=False,
            requires_warning_confirmation=False,
            warning_messages=[],
            blocking_messages=[],
            details=[],
        )

        response = viewset.limit_precheck(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_evaluate.call_args.kwargs["base_amount"], Decimal("0"))

    @patch("accounting.views.cash_transaction.AccountingTransactionType.objects.get")
    @patch("accounting.views.cash_transaction.AccountingBankAccount.objects.get")
    def test_income_limit_precheck_still_requires_amount(
        self,
        mock_bank_get,
        mock_type_get,
    ):
        viewset = AccountingCashTransactionViewSet()
        request = SimpleNamespace(data={"bank_account": "bank-1", "transaction_type": "tx-1"})
        viewset.request = request

        mock_bank_get.return_value = SimpleNamespace(id="bank-1")
        mock_type_get.return_value = SimpleNamespace(id="tx-1", transaction_category="income", code="INCOME")

        response = viewset.limit_precheck(request)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["detail"], "amount or base_amount is required.")


class AccountingSettingsSerializerTests(SimpleTestCase):
    def test_includes_salary_advance_repayment_mapping(self):
        account = SimpleNamespace(pk="ledger-1", id="ledger-1", name="Early Salary Repayments", code="L-REP-001")
        settings = SimpleNamespace(salary_advance_repayment_ledger_account=account)

        payload = AccountingSettingsSerializer(settings).data

        self.assertEqual(payload["salary_advance_repayment_ledger_account"], "ledger-1")
        self.assertEqual(payload["salary_advance_repayment_ledger_account_name"], "Early Salary Repayments")
        self.assertEqual(payload["salary_advance_repayment_ledger_account_code"], "L-REP-001")


class AccountingLimitAmountResolutionTests(SimpleTestCase):
    @patch("accounting.services.bank_rules.resolve_revenue_basis", return_value=Decimal("100000.00"))
    def test_percent_revenue_mode_uses_percentage_of_revenue(self, _mock_revenue_basis):
        result = resolve_limit_amount(
            "percent_revenue",
            fixed_value=None,
            percent_value=Decimal("30.00"),
            revenue_period="all_time",
        )

        self.assertEqual(result, Decimal("30000.00"))

    @patch("accounting.services.bank_rules.resolve_revenue_basis", return_value=Decimal("100000.00"))
    def test_legacy_percentage_mode_alias_uses_percentage_of_revenue(self, _mock_revenue_basis):
        result = resolve_limit_amount(
            "percentage",
            fixed_value=None,
            percent_value=Decimal("30.00"),
            revenue_period="all_time",
        )

        self.assertEqual(result, Decimal("30000.00"))

    def test_fixed_amount_mode_uses_fixed_limit(self):
        result = resolve_limit_amount(
            "fixed_amount",
            fixed_value=Decimal("100000.00"),
            percent_value=Decimal("30.00"),
            revenue_period="all_time",
        )

        self.assertEqual(result, Decimal("100000.00"))

    def test_legacy_flat_mode_alias_uses_fixed_limit(self):
        result = resolve_limit_amount(
            "flat",
            fixed_value=Decimal("100000.00"),
            percent_value=Decimal("30.00"),
            revenue_period="all_time",
        )

        self.assertEqual(result, Decimal("100000.00"))


class AccountingPostingServiceTests(SimpleTestCase):
    def _build_cash_transaction(self, category="income", status="approved"):
        bank_ledger = MagicMock(name="bank_ledger")
        counter_ledger = MagicMock(name="counter_ledger")

        bank_account = MagicMock()
        bank_account.ledger_account = bank_ledger

        transaction_type = MagicMock()
        transaction_type.transaction_category = category
        transaction_type.default_ledger_account = counter_ledger

        cash_tx = MagicMock()
        cash_tx.journal_entry_id = None
        cash_tx.journal_entry = None
        cash_tx.status = status
        cash_tx.bank_account = bank_account
        cash_tx.transaction_type = transaction_type
        cash_tx.ledger_account = None
        cash_tx.transaction_date = "2026-09-20"
        cash_tx.reference_number = "TXN-001"
        cash_tx.description = "Test transaction"
        cash_tx.amount = Decimal("100.00")
        cash_tx.currency = MagicMock(name="currency")
        cash_tx.exchange_rate = Decimal("1")
        cash_tx.base_amount = Decimal("100.00")

        return cash_tx, bank_ledger, counter_ledger

    def test_returns_existing_journal_when_already_posted(self):
        cash_tx, _, _ = self._build_cash_transaction()
        existing_journal = MagicMock(name="existing_journal")
        cash_tx.journal_entry_id = "already-linked"
        cash_tx.journal_entry = existing_journal

        result = post_cash_transaction_to_ledger(cash_tx)

        self.assertIs(result, existing_journal)

    def test_rejects_non_approved_transactions(self):
        cash_tx, _, _ = self._build_cash_transaction(status="pending")

        with self.assertRaises(ValidationError):
            post_cash_transaction_to_ledger(cash_tx)

    @patch("accounting.services.posting.AccountingJournalLine.objects.create")
    @patch("accounting.services.posting.AccountingJournalEntry.objects.create")
    @patch("accounting.services.posting._resolve_academic_year")
    @patch("accounting.services.posting.db_transaction.atomic")
    def test_allows_completed_transactions_to_post(
        self,
        mock_atomic,
        mock_resolve_academic_year,
        mock_journal_entry_create,
        mock_journal_line_create,
    ):
        cash_tx, _, _ = self._build_cash_transaction(status="completed")
        mock_atomic.return_value = nullcontext()
        mock_resolve_academic_year.return_value = MagicMock(name="academic_year")
        mock_journal_entry_create.return_value = MagicMock(name="journal_entry")

        result = post_cash_transaction_to_ledger(cash_tx)

        self.assertIsNotNone(result)
        self.assertEqual(mock_journal_line_create.call_count, 2)

    @patch("accounting.services.posting.AccountingJournalLine.objects.create")
    @patch("accounting.services.posting.AccountingJournalEntry.objects.create")
    @patch("accounting.services.posting._resolve_academic_year")
    @patch("accounting.services.posting.db_transaction.atomic")
    def test_posts_income_transaction_to_ledger(
        self,
        mock_atomic,
        mock_resolve_academic_year,
        mock_journal_entry_create,
        mock_journal_line_create,
    ):
        cash_tx, bank_ledger, counter_ledger = self._build_cash_transaction(category="income")
        mock_atomic.return_value = nullcontext()
        mock_resolve_academic_year.return_value = MagicMock(name="academic_year")
        journal_entry = MagicMock(name="journal_entry")
        journal_entry.id = "je-1"
        mock_journal_entry_create.return_value = journal_entry

        result = post_cash_transaction_to_ledger(cash_tx)

        self.assertIs(result, journal_entry)
        self.assertEqual(mock_journal_line_create.call_count, 2)

        first_call = mock_journal_line_create.call_args_list[0].kwargs
        second_call = mock_journal_line_create.call_args_list[1].kwargs

        self.assertIs(first_call["ledger_account"], bank_ledger)
        self.assertEqual(first_call["debit_amount"], Decimal("100.00"))
        self.assertIs(second_call["ledger_account"], counter_ledger)
        self.assertEqual(second_call["credit_amount"], Decimal("100.00"))

        cash_tx.save.assert_called_once()

    @patch("accounting.services.posting.AccountingJournalLine.objects.create")
    @patch("accounting.services.posting.AccountingJournalEntry.objects.create")
    @patch("accounting.services.posting._resolve_academic_year")
    @patch("accounting.services.posting.db_transaction.atomic")
    def test_posts_expense_transaction_to_ledger(
        self,
        mock_atomic,
        mock_resolve_academic_year,
        mock_journal_entry_create,
        mock_journal_line_create,
    ):
        cash_tx, bank_ledger, counter_ledger = self._build_cash_transaction(category="expense")
        mock_atomic.return_value = nullcontext()
        mock_resolve_academic_year.return_value = MagicMock(name="academic_year")
        mock_journal_entry_create.return_value = MagicMock(name="journal_entry")

        post_cash_transaction_to_ledger(cash_tx)

        first_call = mock_journal_line_create.call_args_list[0].kwargs
        second_call = mock_journal_line_create.call_args_list[1].kwargs

        self.assertIs(first_call["ledger_account"], counter_ledger)
        self.assertEqual(first_call["debit_amount"], Decimal("100.00"))
        self.assertIs(second_call["ledger_account"], bank_ledger)
        self.assertEqual(second_call["credit_amount"], Decimal("100.00"))

    @patch("accounting.services.posting.AccountingJournalLine.objects.create")
    @patch("accounting.services.posting.AccountingJournalEntry.objects.create")
    @patch("accounting.services.posting._resolve_academic_year")
    @patch("accounting.services.posting.db_transaction.atomic")
    def test_post_retries_with_unique_reference_on_duplicate_key(
        self,
        mock_atomic,
        mock_resolve_academic_year,
        mock_journal_entry_create,
        mock_journal_line_create,
    ):
        cash_tx, _, _ = self._build_cash_transaction(category="income")
        cash_tx.reference_number = "123"
        mock_atomic.return_value = nullcontext()
        mock_resolve_academic_year.return_value = MagicMock(name="academic_year")

        created_entry = MagicMock(name="journal_entry")
        created_entry.id = "je-1"
        mock_journal_entry_create.side_effect = [
            IntegrityError(
                'duplicate key value violates unique constraint "accounting_journal_entry_reference_number_key"'
            ),
            created_entry,
        ]

        result = post_cash_transaction_to_ledger(cash_tx)

        self.assertIs(result, created_entry)
        self.assertEqual(mock_journal_entry_create.call_count, 2)
        first_call = mock_journal_entry_create.call_args_list[0].kwargs
        second_call = mock_journal_entry_create.call_args_list[1].kwargs
        self.assertEqual(first_call["reference_number"], "123")
        self.assertEqual(second_call["reference_number"], "123-2")
        self.assertEqual(mock_journal_line_create.call_count, 2)

    def test_rejects_missing_posting_mapping(self):
        cash_tx, _, _ = self._build_cash_transaction()
        cash_tx.transaction_type.default_ledger_account = None
        cash_tx.ledger_account = None

        with self.assertRaises(ValidationError):
            post_cash_transaction_to_ledger(cash_tx)

    @patch("accounting.services.posting._resolve_academic_year")
    def test_rejects_invalid_transaction_category(self, mock_resolve_academic_year):
        cash_tx, _, _ = self._build_cash_transaction(category="transfer")
        mock_resolve_academic_year.return_value = MagicMock(name="academic_year")

        with self.assertRaises(ValidationError):
            post_cash_transaction_to_ledger(cash_tx)


class AccountingBulkPostAllTests(SimpleTestCase):
    @patch("accounting.services.post_all.transaction.atomic", return_value=nullcontext())
    @patch("accounting.services.post_all.recalculate_bank_account_current_balance")
    @patch("accounting.services.post_all.post_cash_transaction_to_ledger")
    @patch("accounting.services.post_all.get_eligible_post_all_queryset")
    def test_execute_post_all_sets_status_completed_after_post(
        self,
        mock_get_eligible,
        mock_post,
        mock_recalc,
        _mock_atomic,
    ):
        cash_tx = MagicMock()
        cash_tx.id = "tx-1"
        cash_tx.status = AccountingCashTransaction.TransactionStatus.APPROVED
        cash_tx.bank_account_id = None
        cash_tx.completed_by = None
        cash_tx.completed_at = None

        class _Eligible:
            def values_list(self, *args, **kwargs):
                return [cash_tx.id]

            def iterator(self, chunk_size=200):
                return iter([cash_tx])

        mock_get_eligible.return_value = _Eligible()
        mock_post.return_value = SimpleNamespace(id="je-1")

        result = execute_post_all(
            user_id=None,
            apply_filters=True,
            filter_params={},
        )

        self.assertEqual(result["posted_count"], 1)
        self.assertEqual(result["skipped_count"], 0)
        self.assertEqual(cash_tx.status, AccountingCashTransaction.TransactionStatus.COMPLETED)
        self.assertIsNotNone(cash_tx.completed_at)
        cash_tx.save.assert_called_once()
        mock_recalc.assert_not_called()


class _DummyBaseView:
    def handle_exception(self, exc):
        return Response({"amount": ["A valid number is required."]}, status=400)

    def finalize_response(self, request, response, *args, **kwargs):
        return response


class _DummyAccountingView(AccountingErrorFormattingMixin, _DummyBaseView):
    pass


class AccountingErrorFormattingMixinTests(SimpleTestCase):
    def setUp(self):
        self.view = _DummyAccountingView()

    def test_extract_detail_from_field_errors(self):
        detail = self.view._extract_detail({"amount": ["A valid number is required."]})
        self.assertEqual(detail, "A valid number is required.")

    def test_extract_detail_from_list_payload(self):
        detail = self.view._extract_detail(["Request is invalid"])
        self.assertEqual(detail, "Request is invalid")

    def test_handle_exception_normalizes_to_detail_shape(self):
        response = self.view.handle_exception(Exception("boom"))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data, {"detail": "A valid number is required."})

    def test_finalize_response_normalizes_non_detail_error_payload(self):
        response = Response({"status": "bad"}, status=400)
        normalized = self.view.finalize_response(None, response)
        self.assertEqual(normalized.data, {"detail": "bad"})


class AccountingBillConcessionSyncTests(TestCase):
    @patch("accounting.services.student_billing.AccountingConcession.objects.filter")
    @patch("accounting.services.student_billing.AccountingStudentBill.objects.filter")
    def test_sync_distributes_concessions_and_updates_outstanding(
        self,
        mock_bill_filter,
        mock_concession_filter,
    ):
        bill1 = MagicMock()
        bill1.gross_amount = Decimal("200.00")
        bill1.paid_amount = Decimal("50.00")

        bill2 = MagicMock()
        bill2.gross_amount = Decimal("100.00")
        bill2.paid_amount = Decimal("0.00")

        mock_bill_qs = MagicMock()
        mock_bill_qs.order_by.return_value = [bill1, bill2]
        mock_bill_filter.return_value = mock_bill_qs

        mock_concession_qs = MagicMock()
        mock_concession_qs.aggregate.return_value = {"total": Decimal("30.00")}
        mock_concession_filter.return_value = mock_concession_qs

        updated_count = sync_accounting_bill_concession_totals(
            student=MagicMock(),
            academic_year=MagicMock(),
        )

        self.assertEqual(updated_count, 2)
        self.assertEqual(bill1.concession_amount, Decimal("20.00"))
        self.assertEqual(bill1.net_amount, Decimal("180.00"))
        self.assertEqual(bill1.outstanding_amount, Decimal("130.00"))

        self.assertEqual(bill2.concession_amount, Decimal("10.00"))
        self.assertEqual(bill2.net_amount, Decimal("90.00"))
        self.assertEqual(bill2.outstanding_amount, Decimal("90.00"))

        bill1.save.assert_called_once()
        bill2.save.assert_called_once()

    @patch("accounting.services.student_billing.AccountingConcession.objects.filter")
    @patch("accounting.services.student_billing.AccountingStudentBill.objects.filter")
    def test_sync_returns_zero_when_no_bills(self, mock_bill_filter, mock_concession_filter):
        mock_bill_qs = MagicMock()
        mock_bill_qs.order_by.return_value = []
        mock_bill_filter.return_value = mock_bill_qs

        updated_count = sync_accounting_bill_concession_totals(
            student=MagicMock(),
            academic_year=MagicMock(),
        )

        self.assertEqual(updated_count, 0)
        mock_concession_filter.assert_not_called()


class EnrollmentBillingArrearsTests(SimpleTestCase):
    @patch("accounting.services.student_billing.AccountingStudentBill.objects.filter")
    def test_get_enrollment_arrears_amount_sums_prior_outstanding_balances(
        self,
        mock_filter,
    ):
        enrollment = SimpleNamespace(
            student=MagicMock(),
            academic_year_id="ay-current",
        )

        mock_qs = MagicMock()
        mock_qs.exclude.return_value = mock_qs
        mock_qs.aggregate.return_value = {"total": Decimal("125.50")}
        mock_filter.return_value = mock_qs

        arrears = get_enrollment_arrears_amount(enrollment)

        self.assertEqual(arrears, Decimal("125.50"))
        mock_filter.assert_called_once_with(student=enrollment.student)
        self.assertEqual(mock_qs.exclude.call_count, 2)
        mock_qs.aggregate.assert_called_once()

    @patch("accounting.services.student_billing.get_enrollment_arrears_amount")
    def test_build_billing_lines_prepends_arrears_line(
        self,
        mock_get_arrears,
    ):
        mock_get_arrears.return_value = Decimal("75.00")

        section_fee = SimpleNamespace(
            amount=Decimal("25.00"),
            general_fee=SimpleNamespace(
                name="Registration",
                student_target="",
                description="Registration fee",
            ),
        )
        tuition_fee = SimpleNamespace(amount=Decimal("300.00"))
        enrollment = SimpleNamespace(
            enrolled_as="new",
            section=SimpleNamespace(
                section_fees=SimpleNamespace(
                    select_related=MagicMock(
                        return_value=SimpleNamespace(
                            filter=MagicMock(return_value=[section_fee])
                        )
                    )
                )
            ),
            grade_level=SimpleNamespace(
                tuition_fees=SimpleNamespace(
                    filter=MagicMock(
                        return_value=SimpleNamespace(first=MagicMock(return_value=tuition_fee))
                    )
                )
            ),
        )

        lines = build_billing_lines_for_enrollment(enrollment)

        self.assertEqual(lines[0].name, "Arrears")
        self.assertEqual(lines[0].amount, Decimal("75.00"))
        self.assertEqual(lines[1].name, "Registration")
        self.assertEqual(lines[2].name, "Tuition")


class AccountingCashTransactionStatusFlowTests(SimpleTestCase):
    def test_validate_editable_unlinks_reversed_journal_instead_of_blocking(self):
        request_user = MagicMock()
        viewset = AccountingCashTransactionViewSet()
        viewset.request = SimpleNamespace(user=request_user)

        reversed_journal = SimpleNamespace(status=AccountingJournalEntry.EntryStatus.REVERSED)
        cash_tx = MagicMock()
        cash_tx.source_reference = None
        cash_tx.journal_entry = reversed_journal

        response = viewset._validate_editable(cash_tx)

        self.assertIsNone(response)
        self.assertIsNone(cash_tx.journal_entry)
        self.assertEqual(cash_tx.updated_by, request_user)
        cash_tx.save.assert_called_once_with(update_fields=["journal_entry", "updated_by", "updated_at"])

    @patch("accounting.views.cash_transaction.transaction.atomic", return_value=nullcontext())
    def test_update_status_maps_canceled_alias_to_rejected(self, _mock_atomic):
        viewset = AccountingCashTransactionViewSet()
        viewset.request = SimpleNamespace(user=SimpleNamespace(username="auditor", email="auditor@example.com"))
        viewset.format_kwarg = None

        cash_tx = MagicMock()
        cash_tx.status = AccountingCashTransaction.TransactionStatus.PENDING
        cash_tx.bank_account = MagicMock()
        cash_tx.journal_entry_id = None

        with patch.object(viewset, "get_serializer", return_value=SimpleNamespace(data={})):
            response = viewset._update_status(
                cash_tx,
                "canceled",
                rejection_reason="Canceled by user",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(cash_tx.status, AccountingCashTransaction.TransactionStatus.REJECTED)
        self.assertEqual(cash_tx.rejected_by, "auditor")
        self.assertIsNotNone(cash_tx.rejected_at)

    @patch("accounting.views.cash_transaction.transaction.atomic", return_value=nullcontext())
    @patch("accounting.views.cash_transaction.evaluate_transaction_limits", return_value=SimpleNamespace(should_block=False, blocking_messages=[]))
    @patch("accounting.views.cash_transaction.recalculate_bank_account_current_balance")
    @patch("accounting.views.cash_transaction.post_cash_transaction_to_ledger")
    def test_update_status_does_not_post_when_approved(
        self,
        mock_post,
        mock_recalc,
        _mock_evaluate,
        _mock_atomic,
    ):
        viewset = AccountingCashTransactionViewSet()
        viewset.request = SimpleNamespace(user=MagicMock(), data={})
        viewset.format_kwarg = None

        cash_tx = MagicMock()
        cash_tx.status = AccountingCashTransaction.TransactionStatus.APPROVED
        cash_tx.bank_account = MagicMock()
        cash_tx.journal_entry_id = None

        with patch.object(viewset, "get_serializer", return_value=SimpleNamespace(data={})):
            response = viewset._update_status(
                cash_tx,
                AccountingCashTransaction.TransactionStatus.APPROVED,
            )

        self.assertEqual(response.status_code, 200)
        mock_post.assert_not_called()
        mock_recalc.assert_not_called()

    @patch("accounting.views.cash_transaction.transaction.atomic", return_value=nullcontext())
    @patch("accounting.views.cash_transaction.evaluate_transaction_limits", return_value=SimpleNamespace(should_block=False, blocking_messages=[]))
    @patch("accounting.views.cash_transaction.recalculate_bank_account_current_balance")
    @patch("accounting.views.cash_transaction.post_cash_transaction_to_ledger")
    def test_update_status_approve_ignores_prevent_journal_posting_flag(
        self,
        mock_post,
        mock_recalc,
        _mock_evaluate,
        _mock_atomic,
    ):
        viewset = AccountingCashTransactionViewSet()
        viewset.request = SimpleNamespace(user=MagicMock(), data={})
        viewset.format_kwarg = None

        cash_tx = MagicMock()
        cash_tx.status = AccountingCashTransaction.TransactionStatus.APPROVED
        cash_tx.bank_account = MagicMock()
        cash_tx.journal_entry_id = None

        with patch.object(viewset, "get_serializer", return_value=SimpleNamespace(data={})):
            response = viewset._update_status(
                cash_tx,
                AccountingCashTransaction.TransactionStatus.APPROVED,
                prevent_journal_posting=True,
            )

        self.assertEqual(response.status_code, 200)
        mock_post.assert_not_called()
        mock_recalc.assert_not_called()

    @patch("accounting.views.cash_transaction.transaction.atomic", return_value=nullcontext())
    @patch("accounting.views.cash_transaction.recalculate_bank_account_current_balance")
    @patch("accounting.views.cash_transaction.reverse_cash_transaction_journal_entry")
    def test_update_status_reverses_when_moving_from_approved_to_rejected_if_posted(
        self,
        mock_reverse,
        mock_recalc,
        _mock_atomic,
    ):
        viewset = AccountingCashTransactionViewSet()
        viewset.request = SimpleNamespace(user=MagicMock(), data={})
        viewset.format_kwarg = None

        cash_tx = MagicMock()
        cash_tx.status = AccountingCashTransaction.TransactionStatus.APPROVED
        cash_tx.bank_account = MagicMock()
        cash_tx.journal_entry_id = "je-1"

        with patch.object(viewset, "get_serializer", return_value=SimpleNamespace(data={})):
            response = viewset._update_status(
                cash_tx,
                AccountingCashTransaction.TransactionStatus.REJECTED,
                rejection_reason="Invalid payment",
            )

        self.assertEqual(response.status_code, 200)
        mock_reverse.assert_called_once_with(cash_tx, actor=viewset.request.user)
        mock_recalc.assert_called_once_with(cash_tx.bank_account)

    @patch("accounting.views.cash_transaction.transaction.atomic", return_value=nullcontext())
    @patch("accounting.views.cash_transaction.transaction.on_commit")
    @patch("accounting.views.cash_transaction.evaluate_transaction_limits", return_value=SimpleNamespace(should_block=False, blocking_messages=[]))
    @patch("accounting.views.cash_transaction.recalculate_bank_account_current_balance")
    @patch("accounting.views.cash_transaction.post_cash_transaction_to_ledger")
    def test_update_status_completes_approved_transaction_and_recalculates_balance(
        self,
        mock_post,
        mock_recalc,
        _mock_evaluate,
        _mock_on_commit,
        _mock_atomic,
    ):
        viewset = AccountingCashTransactionViewSet()
        viewset.request = SimpleNamespace(user=MagicMock(), data={})
        viewset.format_kwarg = None

        cash_tx = MagicMock()
        cash_tx.status = AccountingCashTransaction.TransactionStatus.APPROVED
        cash_tx.bank_account = MagicMock()
        cash_tx.journal_entry_id = None
        cash_tx.journal_entry = None

        with patch.object(viewset, "get_serializer", return_value=SimpleNamespace(data={})):
            response = viewset._update_status(
                cash_tx,
                AccountingCashTransaction.TransactionStatus.COMPLETED,
                via_complete_action=True,
            )

        self.assertEqual(response.status_code, 200)
        mock_post.assert_called_once_with(cash_tx, actor=viewset.request.user)
        mock_recalc.assert_called_once_with(cash_tx.bank_account)

    @patch("accounting.views.cash_transaction.transaction.atomic", return_value=nullcontext())
    @patch("accounting.views.cash_transaction.transaction.on_commit")
    @patch("accounting.views.cash_transaction.evaluate_transaction_limits", return_value=SimpleNamespace(should_block=False, blocking_messages=[]))
    @patch("accounting.views.cash_transaction.recalculate_bank_account_current_balance")
    @patch("accounting.views.cash_transaction.sync_cash_transaction_journal_entry")
    @patch("accounting.views.cash_transaction.post_cash_transaction_to_ledger")
    def test_update_status_complete_unlinks_stale_reversed_journal_then_posts(
        self,
        mock_post,
        mock_sync,
        mock_recalc,
        _mock_evaluate,
        _mock_on_commit,
        _mock_atomic,
    ):
        viewset = AccountingCashTransactionViewSet()
        viewset.request = SimpleNamespace(user=MagicMock(), data={})
        viewset.format_kwarg = None

        reversed_journal = SimpleNamespace(status=AccountingJournalEntry.EntryStatus.REVERSED)
        cash_tx = MagicMock()
        cash_tx.status = AccountingCashTransaction.TransactionStatus.APPROVED
        cash_tx.bank_account = MagicMock()
        cash_tx.journal_entry_id = "je-reversed"
        cash_tx.journal_entry = reversed_journal

        with patch.object(viewset, "get_serializer", return_value=SimpleNamespace(data={})):
            response = viewset._update_status(
                cash_tx,
                AccountingCashTransaction.TransactionStatus.COMPLETED,
                via_complete_action=True,
            )

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(cash_tx.journal_entry)
        mock_post.assert_called_once_with(cash_tx, actor=viewset.request.user)
        mock_sync.assert_not_called()
        mock_recalc.assert_called_once_with(cash_tx.bank_account)

    @patch("accounting.views.cash_transaction.transaction.atomic", return_value=nullcontext())
    @patch("accounting.views.cash_transaction.recalculate_bank_account_current_balance")
    @patch("accounting.views.cash_transaction.post_cash_transaction_to_ledger")
    def test_update_status_rejects_completed_via_generic_status_endpoint(
        self,
        mock_post,
        mock_recalc,
        _mock_atomic,
    ):
        viewset = AccountingCashTransactionViewSet()
        viewset.request = SimpleNamespace(user=MagicMock(), data={})
        viewset.format_kwarg = None

        cash_tx = MagicMock()
        cash_tx.status = AccountingCashTransaction.TransactionStatus.APPROVED
        cash_tx.bank_account = MagicMock()

        response = viewset._update_status(
            cash_tx,
            AccountingCashTransaction.TransactionStatus.COMPLETED,
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("dedicated complete endpoint", response.data["detail"])
        mock_post.assert_not_called()
        mock_recalc.assert_not_called()

    @patch("accounting.views.cash_transaction.transaction.atomic", return_value=nullcontext())
    @patch("accounting.views.cash_transaction.recalculate_bank_account_current_balance")
    @patch("accounting.views.cash_transaction.post_cash_transaction_to_ledger")
    def test_update_status_rejects_complete_from_non_approved_status(
        self,
        mock_post,
        mock_recalc,
        _mock_atomic,
    ):
        viewset = AccountingCashTransactionViewSet()
        viewset.request = SimpleNamespace(user=MagicMock(), data={})
        viewset.format_kwarg = None

        cash_tx = MagicMock()
        cash_tx.status = AccountingCashTransaction.TransactionStatus.PENDING
        cash_tx.bank_account = MagicMock()

        response = viewset._update_status(
            cash_tx,
            AccountingCashTransaction.TransactionStatus.COMPLETED,
            via_complete_action=True,
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid status transition", response.data["detail"])
        mock_post.assert_not_called()
        mock_recalc.assert_not_called()

    @patch("accounting.views.cash_transaction.transaction.atomic", return_value=nullcontext())
    @patch("accounting.views.cash_transaction.recalculate_bank_account_current_balance")
    @patch("accounting.views.cash_transaction.post_cash_transaction_to_ledger")
    def test_update_status_rejects_duplicate_completion(
        self,
        mock_post,
        mock_recalc,
        _mock_atomic,
    ):
        viewset = AccountingCashTransactionViewSet()
        viewset.request = SimpleNamespace(user=MagicMock(), data={})
        viewset.format_kwarg = None

        cash_tx = MagicMock()
        cash_tx.status = AccountingCashTransaction.TransactionStatus.COMPLETED
        cash_tx.bank_account = MagicMock()

        response = viewset._update_status(
            cash_tx,
            AccountingCashTransaction.TransactionStatus.COMPLETED,
            via_complete_action=True,
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data["detail"], "Transaction is already completed.")
        mock_post.assert_not_called()
        mock_recalc.assert_not_called()

    @patch("accounting.views.cash_transaction.transaction.atomic", return_value=nullcontext())
    @patch("accounting.views.cash_transaction.transaction.on_commit", side_effect=lambda fn: fn())
    @patch("accounting.views.cash_transaction.dispatch_bank_rule_alerts_for_status_event")
    @patch("accounting.views.cash_transaction.recalculate_bank_account_current_balance")
    @patch("accounting.views.cash_transaction.evaluate_transaction_limits")
    def test_update_status_dispatches_alert_on_approved_transition(
        self,
        mock_evaluate,
        mock_recalc,
        mock_dispatch,
        _mock_on_commit,
        _mock_atomic,
    ):
        viewset = AccountingCashTransactionViewSet()
        viewset.request = SimpleNamespace(user=MagicMock(), data={})
        viewset.format_kwarg = None
        cash_tx = MagicMock()
        cash_tx.status = AccountingCashTransaction.TransactionStatus.PENDING
        cash_tx.bank_account = MagicMock()
        cash_tx.journal_entry_id = None
        cash_tx.bank_account = MagicMock()
        cash_tx.bank_account_id = "bank-1"
        cash_tx.base_amount = Decimal("50.00")
        cash_tx.amount = Decimal("50.00")
        cash_tx.reference_number = "TXN-1"
        cash_tx.transaction_date = "2026-08-08"
        cash_tx.journal_entry_id = None

        mock_evaluate.return_value = SimpleNamespace(should_block=False, blocking_messages=[])

        with patch.object(viewset, "get_serializer", return_value=SimpleNamespace(data={})), patch(
            "accounting.views.cash_transaction.AccountingBankAccount.objects.get",
            return_value=cash_tx.bank_account,
        ):
            response = viewset._update_status(
                cash_tx,
                AccountingCashTransaction.TransactionStatus.APPROVED,
            )

        self.assertEqual(response.status_code, 200)
        mock_recalc.assert_not_called()
        mock_dispatch.assert_called_once()

    @patch("accounting.views.cash_transaction.transaction.atomic", return_value=nullcontext())
    @patch("accounting.views.cash_transaction.transaction.on_commit", side_effect=lambda fn: fn())
    @patch("accounting.views.cash_transaction.dispatch_bank_rule_alerts_for_status_event")
    @patch("accounting.views.cash_transaction.recalculate_bank_account_current_balance")
    @patch("accounting.views.cash_transaction.post_cash_transaction_to_ledger")
    def test_perform_create_posts_if_created_as_approved(
        self,
        mock_post,
        mock_recalc,
        mock_dispatch,
        _mock_on_commit,
        _mock_atomic,
    ):
        viewset = AccountingCashTransactionViewSet()
        request_user = MagicMock()
        viewset.request = SimpleNamespace(user=request_user, data={})

        serializer = MagicMock()
        serializer.validated_data = {
            "transaction_type": MagicMock(transaction_category="income"),
            "source_reference": "",
            "amount": None,
        }

        cash_tx = MagicMock()
        cash_tx.status = AccountingCashTransaction.TransactionStatus.COMPLETED
        cash_tx.bank_account = MagicMock()
        cash_tx.bank_account_id = "bank-1"
        cash_tx.base_amount = Decimal("100.00")
        cash_tx.reference_number = "TXN-1"
        cash_tx.transaction_date = "2026-08-08"
        serializer.save.return_value = cash_tx

        with patch.object(viewset, "_validate_student_income_payment"), patch.object(
            viewset, "_validate_student_refund"
        ), patch.object(viewset, "_refund_ledger_account_override", return_value=None), patch(
            "accounting.views.cash_transaction.AccountingBankAccount.objects.get",
            return_value=cash_tx.bank_account,
        ):
            viewset.perform_create(serializer)

        serializer.save.assert_called_once_with(created_by=request_user, updated_by=request_user)
        mock_post.assert_called_once_with(cash_tx, actor=viewset.request.user)
        mock_recalc.assert_called_once_with(cash_tx.bank_account)
        mock_dispatch.assert_called_once()

    @patch("accounting.views.cash_transaction.transaction.atomic", return_value=nullcontext())
    @patch("accounting.views.cash_transaction.recalculate_bank_account_current_balance")
    @patch("accounting.views.cash_transaction.reverse_cash_transaction_journal_entry")
    @patch("accounting.views.cash_transaction.sync_cash_transaction_journal_entry")
    def test_perform_update_resets_completed_transaction_to_pending(
        self,
        mock_sync,
        mock_reverse,
        mock_recalc,
        _mock_atomic,
    ):
        viewset = AccountingCashTransactionViewSet()
        viewset.request = SimpleNamespace(user=MagicMock(), data={})

        bank_account = MagicMock()
        cash_tx = MagicMock()
        cash_tx.status = AccountingCashTransaction.TransactionStatus.COMPLETED
        cash_tx.bank_account_id = "bank-1"
        cash_tx.bank_account = bank_account
        cash_tx.journal_entry_id = "je-1"

        serializer = MagicMock()
        serializer.validated_data = {}
        serializer.save.return_value = cash_tx

        with patch.object(viewset, "get_object", return_value=cash_tx), patch.object(
            viewset, "_validate_student_income_payment"
        ), patch.object(viewset, "_validate_student_refund"), patch.object(
            viewset, "_refund_ledger_account_override", return_value=None
        ), patch.object(
            viewset, "_enforce_transaction_limits"
        ), patch(
            "accounting.views.cash_transaction.AccountingBankAccount.objects.select_for_update",
            return_value=SimpleNamespace(filter=lambda **kwargs: [bank_account]),
        ), patch(
            "accounting.views.cash_transaction.AccountingBankAccount.objects.filter",
            return_value=[bank_account],
        ):
            viewset.perform_update(serializer)

        self.assertEqual(
            cash_tx.status,
            AccountingCashTransaction.TransactionStatus.PENDING,
        )
        self.assertIsNone(cash_tx.journal_entry)
        self.assertIsNone(cash_tx.completed_by)
        self.assertIsNone(cash_tx.completed_at)
        self.assertIsNone(cash_tx.approved_by)
        self.assertIsNone(cash_tx.approved_at)
        self.assertIsNone(cash_tx.rejection_reason)
        mock_reverse.assert_called_once_with(cash_tx, actor=viewset.request.user)
        mock_sync.assert_not_called()
        mock_recalc.assert_called_once_with(bank_account)

    @patch("accounting.views.cash_transaction.transaction.atomic", return_value=nullcontext())
    @patch("accounting.views.cash_transaction.transaction.on_commit")
    @patch("accounting.views.cash_transaction.dispatch_bank_rule_alerts_for_status_event")
    @patch("accounting.views.cash_transaction.sync_cash_transaction_journal_entry")
    def test_perform_update_resets_rejected_transaction_to_pending(
        self,
        mock_sync,
        mock_dispatch,
        mock_on_commit,
        _mock_atomic,
    ):
        viewset = AccountingCashTransactionViewSet()
        viewset.request = SimpleNamespace(user=MagicMock(), data={})

        cash_tx = MagicMock()
        cash_tx.status = AccountingCashTransaction.TransactionStatus.REJECTED
        cash_tx.bank_account_id = "bank-1"
        cash_tx.bank_account = MagicMock()
        cash_tx.journal_entry_id = None

        serializer = MagicMock()
        serializer.validated_data = {}
        serializer.save.return_value = cash_tx

        with patch.object(viewset, "get_object", return_value=cash_tx), patch.object(
            viewset, "_validate_student_income_payment"
        ), patch.object(viewset, "_validate_student_refund"), patch.object(
            viewset, "_refund_ledger_account_override", return_value=None
        ), patch.object(
            viewset, "_enforce_transaction_limits"
        ), patch(
            "accounting.views.cash_transaction.AccountingBankAccount.objects.select_for_update",
            return_value=SimpleNamespace(filter=lambda **kwargs: []),
        ):
            viewset.perform_update(serializer)

        self.assertEqual(
            cash_tx.status,
            AccountingCashTransaction.TransactionStatus.PENDING,
        )
        mock_sync.assert_not_called()
        mock_on_commit.assert_not_called()
        mock_dispatch.assert_not_called()

    @patch("accounting.views.cash_transaction.transaction.atomic", return_value=nullcontext())
    @patch("accounting.views.cash_transaction.sync_cash_transaction_journal_entry")
    def test_perform_update_resets_approved_transaction_to_pending(
        self,
        mock_sync,
        _mock_atomic,
    ):
        viewset = AccountingCashTransactionViewSet()
        viewset.request = SimpleNamespace(user=MagicMock(), data={})

        cash_tx = MagicMock()
        cash_tx.status = AccountingCashTransaction.TransactionStatus.APPROVED
        cash_tx.bank_account_id = "bank-1"
        cash_tx.bank_account = MagicMock()
        cash_tx.journal_entry_id = None

        serializer = MagicMock()
        serializer.validated_data = {}
        serializer.save.return_value = cash_tx

        with patch.object(viewset, "get_object", return_value=cash_tx), patch.object(
            viewset, "_validate_student_income_payment"
        ), patch.object(viewset, "_validate_student_refund"), patch.object(
            viewset, "_refund_ledger_account_override", return_value=None
        ), patch.object(
            viewset, "_enforce_transaction_limits"
        ), patch(
            "accounting.views.cash_transaction.AccountingBankAccount.objects.select_for_update",
            return_value=SimpleNamespace(filter=lambda **kwargs: []),
        ):
            viewset.perform_update(serializer)

        self.assertEqual(
            cash_tx.status,
            AccountingCashTransaction.TransactionStatus.PENDING,
        )
        mock_sync.assert_not_called()

    @patch("accounting.views.cash_transaction.transaction.atomic", return_value=nullcontext())
    @patch("accounting.views.cash_transaction.recalculate_bank_account_current_balance")
    @patch("accounting.views.cash_transaction.reverse_cash_transaction_journal_entry")
    @patch("accounting.views.cash_transaction.sync_cash_transaction_journal_entry")
    def test_perform_update_reverses_any_posted_transaction_on_edit(
        self,
        mock_sync,
        mock_reverse,
        mock_recalc,
        _mock_atomic,
    ):
        viewset = AccountingCashTransactionViewSet()
        viewset.request = SimpleNamespace(user=MagicMock(), data={})

        bank_account = MagicMock()
        cash_tx = MagicMock()
        cash_tx.status = AccountingCashTransaction.TransactionStatus.APPROVED
        cash_tx.bank_account_id = "bank-1"
        cash_tx.bank_account = bank_account
        cash_tx.journal_entry_id = "je-1"

        serializer = MagicMock()
        serializer.validated_data = {}
        serializer.save.return_value = cash_tx

        with patch.object(viewset, "get_object", return_value=cash_tx), patch.object(
            viewset, "_validate_student_income_payment"
        ), patch.object(viewset, "_validate_student_refund"), patch.object(
            viewset, "_refund_ledger_account_override", return_value=None
        ), patch.object(
            viewset, "_enforce_transaction_limits"
        ), patch(
            "accounting.views.cash_transaction.AccountingBankAccount.objects.select_for_update",
            return_value=SimpleNamespace(filter=lambda **kwargs: [bank_account]),
        ), patch(
            "accounting.views.cash_transaction.AccountingBankAccount.objects.filter",
            return_value=[bank_account],
        ):
            viewset.perform_update(serializer)

        self.assertEqual(
            cash_tx.status,
            AccountingCashTransaction.TransactionStatus.PENDING,
        )
        mock_reverse.assert_called_once_with(cash_tx, actor=viewset.request.user)
        mock_sync.assert_not_called()
        mock_recalc.assert_called_once_with(bank_account)

    @patch("accounting.views.cash_transaction.transaction.atomic", return_value=nullcontext())
    @patch("accounting.views.cash_transaction.recalculate_bank_account_current_balance")
    @patch("accounting.views.cash_transaction.reverse_cash_transaction_journal_entry")
    @patch("accounting.views.cash_transaction.sync_cash_transaction_journal_entry")
    def test_perform_update_forces_pending_and_reverses_when_previously_pending_but_posted(
        self,
        mock_sync,
        mock_reverse,
        mock_recalc,
        _mock_atomic,
    ):
        viewset = AccountingCashTransactionViewSet()
        viewset.request = SimpleNamespace(user=MagicMock(), data={})

        bank_account = MagicMock()
        cash_tx = MagicMock()
        cash_tx.status = AccountingCashTransaction.TransactionStatus.PENDING
        cash_tx.bank_account_id = "bank-1"
        cash_tx.bank_account = bank_account
        cash_tx.journal_entry_id = "je-1"

        serializer = MagicMock()
        serializer.validated_data = {}
        serializer.save.return_value = cash_tx

        with patch.object(viewset, "get_object", return_value=cash_tx), patch.object(
            viewset, "_validate_student_income_payment"
        ), patch.object(viewset, "_validate_student_refund"), patch.object(
            viewset, "_refund_ledger_account_override", return_value=None
        ), patch.object(
            viewset, "_enforce_transaction_limits"
        ), patch(
            "accounting.views.cash_transaction.AccountingBankAccount.objects.select_for_update",
            return_value=SimpleNamespace(filter=lambda **kwargs: [bank_account]),
        ), patch(
            "accounting.views.cash_transaction.AccountingBankAccount.objects.filter",
            return_value=[bank_account],
        ):
            viewset.perform_update(serializer)

        self.assertEqual(
            cash_tx.status,
            AccountingCashTransaction.TransactionStatus.PENDING,
        )
        mock_reverse.assert_called_once_with(cash_tx, actor=viewset.request.user)
        mock_sync.assert_not_called()
        mock_recalc.assert_called_once_with(bank_account)


class AccountingBankAccountListOptimizationTests(SimpleTestCase):
    @patch("accounting.views.cash_transaction.recalculate_bank_account_current_balance")
    @patch("accounting.views.cash_transaction.aggregate_bank_account_balances")
    @patch("accounting.views.cash_transaction.recalculate_bank_accounts_current_balances")
    def test_list_uses_batched_balance_recalculation(
        self,
        mock_recalculate_batch,
        mock_aggregate_balances,
        mock_recalculate_single,
    ):
        viewset = AccountingBankAccountViewSet()
        viewset.request = SimpleNamespace(query_params={})
        viewset.format_kwarg = None

        currency = SimpleNamespace(id=1, code="USD", symbol="$")
        account_one = SimpleNamespace(
            id=1,
            currency=currency,
            opening_balance=Decimal("10.00"),
            status="active",
            account_type="cash",
        )
        account_two = SimpleNamespace(
            id=2,
            currency=currency,
            opening_balance=Decimal("5.00"),
            status="inactive",
            account_type="checking",
        )
        accounts = [account_one, account_two]

        mock_aggregate_balances.return_value = {
            1: {"base": Decimal("100.00"), "native": Decimal("40.00")},
            2: {"base": Decimal("90.00"), "native": Decimal("-2.00")},
        }

        serializer = SimpleNamespace(data=[{"id": 1}, {"id": 2}])
        with patch.object(viewset, "get_queryset", return_value=MagicMock()), patch.object(
            viewset, "filter_queryset", return_value=accounts
        ), patch.object(viewset, "get_serializer", return_value=serializer):
            response = viewset.list(SimpleNamespace())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["summary"]["total_accounts"], 2)
        self.assertEqual(response.data["summary"]["active_accounts"], 1)
        self.assertEqual(response.data["summary"]["cash_accounts"], 1)
        self.assertEqual(
            response.data["summary"]["balances_by_currency"][0]["total_balance"],
            "53.00",
        )

        mock_recalculate_batch.assert_called_once_with(accounts)
        mock_aggregate_balances.assert_called_once_with(accounts)
        mock_recalculate_single.assert_not_called()


class AccountingCashTransactionExportTests(SimpleTestCase):
    @patch("common.file_generators.FileGenerator.generate_file")
    def test_export_uses_chunked_iterator_for_prefetched_queryset(self, mock_generate):
        mock_generate.return_value = HttpResponse(b"csv")

        viewset = AccountingCashTransactionViewSet()
        request = SimpleNamespace(
            query_params={"file_format": "csv"},
        )
        viewset.request = request
        viewset.format_kwarg = None

        mock_queryset = MagicMock()
        mock_queryset._prefetch_related_lookups = ["bill_allocations__student_bill"]
        mock_queryset.iterator.return_value = iter([])

        with patch.object(viewset, "get_queryset", return_value=mock_queryset):
            response = viewset.export_transactions(request)

        mock_queryset.iterator.assert_called_once_with(chunk_size=2000)
        self.assertIsInstance(response, HttpResponse)
        mock_generate.assert_called_once()


class AccountingJournalEntryExportTests(SimpleTestCase):
    @patch("accounting.views.ledger._build_bank_by_ledger_map", return_value={})
    @patch("common.file_generators.FileGenerator.generate_file")
    def test_export_uses_chunked_iterator_for_prefetched_queryset(
        self,
        mock_generate,
        _mock_bank_map,
    ):
        from accounting.views.ledger import AccountingJournalEntryViewSet

        mock_generate.return_value = HttpResponse(b"csv")

        viewset = AccountingJournalEntryViewSet()
        request = SimpleNamespace(
            query_params={"file_format": "csv"},
        )
        viewset.request = request
        viewset.format_kwarg = None

        mock_queryset = MagicMock()
        mock_queryset._prefetch_related_lookups = ["lines__ledger_account"]
        mock_queryset.iterator.return_value = iter([])

        with patch.object(viewset, "get_queryset", return_value=mock_queryset):
            response = viewset.export_entries(request)

        mock_queryset.iterator.assert_called_once_with(chunk_size=2000)
        self.assertIsInstance(response, HttpResponse)
        mock_generate.assert_called_once()


class AccountingTransactionAccessPolicyTests(SimpleTestCase):
    def test_complete_action_requires_admin_or_superadmin_role(self):
        from accounting.access_policies import AccountingTransactionAccessPolicy

        matching_rules = [
            statement
            for statement in AccountingTransactionAccessPolicy.statements
            if "complete" in statement.get("action", [])
        ]

        self.assertTrue(matching_rules)
        self.assertTrue(
            any(
                rule.get("condition") == "is_role_in:superadmin,admin"
                for rule in matching_rules
            )
        )


class AccountingStudentPaymentValidationTests(SimpleTestCase):
    @patch("accounting.services.currency_totals.effective_payment_base_amount", return_value=Decimal("10000.00"))
    @patch("finance.validators.get_student_net_remaining_balance", return_value=Decimal("16300.00"))
    def test_income_payment_uses_explicit_academic_year_when_provided(
        self,
        _mock_remaining,
        _mock_effective,
    ):
        viewset = AccountingCashTransactionViewSet()

        student = MagicMock()
        explicit_year = MagicMock()
        data = {
            "transaction_type": SimpleNamespace(transaction_category="income"),
            "amount": Decimal("10000.00"),
            "exchange_rate": Decimal("1.0"),
            "student": student,
            "academic_year_id": explicit_year,
        }

        with patch.object(
            viewset,
            "_resolve_transaction_academic_year",
            return_value=explicit_year,
        ) as mock_resolve_year:
            viewset._validate_student_income_payment(data)

        mock_resolve_year.assert_called_once_with(
            student=student,
            tx_date=None,
            academic_year=explicit_year,
        )

    @patch("accounting.services.currency_totals.effective_payment_base_amount", return_value=Decimal("10000.00"))
    @patch("finance.validators.get_student_net_remaining_balance", return_value=Decimal("6300.00"))
    def test_income_payment_rejects_when_effective_exceeds_remaining(
        self,
        _mock_remaining,
        _mock_effective,
    ):
        viewset = AccountingCashTransactionViewSet()

        data = {
            "transaction_type": SimpleNamespace(transaction_category="income"),
            "amount": Decimal("10000.00"),
            "exchange_rate": Decimal("1.0"),
            "student": MagicMock(),
        }

        with patch.object(
            viewset,
            "_resolve_transaction_academic_year",
            return_value=MagicMock(),
        ):
            with self.assertRaisesMessage(
                Exception,
                "exceeds student balance due of 6,300.00",
            ):
                viewset._validate_student_income_payment(data)


class CashStandingBalanceTests(SimpleTestCase):
    def _bank_account(
        self,
        *,
        opening_balance=Decimal("0"),
        opening_balance_date=None,
        ledger_account_id="ledger-1",
        account_id="bank-1",
    ):
        currency = SimpleNamespace(id="cur-1", code="LRD", symbol="L$")
        return SimpleNamespace(
            id=account_id,
            currency=currency,
            opening_balance=opening_balance,
            opening_balance_date=opening_balance_date,
            ledger_account_id=ledger_account_id,
            transactions=MagicMock(),
        )

    @patch("accounting.services.journal_summary._ledger_gl_balance_base")
    def test_linked_ledger_uses_gl_net_only_not_opening_field(self, mock_gl_balance):
        from accounting.services.journal_summary import _account_cash_standing_base

        account = self._bank_account(
            opening_balance=Decimal("30000000"),
            opening_balance_date=SimpleNamespace(year=2026, month=1, day=1),
        )
        mock_gl_balance.return_value = Decimal("4700000")

        balance = _account_cash_standing_base(account)

        self.assertEqual(balance, Decimal("4700000"))

    @patch("accounting.services.journal_summary._bank_accounts_queryset")
    @patch("accounting.services.journal_summary._ledger_gl_balance_base")
    def test_shared_ledger_is_counted_once_across_bank_accounts(self, mock_gl_balance, mock_queryset):
        from accounting.services.journal_summary import compute_cash_standing_balance

        shared_ledger = "ledger-shared"
        accounts = [
            self._bank_account(ledger_account_id=shared_ledger, account_id="bank-a"),
            self._bank_account(ledger_account_id=shared_ledger, account_id="bank-b"),
        ]
        mock_queryset.return_value.select_related.return_value = accounts
        mock_gl_balance.return_value = Decimal("4700000")

        balance = compute_cash_standing_balance()

        self.assertEqual(balance, Decimal("4700000"))
        mock_gl_balance.assert_called_once()

    @patch("accounting.services.journal_summary._ledger_gl_balance_base")
    def test_expense_credits_reduce_standing_balance(self, mock_gl_balance):
        from accounting.services.journal_summary import _account_cash_standing_base

        account = self._bank_account(opening_balance=Decimal("0"))
        mock_gl_balance.return_value = Decimal("-250000")

        balance = _account_cash_standing_base(account)

        self.assertEqual(balance, Decimal("-250000"))
