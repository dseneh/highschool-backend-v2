from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIRequestFactory

from finance.signals import _refresh_payment_summary_for_enrollment
from finance.views.transaction import TransactionViewSet
from finance.utils import (
    _calculate_payment_plan_direct,
    calculate_student_payment_summary,
    disable_payment_summary_refresh,
)


class PaymentPlanAccountingSourceTests(SimpleTestCase):
    @patch("finance.models._get_effective_paid_for_enrollment", return_value=Decimal("100.00"))
    @patch("finance.models._get_net_total_bills_for_enrollment", return_value=Decimal("300.00"))
    @patch("finance.models.PaymentInstallment.objects.filter")
    def test_direct_payment_plan_uses_accounting_bill_totals(
        self,
        mock_installment_filter,
        mock_net_total,
        mock_effective_paid,
    ):
        installment_1 = MagicMock()
        installment_1.id = "inst-1"
        installment_1.value = Decimal("50.00")
        installment_1.due_date = date(2026, 1, 15)

        installment_2 = MagicMock()
        installment_2.id = "inst-2"
        installment_2.value = Decimal("50.00")
        installment_2.due_date = date(2026, 2, 15)

        ordered_installments = MagicMock()
        ordered_installments.exists.return_value = True
        ordered_installments.__iter__.return_value = iter([installment_1, installment_2])

        filtered_installments = MagicMock()
        filtered_installments.order_by.return_value = ordered_installments
        mock_installment_filter.return_value = filtered_installments

        enrollment = MagicMock()
        academic_year = MagicMock(id="ay-1")
        enrollment.academic_year = academic_year
        enrollment.student_bills.aggregate.return_value = {"total": Decimal("900.00")}
        enrollment.student.transactions.filter.return_value.aggregate.return_value = {
            "total": Decimal("10.00")
        }

        payment_plan = _calculate_payment_plan_direct(enrollment, academic_year)

        self.assertEqual(len(payment_plan), 2)
        self.assertEqual(payment_plan[0]["amount"], 150.0)
        self.assertEqual(payment_plan[0]["amount_paid"], 100.0)
        self.assertEqual(payment_plan[0]["balance"], 50.0)
        self.assertEqual(payment_plan[1]["cumulative_balance"], 200.0)
        mock_net_total.assert_called_once_with(enrollment)
        mock_effective_paid.assert_called_once_with(enrollment, academic_year)


class PaymentSummaryGuardTests(SimpleTestCase):
    def test_calculate_student_payment_summary_skips_when_refresh_disabled(self):
        class DummyEnrollment:
            pass

        academic_year = MagicMock()
        academic_year.id = "ay-1"

        enrollment = DummyEnrollment()
        enrollment.pk = "enr-1"
        enrollment.academic_year = academic_year

        with disable_payment_summary_refresh(), patch(
            "students.models.StudentPaymentSummary.objects.update_or_create"
        ) as mock_update_or_create, patch(
            "finance.utils._calculate_payment_plan_direct"
        ) as mock_plan:
            result = calculate_student_payment_summary(enrollment, academic_year)

        self.assertIsNone(result)
        mock_update_or_create.assert_not_called()
        mock_plan.assert_not_called()

    def test_calculate_student_payment_summary_skips_deleted_enrollment(self):
        class DummyEnrollment:
            pass

        academic_year = MagicMock()
        academic_year.id = "ay-1"

        enrollment = DummyEnrollment()
        enrollment.pk = "enr-deleted"
        enrollment.academic_year = academic_year
        enrollment.student = MagicMock()
        DummyEnrollment._default_manager = MagicMock()
        DummyEnrollment._default_manager.filter.return_value.exists.return_value = False

        with patch("students.models.StudentPaymentSummary.objects.filter") as mock_summary_filter, patch(
            "students.models.StudentPaymentSummary.objects.update_or_create"
        ) as mock_update_or_create, patch(
            "finance.utils._calculate_payment_plan_direct"
        ) as mock_plan, patch(
            "finance.utils._calculate_payment_status_direct"
        ) as mock_status:
            result = calculate_student_payment_summary(enrollment, academic_year)

        self.assertIsNone(result)
        mock_summary_filter.assert_called_once()
        mock_update_or_create.assert_not_called()
        mock_plan.assert_not_called()
        mock_status.assert_not_called()

    def test_refresh_payment_summary_skips_deleted_enrollment(self):
        class DummyEnrollment:
            pass

        academic_year = MagicMock()
        academic_year.id = "ay-1"

        enrollment = DummyEnrollment()
        enrollment.pk = "enr-deleted"
        enrollment.id = "enr-deleted"
        DummyEnrollment._default_manager = MagicMock()
        DummyEnrollment._default_manager.filter.return_value.exists.return_value = False

        with patch("finance.signals.clear_student_payment_cache") as mock_clear_cache, patch(
            "finance.utils.calculate_student_payment_summary"
        ) as mock_calculate_summary:
            _refresh_payment_summary_for_enrollment(enrollment, academic_year)

        mock_clear_cache.assert_not_called()
        mock_calculate_summary.assert_not_called()


class EffectivePaidFallbackTests(SimpleTestCase):
    @patch("accounting.models.AccountingCashTransaction.objects.filter")
    @patch("accounting.models.AccountingStudentPaymentAllocation.objects.filter")
    @patch("accounting.models.AccountingStudentBill.objects.filter")
    def test_effective_paid_uses_direct_cash_transactions_when_unallocated(
        self,
        mock_bill_filter,
        mock_allocation_filter,
        mock_cash_filter,
    ):
        from finance.models import _get_effective_paid_for_enrollment

        enrollment = MagicMock()
        enrollment.student.id = "student-uuid"
        enrollment.student.id_number = "STU-100"
        enrollment.student.prev_id_number = "OLD-100"
        academic_year = MagicMock()
        academic_year.start_date = date(2026, 1, 1)
        academic_year.end_date = date(2026, 12, 31)

        bills_qs = MagicMock()
        bills_qs.exists.return_value = True
        bills_qs.aggregate.return_value = {"total": Decimal("0.00")}
        mock_bill_filter.return_value = bills_qs

        mock_allocation_filter.return_value.aggregate.return_value = {"total": None}
        mock_cash_filter.return_value.aggregate.return_value = {"total": Decimal("95.00")}

        paid = _get_effective_paid_for_enrollment(enrollment, academic_year)

        self.assertEqual(paid, Decimal("95.00"))


class StudentTransactionsAccountingEndpointTests(SimpleTestCase):
    def test_student_transactions_returns_accounting_cash_payload(self):
        import importlib

        transaction_view_module = importlib.import_module("finance.views.transaction")

        factory = APIRequestFactory()
        request = factory.get("/transactions/students/STU-100/?academic_year=2025-2026")
        request.query_params = request.GET

        with patch.object(
            transaction_view_module,
            "get_object_by_uuid_or_fields",
        ) as mock_get_student, patch.object(
            transaction_view_module.AcademicYear.objects,
            "filter",
        ) as mock_academic_year_filter, patch.object(
            transaction_view_module.AccountingCashTransaction.objects,
            "select_related",
        ) as mock_select_related:
            student = MagicMock()
            student.id = "student-uuid"
            student.id_number = "STU-100"
            student.prev_id_number = "STU-099"
            student.get_full_name.return_value = "Ada Lovelace"
            mock_get_student.return_value = student

            academic_year = MagicMock()
            academic_year.id = "ay-1"
            academic_year.name = "2025-2026"
            academic_year.start_date = date(2025, 9, 1)
            academic_year.end_date = date(2026, 7, 31)
            mock_academic_year_filter.return_value.first.return_value = academic_year

            tx = MagicMock()
            tx.id = "tx-1"
            tx.reference_number = "TXN-20260101-00001"
            tx.amount = Decimal("120.00")
            tx.transaction_date = date(2026, 1, 10)
            tx.description = "Tuition payment"
            tx.status = "approved"

            tx.transaction_type_id = "tt-1"
            tx.transaction_type.id = "tt-1"
            tx.transaction_type.name = "Tuition"
            tx.transaction_type.code = "TUITION"
            tx.transaction_type.transaction_category = "income"

            tx.payment_method_id = "pm-1"
            tx.payment_method.id = "pm-1"
            tx.payment_method.name = "Cash"

            tx.bank_account_id = "ba-1"
            tx.bank_account.id = "ba-1"
            tx.bank_account.account_number = "100200300"
            tx.bank_account.account_name = "Main Cash"

            tx.currency_id = "cur-1"
            tx.currency.id = "cur-1"
            tx.currency.name = "US Dollar"
            tx.currency.symbol = "$"
            tx.currency.code = "USD"

            qs = MagicMock()
            qs.filter.return_value = qs
            qs.distinct.return_value = qs
            qs.order_by.return_value = [tx]
            mock_select_related.return_value = qs

            viewset = TransactionViewSet()
            response = viewset.student_transactions(request, student_id="STU-100")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["reference"], "TXN-20260101-00001")
        self.assertEqual(response.data[0]["transaction_type"]["type_code"], "TUITION")
        self.assertEqual(response.data[0]["status"], "approved")
