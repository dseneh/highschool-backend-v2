from decimal import Decimal
from contextlib import nullcontext
from unittest.mock import MagicMock, patch

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase
from rest_framework.response import Response
from types import SimpleNamespace

from accounting.services.posting import post_cash_transaction_to_ledger
from accounting.services.student_billing import sync_accounting_bill_concession_totals
from accounting.views.base import AccountingErrorFormattingMixin
from accounting.views.cash_transaction import AccountingCashTransactionViewSet
from accounting.models import AccountingCashTransaction


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


class AccountingCashTransactionStatusFlowTests(SimpleTestCase):
    @patch("accounting.views.cash_transaction.transaction.atomic", return_value=nullcontext())
    @patch("accounting.views.cash_transaction.recalculate_bank_account_current_balance")
    @patch("accounting.views.cash_transaction.post_cash_transaction_to_ledger")
    def test_update_status_auto_posts_when_approved(
        self,
        mock_post,
        mock_recalc,
        _mock_atomic,
    ):
        viewset = AccountingCashTransactionViewSet()
        viewset.request = SimpleNamespace(user=MagicMock())
        viewset.format_kwarg = None

        cash_tx = MagicMock()
        cash_tx.status = AccountingCashTransaction.TransactionStatus.PENDING
        cash_tx.bank_account = MagicMock()

        with patch.object(viewset, "get_serializer", return_value=SimpleNamespace(data={})):
            response = viewset._update_status(
                cash_tx,
                AccountingCashTransaction.TransactionStatus.APPROVED,
            )

        self.assertEqual(response.status_code, 200)
        mock_post.assert_called_once_with(cash_tx, actor=viewset.request.user)
        mock_recalc.assert_called_once_with(cash_tx.bank_account)

    @patch("accounting.views.cash_transaction.transaction.atomic", return_value=nullcontext())
    @patch("accounting.views.cash_transaction.recalculate_bank_account_current_balance")
    @patch("accounting.views.cash_transaction.post_cash_transaction_to_ledger")
    def test_update_status_can_skip_auto_post_on_approve(
        self,
        mock_post,
        mock_recalc,
        _mock_atomic,
    ):
        viewset = AccountingCashTransactionViewSet()
        viewset.request = SimpleNamespace(user=MagicMock())
        viewset.format_kwarg = None

        cash_tx = MagicMock()
        cash_tx.status = AccountingCashTransaction.TransactionStatus.PENDING
        cash_tx.bank_account = MagicMock()

        with patch.object(viewset, "get_serializer", return_value=SimpleNamespace(data={})):
            response = viewset._update_status(
                cash_tx,
                AccountingCashTransaction.TransactionStatus.APPROVED,
                prevent_journal_posting=True,
            )

        self.assertEqual(response.status_code, 200)
        mock_post.assert_not_called()
        mock_recalc.assert_called_once_with(cash_tx.bank_account)

    @patch("accounting.views.cash_transaction.transaction.atomic", return_value=nullcontext())
    @patch("accounting.views.cash_transaction.recalculate_bank_account_current_balance")
    @patch("accounting.views.cash_transaction.reverse_cash_transaction_journal_entry")
    def test_update_status_reverses_journal_when_leaving_approved(
        self,
        mock_reverse,
        mock_recalc,
        _mock_atomic,
    ):
        viewset = AccountingCashTransactionViewSet()
        viewset.request = SimpleNamespace(user=MagicMock())
        viewset.format_kwarg = None

        cash_tx = MagicMock()
        cash_tx.status = AccountingCashTransaction.TransactionStatus.APPROVED
        cash_tx.bank_account = MagicMock()

        with patch.object(viewset, "get_serializer", return_value=SimpleNamespace(data={})):
            response = viewset._update_status(
                cash_tx,
                AccountingCashTransaction.TransactionStatus.REJECTED,
                rejection_reason="Invalid payment",
            )

        self.assertEqual(response.status_code, 200)
        mock_reverse.assert_called_once_with(cash_tx, actor=viewset.request.user)
        mock_recalc.assert_called_once_with(cash_tx.bank_account)

    @patch("accounting.views.cash_transaction.recalculate_bank_account_current_balance")
    @patch("accounting.views.cash_transaction.post_cash_transaction_to_ledger")
    def test_perform_create_posts_if_created_as_approved(
        self,
        mock_post,
        mock_recalc,
    ):
        viewset = AccountingCashTransactionViewSet()
        viewset.request = SimpleNamespace(user=MagicMock())

        serializer = MagicMock()
        serializer.validated_data = {
            "transaction_type": MagicMock(transaction_category="income"),
            "source_reference": "",
            "amount": None,
        }

        cash_tx = MagicMock()
        cash_tx.status = AccountingCashTransaction.TransactionStatus.APPROVED
        cash_tx.bank_account = MagicMock()
        serializer.save.return_value = cash_tx

        viewset.perform_create(serializer)

        mock_post.assert_called_once_with(cash_tx, actor=viewset.request.user)
        mock_recalc.assert_called_once_with(cash_tx.bank_account)
