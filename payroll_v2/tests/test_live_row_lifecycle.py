"""Tests for paid live-row lifecycle and snapshot helpers."""

from decimal import Decimal
from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.test import SimpleTestCase

from payroll_v2.paid_table_snapshot import snapshot_has_rebuild_payload
from payroll_v2.report_snapshot_helpers import summarize_paid_snapshot_rows


class SnapshotRebuildPayloadTests(SimpleTestCase):
    def test_snapshot_has_rebuild_payload_requires_employee_items(self):
        self.assertFalse(snapshot_has_rebuild_payload(None))
        self.assertFalse(snapshot_has_rebuild_payload({"schema_version": 1, "rows": [{"id": "1"}]}))
        self.assertTrue(
            snapshot_has_rebuild_payload(
                {"schema_version": 2, "employee_items": [{"id": "1", "line_items": []}]}
            )
        )


class ReportSnapshotHelperTests(SimpleTestCase):
    def test_summarize_paid_snapshot_rows(self):
        rows = [
            {
                "gross_pay": "1000.00",
                "total_tax": "100.00",
                "total_deductions": "150.00",
                "total_reimbursements": "25.00",
                "net_pay": "875.00",
            },
            {
                "gross_pay": "500.00",
                "total_tax": "50.00",
                "total_deductions": "75.00",
                "total_reimbursements": "0.00",
                "net_pay": "425.00",
            },
        ]
        summary = summarize_paid_snapshot_rows(rows)
        self.assertEqual(summary["employee_count"], 2)
        self.assertEqual(summary["gross"], Decimal("1500.00"))
        self.assertEqual(summary["tax"], Decimal("150.00"))
        self.assertEqual(summary["deductions"], Decimal("225.00"))
        self.assertEqual(summary["reimbursements"], Decimal("25.00"))
        self.assertEqual(summary["take_home"], Decimal("1300.00"))


class RestorePayrollLiveRowsTests(SimpleTestCase):
    def test_restore_requires_rebuild_payload(self):
        from payroll_v2.live_row_lifecycle import restore_payroll_live_rows_from_snapshot

        payroll_run = MagicMock()
        payroll_run.employee_items.exists.return_value = False
        payroll_run.paid_table_snapshot = {"rows": [{"id": str(uuid4())}]}

        with self.assertRaisesMessage(ValueError, "employee_items rebuild payload"):
            restore_payroll_live_rows_from_snapshot(payroll_run)

    def test_restore_skips_when_live_rows_exist(self):
        from payroll_v2.live_row_lifecycle import restore_payroll_live_rows_from_snapshot

        payroll_run = MagicMock()
        payroll_run.employee_items.exists.return_value = True
        payroll_run.employee_items.count.return_value = 3

        restored = restore_payroll_live_rows_from_snapshot(payroll_run)
        self.assertEqual(restored, 3)

    @patch("payroll_v2.live_row_lifecycle.PayrollLineItem")
    @patch("payroll_v2.live_row_lifecycle.PayrollEmployeeItem")
    @patch("payroll_v2.live_row_lifecycle.PayrollCatalogItemRule.objects.filter")
    @patch("payroll_v2.live_row_lifecycle.EmployeePayrollItem.objects.filter")
    @patch("payroll_v2.live_row_lifecycle.PayrollCatalogItem.objects.filter")
    @patch("payroll_v2.live_row_lifecycle.EmployeeCompensation.objects.filter")
    def test_restore_nulls_missing_optional_foreign_keys(
        self,
        compensation_filter,
        payroll_item_filter,
        employee_payroll_item_filter,
        payroll_item_rule_filter,
        payroll_employee_item_cls,
        payroll_line_item_cls,
    ):
        from payroll_v2.live_row_lifecycle import restore_payroll_live_rows_from_snapshot

        compensation_filter.return_value.exists.return_value = False
        payroll_item_filter.return_value.exists.return_value = False
        employee_payroll_item_filter.return_value.exists.return_value = False
        payroll_item_rule_filter.return_value.exists.return_value = False

        captured_employee_kwargs = {}
        captured_line_kwargs = {}

        def build_employee_item(*args, **kwargs):
            captured_employee_kwargs.update(kwargs)
            item = MagicMock()
            item.id = kwargs.get("id")
            return item

        def build_line_item(*args, **kwargs):
            captured_line_kwargs.update(kwargs)
            line = MagicMock()
            line.id = kwargs.get("id")
            return line

        payroll_employee_item_cls.side_effect = build_employee_item
        payroll_line_item_cls.side_effect = build_line_item

        payroll_run = MagicMock()
        payroll_run.id = str(uuid4())
        payroll_run.employee_items.exists.return_value = False
        payroll_run.paid_table_snapshot = {
            "employee_items": [
                {
                    "id": str(uuid4()),
                    "employee": str(uuid4()),
                    "compensation": str(uuid4()),
                    "basic_salary": "1000.00",
                    "gross_pay": "1000.00",
                    "taxable_income": "1000.00",
                    "total_tax": "0.00",
                    "total_deductions": "0.00",
                    "total_benefits": "0.00",
                    "total_reimbursements": "0.00",
                    "net_pay": "1000.00",
                    "line_items": [
                        {
                            "id": str(uuid4()),
                            "line_type": "earning",
                            "name": "Allowance",
                            "amount": "100.00",
                            "calculation_type": "flat",
                            "target_amount_source": "basic_salary",
                            "payroll_item": str(uuid4()),
                            "employee_payroll_item": str(uuid4()),
                            "payroll_item_rule": str(uuid4()),
                        }
                    ],
                }
            ]
        }

        restored = restore_payroll_live_rows_from_snapshot(payroll_run)

        self.assertEqual(restored, 1)
        self.assertIsNone(captured_employee_kwargs["compensation"])
        self.assertIsNone(captured_line_kwargs["payroll_item"])
        self.assertIsNone(captured_line_kwargs["employee_payroll_item"])
        self.assertIsNone(captured_line_kwargs["payroll_item_rule"])


class RestoreBenefitLinesTests(SimpleTestCase):
    def test_restore_requires_snapshot_rows(self):
        from employee_benefits.live_row_lifecycle import restore_benefit_lines_from_snapshot

        benefit_request = MagicMock()
        benefit_request.lines.exists.return_value = False
        benefit_request.paid_table_snapshot = {}

        with self.assertRaisesMessage(ValueError, "missing line rows"):
            restore_benefit_lines_from_snapshot(benefit_request)

    def test_restore_skips_when_live_lines_exist(self):
        from employee_benefits.live_row_lifecycle import restore_benefit_lines_from_snapshot

        benefit_request = MagicMock()
        benefit_request.lines.exists.return_value = True
        benefit_request.lines.count.return_value = 2

        restored = restore_benefit_lines_from_snapshot(benefit_request)
        self.assertEqual(restored, 2)


class PurgePaidLiveRowsTests(SimpleTestCase):
    @patch("payroll_v2.live_row_lifecycle.delete_paid_live_rows")
    @patch("payroll_v2.live_row_lifecycle.delete_paid_live_rows_enabled", return_value=True)
    def test_purge_deletes_when_paid_and_enabled(self, _enabled, delete_rows):
        from payroll_v2.enums import PayrollStatus
        from payroll_v2.live_row_lifecycle import purge_paid_live_rows_if_enabled

        payroll_run = MagicMock()
        payroll_run.status = PayrollStatus.PAID
        delete_rows.return_value = 4

        deleted = purge_paid_live_rows_if_enabled(payroll_run)
        self.assertEqual(deleted, 4)
        delete_rows.assert_called_once_with(payroll_run)

    @patch("payroll_v2.live_row_lifecycle.delete_paid_live_rows")
    @patch("payroll_v2.live_row_lifecycle.delete_paid_live_rows_enabled", return_value=False)
    def test_purge_respects_feature_flag(self, _enabled, delete_rows):
        from payroll_v2.enums import PayrollStatus
        from payroll_v2.live_row_lifecycle import purge_paid_live_rows_if_enabled

        payroll_run = MagicMock()
        payroll_run.status = PayrollStatus.PAID

        deleted = purge_paid_live_rows_if_enabled(payroll_run)
        self.assertEqual(deleted, 0)
        delete_rows.assert_not_called()
