from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from students.services.balance import build_effective_paid_subquery


class BuildEffectivePaidSubqueryTests(SimpleTestCase):
    @patch("students.services.balance.AccountingCashTransaction.objects")
    def test_paid_subquery_uses_full_student_match_and_dedupes_ids(self, mock_manager):
        outer_qs = MagicMock()
        inner_qs = MagicMock()
        sum_qs = MagicMock()
        mock_manager.filter.side_effect = [outer_qs, sum_qs]

        outer_qs.order_by.return_value = outer_qs
        outer_qs.values.return_value = outer_qs
        outer_qs.distinct.return_value = outer_qs

        sum_qs.order_by.return_value = sum_qs
        sum_qs.annotate.return_value = sum_qs
        sum_qs.values.return_value = sum_qs

        subquery = build_effective_paid_subquery(
            start_date="2025-09-01",
            end_date="2026-06-30",
        )

        self.assertIsNotNone(subquery)
        self.assertEqual(mock_manager.filter.call_count, 2)

        first_filter_kwargs = mock_manager.filter.call_args_list[0].kwargs
        self.assertEqual(first_filter_kwargs["transaction_date__gte"], "2025-09-01")
        self.assertEqual(first_filter_kwargs["transaction_date__lte"], "2026-06-30")
        outer_qs.distinct.assert_called_once_with()

    @patch("students.services.balance.get_total_paid_for_student_year", return_value=Decimal("250.00"))
    def test_get_effective_paid_for_student_delegates_to_cash_ledger_helper(self, mock_total_paid):
        from students.services.balance import get_effective_paid_for_student

        student = MagicMock()
        academic_year = MagicMock()

        paid = get_effective_paid_for_student(student, academic_year)

        self.assertEqual(paid, Decimal("250.00"))
        mock_total_paid.assert_called_once_with(student, academic_year)
