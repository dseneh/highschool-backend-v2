from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from payroll_v2.enums import DeductionSourceType, EmployeeContributionType, SponsorshipCoverageType
from payroll_v2.obligation_services import (
    calculate_employee_contribution_amount,
    calculate_equal_installment_amount,
    calculate_sponsorship_coverage_amount,
    evaluate_employee_obligation_eligibility,
    evaluate_deduction_limits,
)


class ObligationServiceTests(SimpleTestCase):
    def test_percentage_sponsorship_coverage(self):
        amount = calculate_sponsorship_coverage_amount(
            eligible_fee_total=Decimal("1200.00"),
            coverage_type=SponsorshipCoverageType.PERCENTAGE,
            coverage_value=Decimal("70"),
        )
        self.assertEqual(amount, Decimal("840.00"))

    def test_employee_contribution_defaults_to_residual_when_none(self):
        amount = calculate_employee_contribution_amount(
            eligible_fee_total=Decimal("1200.00"),
            school_covered_amount=Decimal("840.00"),
            contribution_type=EmployeeContributionType.NONE,
            contribution_value=Decimal("0"),
        )
        self.assertEqual(amount, Decimal("360.00"))

    def test_equal_installment_amount(self):
        installment = calculate_equal_installment_amount(total_amount=Decimal("900.00"), installments=6)
        self.assertEqual(installment, Decimal("150.00"))

    def test_evaluate_deduction_limits_allowed_case(self):
        result = evaluate_deduction_limits(
            gross_pay=Decimal("2000.00"),
            existing_total_deductions=Decimal("1250.00"),
            proposed_deduction=Decimal("90.00"),
            max_deduction_percent_of_gross=Decimal("80"),
            min_net_pay_percent_of_gross=Decimal("30"),
        )
        self.assertTrue(result.is_allowed)
        self.assertEqual(result.allowed_amount, Decimal("90.00"))
        self.assertEqual(result.resulting_net_pay, Decimal("660.00"))

    def test_evaluate_deduction_limits_blocks_when_min_net_would_break(self):
        result = evaluate_deduction_limits(
            gross_pay=Decimal("2000.00"),
            existing_total_deductions=Decimal("1360.00"),
            proposed_deduction=Decimal("90.00"),
            max_deduction_percent_of_gross=Decimal("80"),
            min_net_pay_percent_of_gross=Decimal("30"),
        )
        self.assertFalse(result.is_allowed)
        self.assertEqual(result.allowed_amount, Decimal("40.00"))
        self.assertEqual(result.reason, "violates_min_net_pay")

    @patch("payroll_v2.obligation_services._active_periodic_obligation_totals")
    @patch("payroll_v2.obligation_services.resolve_employee_reference_gross_salary")
    @patch("payroll_v2.obligation_services._active_salary_advance_committed_amount")
    def test_salary_advance_can_borrow_unused_ward_allocation(
        self,
        committed_mock,
        gross_salary_mock,
        active_totals_mock,
    ):
        committed_mock.return_value = Decimal("0.00")
        gross_salary_mock.return_value = Decimal("1000.00")
        active_totals_mock.return_value = {
            "ward": Decimal("0.00"),
            "salary_advance": Decimal("150.00"),
            "other": Decimal("0.00"),
        }
        settings = SimpleNamespace(
            maximum_ward_sponsorship_deduction_percent=Decimal("40"),
            maximum_salary_advance_deduction_percent=Decimal("20"),
            tax_reserve_percent=Decimal("20"),
            minimum_take_home_pay_percent=Decimal("30"),
        )

        result = evaluate_employee_obligation_eligibility(
            employee=SimpleNamespace(id="emp-1"),
            payroll_settings=settings,
            obligation_type=DeductionSourceType.SALARY_ADVANCE,
            requested_periodic_deduction=Decimal("300.00"),
        )

        self.assertTrue(result["is_eligible"])
        self.assertEqual(result["max_additional_allowed"], "450.00")
        self.assertTrue(result["breakdown"]["can_borrow_ward_allocation"])
        self.assertEqual(result["maximum_allowed_amount"], "600.00")
        self.assertEqual(result["available_to_request_amount"], "600.00")

    @patch("payroll_v2.obligation_services._active_periodic_obligation_totals")
    @patch("payroll_v2.obligation_services.resolve_employee_reference_gross_salary")
    @patch("payroll_v2.obligation_services._active_salary_advance_committed_amount")
    def test_salary_advance_request_amount_blocked_by_committed_capacity(
        self,
        committed_mock,
        gross_salary_mock,
        active_totals_mock,
    ):
        committed_mock.return_value = Decimal("500.00")
        gross_salary_mock.return_value = Decimal("1000.00")
        active_totals_mock.return_value = {
            "ward": Decimal("0.00"),
            "salary_advance": Decimal("150.00"),
            "other": Decimal("0.00"),
        }
        settings = SimpleNamespace(
            maximum_ward_sponsorship_deduction_percent=Decimal("40"),
            maximum_salary_advance_deduction_percent=Decimal("20"),
            tax_reserve_percent=Decimal("20"),
            minimum_take_home_pay_percent=Decimal("30"),
        )

        result = evaluate_employee_obligation_eligibility(
            employee=SimpleNamespace(id="emp-1"),
            payroll_settings=settings,
            obligation_type=DeductionSourceType.SALARY_ADVANCE,
            requested_amount=Decimal("900.00"),
            requested_installments=2,
        )

        self.assertFalse(result["is_eligible"])
        self.assertEqual(result["maximum_allowed_amount"], "600.00")
        self.assertEqual(result["already_committed_amount"], "500.00")
        self.assertEqual(result["available_to_request_amount"], "100.00")

    @patch("payroll_v2.obligation_services._active_periodic_obligation_totals")
    @patch("payroll_v2.obligation_services.resolve_employee_reference_gross_salary")
    @patch("payroll_v2.obligation_services._active_salary_advance_committed_amount")
    def test_salary_advance_active_ward_uses_remaining_ward_allocation(
        self,
        committed_mock,
        gross_salary_mock,
        active_totals_mock,
    ):
        committed_mock.return_value = Decimal("250.00")
        gross_salary_mock.return_value = Decimal("7000.00")
        active_totals_mock.return_value = {
            "ward": Decimal("1400.00"),
            "salary_advance": Decimal("300.00"),
            "other": Decimal("0.00"),
        }
        settings = SimpleNamespace(
            maximum_ward_sponsorship_deduction_percent=Decimal("40"),
            maximum_salary_advance_deduction_percent=Decimal("15"),
            tax_reserve_percent=Decimal("20"),
            minimum_take_home_pay_percent=Decimal("30"),
        )

        result = evaluate_employee_obligation_eligibility(
            employee=SimpleNamespace(id="emp-1"),
            payroll_settings=settings,
            obligation_type=DeductionSourceType.SALARY_ADVANCE,
            requested_amount=Decimal("2000.00"),
            requested_installments=6,
        )

        self.assertTrue(result["is_eligible"])
        self.assertEqual(result["breakdown"]["maximum_salary_advance_capacity_percent"], "35.0000")
        self.assertEqual(result["maximum_allowed_amount"], "2450.00")
        self.assertEqual(result["available_to_request_amount"], "2200.00")

    @patch("payroll_v2.obligation_services._active_periodic_obligation_totals")
    @patch("payroll_v2.obligation_services.resolve_employee_reference_gross_salary")
    def test_ward_sponsorship_blocked_when_request_exceeds_room(
        self,
        gross_salary_mock,
        active_totals_mock,
    ):
        gross_salary_mock.return_value = Decimal("1000.00")
        active_totals_mock.return_value = {
            "ward": Decimal("150.00"),
            "salary_advance": Decimal("100.00"),
            "other": Decimal("100.00"),
        }
        settings = SimpleNamespace(
            maximum_ward_sponsorship_deduction_percent=Decimal("40"),
            maximum_salary_advance_deduction_percent=Decimal("20"),
            tax_reserve_percent=Decimal("20"),
            minimum_take_home_pay_percent=Decimal("30"),
        )

        result = evaluate_employee_obligation_eligibility(
            employee=SimpleNamespace(id="emp-1"),
            payroll_settings=settings,
            obligation_type=DeductionSourceType.STAFF_WARD_SPONSORSHIP,
            requested_periodic_deduction=Decimal("300.00"),
        )

        self.assertFalse(result["is_eligible"])
        self.assertGreater(len(result["reasons"]), 0)
