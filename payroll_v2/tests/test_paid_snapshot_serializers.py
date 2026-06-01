"""Serializer tests for paid snapshot-backed API fields."""

from unittest.mock import MagicMock

from django.test import SimpleTestCase

from employee_benefits.enums import BenefitRequestStatus
from employee_benefits.serializers import BenefitRequestDetailSerializer
from payroll_v2.enums import PayrollStatus
from payroll_v2.serializers import PayrollRunDetailSerializer, PayrollRunListSerializer


class PayrollRunSerializerSnapshotTests(SimpleTestCase):
    def test_list_employee_count_from_paid_snapshot(self):
        run = MagicMock()
        run.status = PayrollStatus.PAID
        run.paid_table_snapshot = {"totals": {"line_count": 7}, "rows": []}
        run.employee_items.count.return_value = 0

        count = PayrollRunListSerializer().get_employee_count(run)
        self.assertEqual(count, 7)

    def test_detail_employee_items_from_paid_snapshot(self):
        run = MagicMock()
        run.status = PayrollStatus.PAID
        run.paid_table_snapshot = {
            "rows": [{"id": "row-1"}],
            "employee_items": [{"id": "item-1", "net_pay": "100.00"}],
        }

        items = PayrollRunDetailSerializer().get_employee_items(run)
        self.assertEqual(items, [{"id": "item-1", "net_pay": "100.00"}])


class BenefitRequestSerializerSnapshotTests(SimpleTestCase):
    def test_detail_lines_from_paid_snapshot(self):
        request = MagicMock()
        request.status = BenefitRequestStatus.PAID
        request.paid_table_snapshot = {
            "rows": [{"id": "line-1", "final_amount": "250.00"}],
        }

        lines = BenefitRequestDetailSerializer().get_lines(request)
        self.assertEqual(lines, [{"id": "line-1", "final_amount": "250.00"}])
