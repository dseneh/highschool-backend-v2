from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from common.utils import get_enrollment_bill_summary
from students.models import Student


class StudentAccountingBalanceTests(SimpleTestCase):
    @patch("finance.models._get_effective_paid_for_enrollment", return_value=Decimal("120.00"))
    @patch("students.models.student.get_current_academic_year")
    @patch("accounting.models.AccountingConcession.objects.filter")
    @patch("accounting.models.AccountingStudentBill.objects.filter")
    @patch("accounting.models.AccountingStudentBillLine.objects.filter")
    def test_balance_methods_and_summary_prefer_accounting_bill_table(
        self,
        mock_line_filter,
        mock_bill_filter,
        mock_concession_filter,
        mock_current_year,
        _mock_effective_paid,
    ):
        academic_year = MagicMock(id="ay-1")
        mock_current_year.return_value = academic_year

        accounting_bill_qs = MagicMock()
        accounting_bill_qs.aggregate.return_value = {
            "gross_total": Decimal("350.00"),
            "concession_total": Decimal("50.00"),
            "net_total": Decimal("300.00"),
            "paid_total": Decimal("120.00"),
            "outstanding_total": Decimal("180.00"),
        }
        mock_bill_filter.return_value = accounting_bill_qs

        accounting_lines = MagicMock()
        accounting_lines.exists.return_value = True
        accounting_lines.exclude.return_value.aggregate.return_value = {"total": Decimal("100.00")}
        accounting_lines.filter.return_value.aggregate.return_value = {"total": Decimal("250.00")}
        mock_line_filter.return_value = accounting_lines

        mock_concession_filter.return_value.order_by.return_value = []

        student = Student(
            first_name="Ada",
            last_name="Lovelace",
            gender="female",
            entry_as="new",
            school_code=1,
        )
        student._prefetched_objects_cache = {"transactions": []}

        with patch.object(Student, "transactions", create=True, new=MagicMock()) as mock_transactions:
            mock_transactions.filter.return_value.aggregate.return_value = {
                "approved": Decimal("0.00"),
                "pending": Decimal("0.00"),
                "canceled": Decimal("0.00"),
                "total": Decimal("0.00"),
            }

            self.assertEqual(student.get_approved_balance("ay-1"), Decimal("180.00"))

            balance_summary = student.get_balance_summary("ay-1")
            self.assertEqual(balance_summary["total_bills"], 300.0)
            self.assertEqual(balance_summary["approved_payments"], 120.0)
            self.assertEqual(balance_summary["approved_balance"], 180.0)

            enrollment = MagicMock(student=student, academic_year=academic_year)
            enrollment_summary = get_enrollment_bill_summary(enrollment)
            self.assertEqual(enrollment_summary["total_bill"], 300.0)
            self.assertEqual(enrollment_summary["paid"], 120.0)
            self.assertEqual(enrollment_summary["balance"], 180.0)

    @patch("finance.models._get_effective_paid_for_enrollment", return_value=Decimal("120.00"))
    @patch("accounting.models.AccountingConcession.objects.filter")
    @patch("accounting.models.AccountingStudentBill.objects.filter")
    @patch("accounting.models.AccountingStudentBillLine.objects.filter")
    def test_enrollment_bill_summary_uses_effective_paid_for_alignment(
        self,
        mock_line_filter,
        mock_bill_filter,
        mock_concession_filter,
        mock_effective_paid,
    ):
        accounting_bill_qs = MagicMock()
        accounting_bill_qs.aggregate.return_value = {
            "gross_total": Decimal("350.00"),
            "concession_total": Decimal("50.00"),
            "net_total": Decimal("300.00"),
            "paid_total": Decimal("0.00"),
            "outstanding_total": Decimal("300.00"),
        }
        mock_bill_filter.return_value = accounting_bill_qs

        accounting_lines = MagicMock()
        accounting_lines.exists.return_value = True
        accounting_lines.exclude.return_value.aggregate.return_value = {"total": Decimal("100.00")}
        accounting_lines.filter.return_value.aggregate.return_value = {"total": Decimal("250.00")}
        mock_line_filter.return_value = accounting_lines

        mock_concession_filter.return_value.order_by.return_value = []

        student = Student(
            first_name="Ada",
            last_name="Lovelace",
            gender="female",
            entry_as="new",
            school_code=1,
        )
        student._prefetched_objects_cache = {"transactions": []}

        enrollment = MagicMock(
            id="enr-1",
            student=student,
            academic_year=MagicMock(id="ay-1"),
        )

        summary = get_enrollment_bill_summary(enrollment)

        self.assertEqual(summary["total_bill"], 300.0)
        self.assertEqual(summary["paid"], 120.0)
        self.assertEqual(summary["balance"], 180.0)
        mock_effective_paid.assert_called_once_with(enrollment, enrollment.academic_year)
