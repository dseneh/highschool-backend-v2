from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase

from payroll_v2.enums import (
    PayrollDeductionInstallmentStatus,
    PayrollDeductionScheduleStatus,
    PaymentMethod,
    SalaryAdvanceRepaymentMethod,
    SalaryAdvanceRepaymentStatus,
    SalaryAdvanceStatus,
    StaffWardSponsorshipStatus,
)
from payroll_v2.services import (
    cancel_salary_advance,
    cancel_staff_ward_sponsorship,
    complete_salary_advance,
    complete_staff_ward_sponsorship,
    ensure_salary_advance_can_be_deleted,
    ensure_staff_ward_sponsorship_can_be_deleted,
    get_run_obligation_deduction_violations,
    _installments_for_employee_in_period,
    _reschedule_salary_advance_future_installments,
    _validate_run_obligation_deduction_limits,
    approve_salary_advance,
    approve_staff_ward_sponsorship,
    apply_deduction_installments_for_run,
    apply_salary_advance_repayment_from_finance_transaction,
    adjust_deduction_installment,
    auto_adjust_deduction_installment,
    defer_deduction_installment,
    request_salary_advance_early_repayment,
    record_salary_advance_payment,
    revert_deduction_installments_for_run,
)


class EmployeeSelfServiceDeletionGuardTests(SimpleTestCase):
    @patch("payroll_v2.services._salary_advance_has_financial_processing", return_value=False)
    def test_salary_advance_self_service_allows_draft(self, _processing_mock):
        advance = SimpleNamespace(
            status=SalaryAdvanceStatus.DRAFT,
            completed_at=None,
            cancelled_at=None,
        )

        ensure_salary_advance_can_be_deleted(advance, self_service=True)

    @patch("payroll_v2.services._salary_advance_has_financial_processing", return_value=False)
    def test_salary_advance_self_service_rejects_non_draft_or_pending(self, _processing_mock):
        advance = SimpleNamespace(
            status=SalaryAdvanceStatus.APPROVED,
            completed_at=None,
            cancelled_at=None,
        )

        with self.assertRaisesMessage(ValueError, "Only draft or pending salary advance requests can be deleted."):
            ensure_salary_advance_can_be_deleted(advance, self_service=True)

    @patch("payroll_v2.services._salary_advance_has_financial_processing", return_value=True)
    def test_salary_advance_rejects_when_processing_exists(self, _processing_mock):
        advance = SimpleNamespace(
            status=SalaryAdvanceStatus.DRAFT,
            completed_at=None,
            cancelled_at=None,
        )

        with self.assertRaisesMessage(ValueError, "payroll or finance processing has already started"):
            ensure_salary_advance_can_be_deleted(advance, self_service=True)

    @patch("payroll_v2.services._staff_ward_sponsorship_has_financial_processing", return_value=False)
    def test_sponsorship_self_service_rejects_non_draft_or_pending(self, _processing_mock):
        sponsorship = SimpleNamespace(status=StaffWardSponsorshipStatus.APPROVED)

        with self.assertRaisesMessage(ValueError, "Only draft or pending ward sponsorship requests can be deleted."):
            ensure_staff_ward_sponsorship_can_be_deleted(sponsorship, self_service=True)

    @patch("payroll_v2.services._staff_ward_sponsorship_has_financial_processing", return_value=True)
    def test_sponsorship_rejects_when_processing_exists(self, _processing_mock):
        sponsorship = SimpleNamespace(status=StaffWardSponsorshipStatus.DRAFT)

        with self.assertRaisesMessage(ValueError, "payroll or finance processing has already started"):
            ensure_staff_ward_sponsorship_can_be_deleted(sponsorship, self_service=True)


class DeductionInstallmentWorkflowTests(TestCase):
    @patch("payroll_v2.services._recompute_schedule_remaining_and_status")
    def test_adjust_installment_marks_adjusted(self, recompute_mock):
        schedule = MagicMock()
        schedule.scheduled_amount = Decimal("100.00")

        installment = MagicMock()
        installment.deduction_schedule = schedule

        result = adjust_deduction_installment(
            installment=installment,
            amount=Decimal("75.00"),
            reason="Manual correction",
            actor=None,
        )

        self.assertIs(result, installment)
        self.assertEqual(installment.scheduled_amount, Decimal("75.00"))
        self.assertEqual(installment.status, PayrollDeductionInstallmentStatus.ADJUSTED)
        self.assertEqual(installment.adjustment_reason, "Manual correction")
        self.assertEqual(schedule.status, PayrollDeductionScheduleStatus.ADJUSTED)
        recompute_mock.assert_called_once_with(schedule, actor=None)

    @patch("payroll_v2.services._refresh_deduction_schedule_snapshot")
    def test_defer_installment_marks_deferred(self, refresh_snapshot_mock):
        schedule = MagicMock()
        installment = MagicMock()
        installment.deduction_schedule = schedule

        result = defer_deduction_installment(
            installment=installment,
            reason="Insufficient net pay",
            actor=None,
        )

        self.assertIs(result, installment)
        self.assertEqual(installment.status, PayrollDeductionInstallmentStatus.DEFERRED)
        self.assertEqual(installment.adjustment_reason, "Insufficient net pay")
        self.assertEqual(schedule.status, PayrollDeductionScheduleStatus.DEFERRED)
        refresh_snapshot_mock.assert_called_once_with(schedule)

    @patch("payroll_v2.services.adjust_deduction_installment")
    def test_auto_adjust_uses_min_allowed_amount(self, adjust_mock):
        installment = MagicMock()
        installment.scheduled_amount = Decimal("120.00")

        auto_adjust_deduction_installment(
            installment=installment,
            max_allowed_amount=Decimal("85.00"),
            reason="Policy cap",
            actor=None,
        )

        adjust_mock.assert_called_once()
        kwargs = adjust_mock.call_args.kwargs
        self.assertEqual(kwargs["amount"], Decimal("85.00"))


class PayrollSubmissionLimitValidationTests(SimpleTestCase):
    @patch("payroll_v2.services.evaluate_deduction_limits")
    @patch("payroll_v2.services._active_policy_for_date")
    def test_validation_raises_when_policy_limit_fails(self, policy_mock, limit_mock):
        policy_mock.return_value = SimpleNamespace(
            max_payroll_deduction_percent_of_gross=Decimal("40"),
            min_net_pay_percent_of_gross=Decimal("30"),
        )
        limit_mock.return_value = SimpleNamespace(is_allowed=False)

        line = SimpleNamespace(
            source_type="PayrollDeductionInstallment",
            amount=Decimal("90.00"),
            metadata={"deduction_source_type": "staff_ward_sponsorship"},
        )
        item = MagicMock()
        item.employee_id = "emp-1"
        item.gross_pay = Decimal("2000.00")
        item.total_deductions = Decimal("1450.00")
        item.line_items.all.return_value = [line]

        payroll_run = MagicMock()
        payroll_run.pay_period_start = "2026-08-01"
        payroll_run.employee_items.prefetch_related.return_value.all.return_value = [item]

        with self.assertRaises(ValueError):
            _validate_run_obligation_deduction_limits(payroll_run)

    @patch("payroll_v2.services.evaluate_deduction_limits")
    @patch("payroll_v2.services._active_policy_for_date")
    def test_structured_violations_payload_contains_reasons(self, policy_mock, limit_mock):
        policy_mock.return_value = SimpleNamespace(
            id="pol-1",
            name="Default policy",
            max_payroll_deduction_percent_of_gross=Decimal("40"),
            min_net_pay_percent_of_gross=Decimal("30"),
            effective_from="2026-01-01",
            effective_to=None,
        )
        limit_mock.return_value = SimpleNamespace(
            is_allowed=False,
            exceeds_max_deduction=True,
            below_min_net_pay=False,
            resulting_total_deductions=Decimal("900.00"),
            resulting_net_pay=Decimal("1100.00"),
            max_allowed_deductions=Decimal("800.00"),
            min_required_net_pay=Decimal("600.00"),
        )

        employee = SimpleNamespace(get_full_name=lambda: "Avery Doe", id_number="E001")
        line = SimpleNamespace(
            source_type="PayrollDeductionInstallment",
            amount=Decimal("90.00"),
            metadata={"deduction_source_type": "salary_advance"},
        )
        item = MagicMock()
        item.employee_id = "emp-1"
        item.employee = employee
        item.gross_pay = Decimal("2000.00")
        item.total_deductions = Decimal("950.00")
        item.line_items.all.return_value = [line]

        payroll_run = MagicMock()
        payroll_run.pay_period_start = "2026-08-01"
        payroll_run.employee_items.prefetch_related.return_value.all.return_value = [item]

        payload = get_run_obligation_deduction_violations(payroll_run)

        self.assertEqual(payload["policy"]["name"], "Default policy")
        self.assertEqual(len(payload["violations"]), 1)
        self.assertEqual(payload["violations"][0]["employee_id"], "emp-1")
        self.assertEqual(payload["violations"][0]["employee_name"], "Avery Doe")
        self.assertEqual(payload["violations"][0]["reasons"][0]["code"], "exceeds_max_total_deduction")


class InstallmentApplyRevertTests(SimpleTestCase):
    @patch("payroll_v2.services._recompute_schedule_remaining_and_status")
    @patch("payroll_v2.services.PayrollDeductionInstallment.objects.select_related")
    @patch("payroll_v2.services.PayrollLineItem.objects.filter")
    def test_apply_installments_marks_applied(
        self,
        line_filter_mock,
        installment_select_mock,
        recompute_mock,
    ):
        line = SimpleNamespace(source_id="inst-1", amount=Decimal("75.00"))
        lines_qs = MagicMock()
        lines_qs.exists.return_value = True
        lines_qs.__iter__.side_effect = lambda: iter([line])
        line_filter_mock.return_value = lines_qs

        class StubInstallment:
            def __init__(self):
                self.id = "inst-1"
                self.deduction_schedule_id = "sched-1"
                self.status = None
                self.actual_amount = Decimal("0.00")
                self.payroll_line = None
                self.applied_at = None
                self.updated_by = None

            def save(self, **kwargs):
                return None

        installment = StubInstallment()

        installment_select_mock.return_value.filter.return_value = [installment]

        with patch("payroll_v2.services.PayrollDeductionSchedule.objects.filter") as schedule_filter_mock:
            schedule_filter_mock.return_value = [MagicMock()]
            apply_deduction_installments_for_run(MagicMock(), actor=None)

        self.assertEqual(installment.status, "applied")
        self.assertEqual(installment.actual_amount, Decimal("75.00"))
        recompute_mock.assert_called()

    @patch("payroll_v2.services._recompute_schedule_remaining_and_status")
    @patch("payroll_v2.services.PayrollDeductionInstallment.objects.select_related")
    @patch("payroll_v2.services.PayrollLineItem.objects.filter")
    def test_revert_installments_marks_planned(
        self,
        line_filter_mock,
        installment_select_mock,
        recompute_mock,
    ):
        line = SimpleNamespace(source_id="inst-1", amount=Decimal("75.00"))
        lines_qs = MagicMock()
        lines_qs.exists.return_value = True
        lines_qs.__iter__.side_effect = lambda: iter([line])
        line_filter_mock.return_value = lines_qs

        class StubInstallment:
            def __init__(self):
                self.id = "inst-1"
                self.deduction_schedule_id = "sched-1"
                self.status = "applied"
                self.actual_amount = Decimal("75.00")
                self.payroll_line = object()
                self.applied_at = object()
                self.updated_by = None

            def save(self, **kwargs):
                return None

        installment = StubInstallment()

        installment_select_mock.return_value.filter.return_value = [installment]

        with patch("payroll_v2.services.PayrollDeductionSchedule.objects.filter") as schedule_filter_mock:
            schedule_filter_mock.return_value = [MagicMock()]
            revert_deduction_installments_for_run(MagicMock(), actor=None)

        self.assertEqual(installment.status, "planned")
        self.assertEqual(installment.actual_amount, Decimal("0.00"))
        recompute_mock.assert_called()


class SalaryAdvanceApprovalTests(TestCase):
    @patch("payroll_v2.services.validate_employee_obligation_eligibility")
    @patch("payroll_v2.settings_services.get_tenant_payroll_settings")
    @patch("payroll_v2.services._ensure_salary_advance_employee_deduction_item")
    @patch("payroll_v2.services.create_or_replace_deduction_schedule")
    def test_approve_does_not_create_schedule_or_item(
        self,
        create_schedule_mock,
        ensure_item_mock,
        settings_mock,
        _validate_eligibility_mock,
    ):
        settings_mock.return_value = SimpleNamespace()

        advance = SimpleNamespace(
            status=SalaryAdvanceStatus.SUBMITTED,
            repayment_start_period_id="period-1",
            repayment_start_period=SimpleNamespace(id="period-1"),
            approved_amount=Decimal("0.00"),
            amount=Decimal("10000.00"),
            installment_amount=Decimal("10000.00"),
            number_of_installments=6,
            repayment_method=SalaryAdvanceRepaymentMethod.EQUAL_SPLIT,
            amount_paid=Decimal("0.00"),
            employee=SimpleNamespace(id="emp-1"),
            id="adv-1",
            repayment_status=SalaryAdvanceRepaymentStatus.NOT_STARTED,
            save=MagicMock(),
        )

        approve_salary_advance(advance, user=None)

        create_schedule_mock.assert_not_called()
        ensure_item_mock.assert_not_called()
        self.assertEqual(advance.status, SalaryAdvanceStatus.APPROVED)
        self.assertEqual(advance.approved_amount, Decimal("10000.00"))
        self.assertEqual(advance.remaining_balance, Decimal("10000.00"))


class StaffWardSponsorshipWorkflowTests(TestCase):
    @patch("payroll_v2.services.validate_employee_obligation_eligibility")
    @patch("payroll_v2.settings_services.get_tenant_payroll_settings")
    def test_approve_updates_amounts_from_student_rows(self, settings_mock, validate_mock):
        settings_mock.return_value = SimpleNamespace()

        sponsorship = SimpleNamespace(
            status=StaffWardSponsorshipStatus.PENDING,
            start_period=SimpleNamespace(start_date=date(2026, 9, 1)),
            start_period_id="period-1",
            payroll_recovery_amount=Decimal("0.00"),
            employee=SimpleNamespace(id="emp-1"),
            id="spon-1",
            academic_year=SimpleNamespace(end_date=date(2027, 2, 28)),
            academic_year_id="year-1",
            sponsorship_students=SimpleNamespace(
                all=lambda: [
                    SimpleNamespace(
                        eligible_fee_total=Decimal("1000.00"),
                        school_covered_amount=Decimal("600.00"),
                        employee_responsibility_amount=Decimal("400.00"),
                    ),
                    SimpleNamespace(
                        eligible_fee_total=Decimal("500.00"),
                        school_covered_amount=Decimal("200.00"),
                        employee_responsibility_amount=Decimal("300.00"),
                    ),
                ]
            ),
            save=MagicMock(),
        )

        approve_staff_ward_sponsorship(sponsorship, user=SimpleNamespace(id="user-1"))

        validate_mock.assert_called_once()
        self.assertEqual(sponsorship.total_sponsored_amount, Decimal("1500.00"))
        self.assertEqual(sponsorship.school_contribution_amount, Decimal("800.00"))
        self.assertEqual(sponsorship.employee_contribution_amount, Decimal("700.00"))
        self.assertEqual(sponsorship.payroll_recovery_amount, Decimal("250.00"))
        self.assertEqual(sponsorship.status, StaffWardSponsorshipStatus.APPROVED)

    @patch("payroll_v2.services._ensure_staff_ward_sponsorship_employee_deduction_item")
    @patch("payroll_v2.services.create_or_replace_deduction_schedule")
    @patch("payroll_v2.services.PayrollPeriod.objects.filter")
    @patch("payroll_v2.services.validate_employee_obligation_eligibility")
    @patch("payroll_v2.settings_services.get_tenant_payroll_settings")
    def test_complete_creates_schedule_and_employee_item(
        self,
        settings_mock,
        validate_mock,
        period_filter_mock,
        create_schedule_mock,
        ensure_item_mock,
    ):
        settings_mock.return_value = SimpleNamespace()
        validate_mock.return_value = None
        period_filter_mock.return_value.order_by.return_value = [
            SimpleNamespace(id="period-1", start_date=date(2026, 8, 1), end_date=date(2026, 8, 31), payment_date=date(2026, 8, 31)),
            SimpleNamespace(id="period-2", start_date=date(2026, 9, 1), end_date=date(2026, 9, 30), payment_date=date(2026, 9, 30)),
        ]
        create_schedule_mock.return_value = SimpleNamespace(scheduled_amount=Decimal("700.00"))

        sponsorship = SimpleNamespace(
            status=StaffWardSponsorshipStatus.APPROVED,
            start_period=None,
            start_period_id=None,
            end_period=None,
            end_period_id=None,
            payroll_recovery_amount=Decimal("0.00"),
            total_sponsored_amount=Decimal("0.00"),
            repayment_schedule=[],
            employee=SimpleNamespace(id="emp-1"),
            id="spon-1",
            academic_year=SimpleNamespace(end_date=date(2027, 2, 28)),
            academic_year_id="year-1",
            sponsorship_students=SimpleNamespace(
                all=lambda: [
                    SimpleNamespace(
                        eligible_fee_total=Decimal("1000.00"),
                        school_covered_amount=Decimal("600.00"),
                        employee_responsibility_amount=Decimal("400.00"),
                    ),
                    SimpleNamespace(
                        eligible_fee_total=Decimal("500.00"),
                        school_covered_amount=Decimal("200.00"),
                        employee_responsibility_amount=Decimal("300.00"),
                    ),
                ]
            ),
            save=MagicMock(),
        )
        sponsorship.start_period = SimpleNamespace(schedule_id="sched-1", start_date=date(2026, 8, 1), end_date=date(2026, 8, 31))

        complete_staff_ward_sponsorship(sponsorship, user=SimpleNamespace(id="user-1"))

        create_schedule_mock.assert_called_once()
        ensure_item_mock.assert_called_once()
        self.assertEqual(sponsorship.status, StaffWardSponsorshipStatus.ACTIVE)
        self.assertEqual(sponsorship.payroll_recovery_amount, Decimal("700.00"))
        self.assertEqual(create_schedule_mock.call_args.kwargs["total_amount"], Decimal("1500.00"))

    @patch("payroll_v2.services._refresh_deduction_schedule_snapshot")
    @patch("payroll_v2.services._staff_ward_sponsorship_open_schedules")
    @patch("payroll_v2.services.EmployeePayrollItem.objects.filter")
    def test_cancel_deactivates_open_schedule_and_item(
        self,
        payroll_item_filter_mock,
        open_schedules_mock,
        refresh_snapshot_mock,
    ):
        schedule = SimpleNamespace(
            installments=SimpleNamespace(exclude=lambda **kwargs: SimpleNamespace(update=lambda **update_kwargs: None)),
            status=None,
            scheduled_amount=Decimal("700.00"),
            remaining_amount=Decimal("700.00"),
            save=MagicMock(),
            updated_by=None,
        )
        schedules_qs = MagicMock()
        schedules_qs.filter.return_value = schedules_qs
        schedules_qs.exists.return_value = False
        schedules_qs.__iter__.return_value = iter([schedule])
        open_schedules_mock.return_value = schedules_qs
        payroll_item_filter_mock.return_value.update.return_value = 1

        sponsorship = SimpleNamespace(
            status=StaffWardSponsorshipStatus.ACTIVE,
            employee=SimpleNamespace(id="emp-1"),
            id="spon-1",
            save=MagicMock(),
        )

        cancel_staff_ward_sponsorship(sponsorship, reason="Employee request", user=SimpleNamespace(id="user-1"))

        payroll_item_filter_mock.assert_called_once()
        refresh_snapshot_mock.assert_called_once()
        self.assertEqual(sponsorship.status, StaffWardSponsorshipStatus.CANCELLED)


    @patch("payroll_v2.services._ensure_salary_advance_employee_deduction_item")
    @patch("payroll_v2.services.create_or_replace_deduction_schedule")
    def test_complete_creates_schedule_and_item(
        self,
        create_schedule_mock,
        ensure_item_mock,
    ):
        create_schedule_mock.return_value = SimpleNamespace(
            scheduled_amount=Decimal("1000.00"),
            installments=SimpleNamespace(count=lambda: 6),
        )

        advance = SimpleNamespace(
            status=SalaryAdvanceStatus.APPROVED,
            repayment_start_period_id="period-1",
            repayment_start_period=SimpleNamespace(id="period-1", start_date=date(2026, 8, 1)),
            approved_amount=Decimal("10000.00"),
            amount=Decimal("10000.00"),
            installment_amount=Decimal("1000.00"),
            amount_paid=Decimal("0.00"),
            remaining_balance=Decimal("0.00"),
            number_of_installments=6,
            repayment_method=SalaryAdvanceRepaymentMethod.FIXED_INSTALLMENT,
            employee=SimpleNamespace(id="emp-1"),
            id="adv-1",
            repayment_status=SalaryAdvanceRepaymentStatus.NOT_STARTED,
            save=MagicMock(),
        )

        complete_salary_advance(advance, user=None)

        self.assertEqual(
            create_schedule_mock.call_args.kwargs["fixed_installment_amount"],
            Decimal("1000.00"),
        )
        ensure_item_mock.assert_called_once()
        self.assertEqual(advance.status, SalaryAdvanceStatus.COMPLETED)
        self.assertEqual(advance.remaining_balance, Decimal("10000.00"))

    @patch("payroll_v2.services._deactivate_salary_advance_employee_deduction_item")
    @patch("payroll_v2.services._salary_advance_open_schedules")
    def test_cancel_completed_advance_requires_no_repayment_activity(
        self,
        open_schedules_mock,
        deactivate_item_mock,
    ):
        open_schedules_mock.return_value = []

        advance = SimpleNamespace(
            status=SalaryAdvanceStatus.COMPLETED,
            repayment_start_period_id="period-1",
            repayment_start_period=SimpleNamespace(id="period-1", end_date=date(2026, 8, 31)),
            approved_amount=Decimal("10000.00"),
            amount=Decimal("10000.00"),
            installment_amount=Decimal("0.00"),
            amount_paid=Decimal("0.00"),
            remaining_balance=Decimal("10000.00"),
            number_of_installments=6,
            repayment_method=SalaryAdvanceRepaymentMethod.EQUAL_SPLIT,
            employee=SimpleNamespace(id="emp-1"),
            id="adv-1",
            repayment_status=SalaryAdvanceRepaymentStatus.NOT_STARTED,
            save=MagicMock(),
        )

        cancel_salary_advance(advance, reason="Employee withdrew request", user=None)

        deactivate_item_mock.assert_called_once()
        self.assertEqual(advance.status, SalaryAdvanceStatus.CANCELLED)
        self.assertEqual(advance.remaining_balance, Decimal("0.00"))

    @patch("payroll_v2.services._reschedule_salary_advance_future_installments")
    @patch("payroll_v2.services._deactivate_salary_advance_employee_deduction_item")
    @patch("payroll_v2.services.SalaryAdvancePayment.objects.create")
    def test_record_partial_early_payment_updates_repayment_status(
        self,
        payment_create_mock,
        deactivate_item_mock,
        reschedule_mock,
    ):
        payment_create_mock.return_value = SimpleNamespace(id="payment-1")

        advance = SimpleNamespace(
            status=SalaryAdvanceStatus.COMPLETED,
            approved_amount=Decimal("5000.00"),
            amount=Decimal("5000.00"),
            amount_paid=Decimal("1000.00"),
            remaining_balance=Decimal("4000.00"),
            repayment_status=SalaryAdvanceRepaymentStatus.IN_PROGRESS,
            repayment_method=SalaryAdvanceRepaymentMethod.EQUAL_SPLIT,
            installment_amount=Decimal("0.00"),
            employee=SimpleNamespace(id="emp-1"),
            id="adv-1",
            save=MagicMock(),
        )

        record_salary_advance_payment(
            advance,
            amount=Decimal("1500.00"),
            payment_date=date(2026, 8, 10),
            notes="Manual repayment",
            user=None,
        )

        self.assertEqual(advance.amount_paid, Decimal("2500.00"))
        self.assertEqual(advance.remaining_balance, Decimal("2500.00"))
        self.assertEqual(advance.repayment_status, SalaryAdvanceRepaymentStatus.IN_PROGRESS)
        deactivate_item_mock.assert_not_called()
        reschedule_mock.assert_called_once()


class SalaryAdvanceLegacyRepairTests(SimpleTestCase):
    @patch("payroll_v2.services.create_or_replace_deduction_schedule")
    @patch("payroll_v2.services.SalaryAdvance.objects.filter")
    @patch("payroll_v2.services.PayrollDeductionSchedule.objects.select_related")
    @patch("payroll_v2.services.PayrollDeductionInstallment.objects.select_related")
    @patch("payroll_v2.services._reset_orphaned_applied_installments_for_period")
    def test_installment_lookup_repairs_legacy_equal_split_schedule(
        self,
        reset_orphaned_mock,
        installment_select_mock,
        schedule_select_mock,
        advances_filter_mock,
        create_schedule_mock,
    ):
        employee = SimpleNamespace(id="emp-1")
        payroll_period = SimpleNamespace(id="period-1")

        first_installment = SimpleNamespace(
            id="inst-1",
            scheduled_amount=Decimal("10000.00"),
            status=PayrollDeductionInstallmentStatus.PLANNED,
        )
        trailing_installment = SimpleNamespace(
            id="inst-2",
            scheduled_amount=Decimal("0.00"),
            status=PayrollDeductionInstallmentStatus.PLANNED,
        )

        installments_manager = MagicMock()
        installments_manager.select_related.return_value.order_by.return_value = [
            first_installment,
            trailing_installment,
        ]

        schedule = SimpleNamespace(
            source_id="adv-1",
            source_type="salary_advance",
            employee=employee,
            total_amount=Decimal("10000.00"),
            scheduled_amount=Decimal("10000.00"),
            start_period=SimpleNamespace(id="start-period"),
            end_period=SimpleNamespace(id="end-period"),
            installments=installments_manager,
        )

        schedule_select_mock.return_value.filter.return_value = [schedule]
        advances_filter_mock.return_value = [
            SimpleNamespace(
                id="adv-1",
                repayment_method=SalaryAdvanceRepaymentMethod.EQUAL_SPLIT,
                number_of_installments=6,
            )
        ]

        expected_qs = object()
        installment_select_mock.return_value.filter.return_value = expected_qs

        result = _installments_for_employee_in_period(employee=employee, payroll_period=payroll_period)

        self.assertIs(result, expected_qs)
        create_schedule_mock.assert_called_once()
        kwargs = create_schedule_mock.call_args.kwargs
        self.assertEqual(kwargs["source_type"], "salary_advance")
        self.assertEqual(kwargs["number_of_installments"], 6)
        self.assertIsNone(kwargs["fixed_installment_amount"])
        reset_orphaned_mock.assert_called_once_with(employee=employee, payroll_period=payroll_period)


class SalaryAdvanceEarlyRepaymentWorkflowTests(TestCase):
    @patch("payroll_v2.services.user_has_permission", return_value=True)
    @patch("payroll_v2.services.AccountingCashTransaction.objects.create")
    @patch("payroll_v2.services._salary_advance_repayment_bank_account")
    @patch("payroll_v2.services._salary_advance_repayment_tx_type")
    @patch("payroll_v2.services._salary_advance_repayment_payment_method")
    @patch("payroll_v2.services.AccountingSettings.objects.select_related")
    def test_request_creates_pending_finance_transaction_without_mutating_advance(
        self,
        settings_select_mock,
        payment_method_mock,
        tx_type_mock,
        bank_account_mock,
        cash_tx_create_mock,
        _permission_mock,
    ):
        accounting_settings = SimpleNamespace(
            salary_advance_repayment_ledger_account_id="ledger-1",
            salary_advance_repayment_ledger_account=SimpleNamespace(id="ledger-1"),
        )
        settings_qs = MagicMock()
        settings_qs.order_by.return_value.first.return_value = accounting_settings
        settings_select_mock.return_value = settings_qs

        bank_account = SimpleNamespace(currency_id="USD", currency=SimpleNamespace(id="USD"))
        bank_account_mock.return_value = bank_account

        tx_type = SimpleNamespace(id="tx-type-1")
        tx_type_mock.return_value = tx_type
        payment_method_mock.return_value = SimpleNamespace(id="payment-method-1")

        finance_tx = SimpleNamespace(id="tx-1", reference_number="SAR-ADV-0001", status="pending")
        cash_tx_create_mock.return_value = finance_tx

        advance = SimpleNamespace(
            status=SalaryAdvanceStatus.COMPLETED,
            remaining_balance=Decimal("2500.00"),
            amount_paid=Decimal("1500.00"),
            employee=SimpleNamespace(get_full_name=lambda: "Avery Doe"),
            employee_id="emp-1",
            id="adv-1",
        )

        payload = request_salary_advance_early_repayment(
            advance,
            amount=Decimal("500.00"),
            payment_date=date(2026, 8, 10),
            payment_method=PaymentMethod.BANK_TRANSFER,
            reference="RCPT-1",
            notes="Pending finance review",
            user=SimpleNamespace(),
        )

        self.assertEqual(advance.amount_paid, Decimal("1500.00"))
        self.assertEqual(advance.remaining_balance, Decimal("2500.00"))
        self.assertEqual(payload["salary_advance"], "adv-1")
        self.assertEqual(payload["finance_transaction_id"], "tx-1")
        self.assertEqual(payload["finance_transaction_reference"], "SAR-ADV-0001")
        self.assertEqual(payload["finance_transaction_status"], "pending")
        cash_tx_create_mock.assert_called_once()
        self.assertEqual(cash_tx_create_mock.call_args.kwargs["status"], "pending")
        self.assertEqual(cash_tx_create_mock.call_args.kwargs["source_reference"], "salary-advance:adv-1")

    @patch("payroll_v2.services.SalaryAdvancePayment.objects.filter")
    @patch("payroll_v2.services.SalaryAdvancePayment.objects.create")
    @patch("payroll_v2.services._reschedule_salary_advance_future_installments")
    @patch("payroll_v2.services._deactivate_salary_advance_employee_deduction_item")
    @patch("payroll_v2.services.SalaryAdvance.objects.select_for_update")
    def test_completed_finance_transaction_applies_repayment_and_shortens_schedule(
        self,
        select_for_update_mock,
        deactivate_mock,
        reschedule_mock,
        payment_create_mock,
        payment_filter_mock,
    ):
        advance = SimpleNamespace(
            status=SalaryAdvanceStatus.COMPLETED,
            approved_amount=Decimal("5000.00"),
            amount=Decimal("5000.00"),
            amount_paid=Decimal("1500.00"),
            remaining_balance=Decimal("3500.00"),
            repayment_status=SalaryAdvanceRepaymentStatus.IN_PROGRESS,
            repayment_method=SalaryAdvanceRepaymentMethod.EQUAL_SPLIT,
            installment_amount=Decimal("0.00"),
            employee=SimpleNamespace(id="emp-1", get_full_name=lambda: "Avery Doe"),
            employee_id="emp-1",
            id="adv-1",
            save=MagicMock(),
        )
        advance_qs = MagicMock()
        advance_qs.filter.return_value.first.return_value = advance
        select_for_update_mock.return_value = advance_qs

        existing_qs = MagicMock()
        existing_qs.first.return_value = None
        payment_filter_mock.return_value = existing_qs

        payment = SimpleNamespace(id="payment-1")
        payment_create_mock.return_value = payment

        finance_transaction = SimpleNamespace(
            status="completed",
            source_reference="salary-advance:adv-1",
            amount=Decimal("1200.00"),
            transaction_date=date(2026, 8, 10),
            reference_number="SAR-ADV-0001",
            notes="Approved by finance",
        )

        result = apply_salary_advance_repayment_from_finance_transaction(
            finance_transaction=finance_transaction,
            actor=SimpleNamespace(role="finance"),
        )

        self.assertIs(result, payment)
        payment_create_mock.assert_called_once()
        self.assertEqual(payment_create_mock.call_args.kwargs["finance_transaction"], finance_transaction)
        self.assertEqual(advance.amount_paid, Decimal("2700.00"))
        self.assertEqual(advance.remaining_balance, Decimal("2300.00"))
        advance.save.assert_called_once()
        reschedule_mock.assert_called_once_with(advance=advance, actor=SimpleNamespace(role="finance"))
        deactivate_mock.assert_not_called()

    @patch("payroll_v2.services._refresh_deduction_schedule_snapshot")
    @patch("payroll_v2.services._salary_advance_open_schedules")
    @patch("payroll_v2.services.calculate_equal_installment_amount")
    def test_reschedule_shortens_and_cancels_excess_installments(
        self,
        equal_amount_mock,
        open_schedules_mock,
        refresh_snapshot_mock,
    ):
        equal_amount_mock.return_value = Decimal("400.00")

        class StubInstallment:
            def __init__(self, identifier):
                self.id = identifier
                self.scheduled_amount = Decimal("400.00")
                self.status = PayrollDeductionInstallmentStatus.PLANNED
                self.adjustment_reason = ""
                self.updated_by = None
                self.saved_updates = []

            def save(self, **kwargs):
                self.saved_updates.append(kwargs.get("update_fields", []))

        installment_1 = StubInstallment("inst-1")
        installment_2 = StubInstallment("inst-2")
        installment_3 = StubInstallment("inst-3")

        installments_qs = MagicMock()
        installments_qs.exclude.return_value.order_by.return_value = [installment_1, installment_2, installment_3]

        schedule = SimpleNamespace(
            installments=installments_qs,
            remaining_amount=Decimal("0.00"),
            scheduled_amount=Decimal("0.00"),
            status=PayrollDeductionScheduleStatus.PLANNED,
            save=MagicMock(),
        )
        open_schedules_qs = MagicMock()
        open_schedules_qs.order_by.return_value.first.return_value = schedule
        open_schedules_mock.return_value = open_schedules_qs

        advance = SimpleNamespace(
            remaining_balance=Decimal("700.00"),
            amount_paid=Decimal("300.00"),
            repayment_method=SalaryAdvanceRepaymentMethod.FIXED_INSTALLMENT,
            installment_amount=Decimal("400.00"),
        )

        _reschedule_salary_advance_future_installments(advance=advance, actor=SimpleNamespace(role="finance"))

        self.assertEqual(installment_1.scheduled_amount, Decimal("400.00"))
        self.assertEqual(installment_2.scheduled_amount, Decimal("300.00"))
        self.assertEqual(installment_3.status, PayrollDeductionInstallmentStatus.CANCELLED)
        self.assertEqual(installment_3.adjustment_reason, "Shortened after early repayment.")
        self.assertEqual(schedule.status, PayrollDeductionScheduleStatus.PARTIALLY_APPLIED)
        refresh_snapshot_mock.assert_called_once_with(schedule)
