from datetime import date
from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.core.exceptions import ValidationError as DjangoValidationError
from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError

from academics.models import AcademicYear, GradeLevel
from accounting.models import AccountingCurrency
from budgeting.access_policies import BudgetAccessPolicy
from budgeting.models import (
    Budget, BudgetLine, BudgetLinePeriod, BudgetRevision, BudgetSection,
)
from budgeting.serializers import BudgetLineSerializer
from budgeting.services import (
    actuals_by_account, add_projected_student_revenue, budget_summary_payload, build_budget_report,
    comprehensive_budget_details,
    prior_year_baseline, projection_payload, student_receivables_metrics,
    validate_budget_for_submission,
)
from budgeting.views import BudgetViewSet
from users.access_policies.permissions import PRIVILEGES
from users.models import User


class BudgetModelRuleTests(SimpleTestCase):
    def test_budget_requires_regular_year_and_base_currency(self):
        year = AcademicYear(name="History", year_type=AcademicYear.YearType.HISTORICAL)
        currency = AccountingCurrency(code="USD", name="US Dollar", symbol="$", is_base_currency=False)
        budget = Budget(academic_year=year, base_currency=currency, name="Annual")

        with self.assertRaises(DjangoValidationError) as error:
            budget.clean()

        self.assertIn("academic_year", error.exception.message_dict)
        self.assertIn("base_currency", error.exception.message_dict)

    def test_approved_budget_requires_gl_accounts_but_submission_does_not(self):
        class FakeQuerySet(list):
            def select_related(self, *args):
                return self

            def exists(self):
                return bool(self)

        line = SimpleNamespace(
            name="Tuition", gl_account_id=None, section=SimpleNamespace(section_type="revenue"),
            periods=MagicMock(), annual_planned_amount=Decimal("100.00"),
        )
        line.periods.exists.return_value = False
        queryset = FakeQuerySet([line])

        with patch("budgeting.services.BudgetLine.objects.filter", return_value=queryset):
            validate_budget_for_submission(SimpleNamespace())
            with self.assertRaises(DjangoValidationError):
                validate_budget_for_submission(SimpleNamespace(), require_gl_accounts=True)

    @patch("budgeting.models.BudgetLinePeriod.objects.filter")
    def test_budget_line_periods_cannot_overlap(self, mock_filter):
        year = AcademicYear(
            name="2025/26", year_type=AcademicYear.YearType.REGULAR,
            start_date=date(2025, 9, 1), end_date=date(2026, 6, 30),
        )
        currency = AccountingCurrency(
            code="USD", name="US Dollar", symbol="$", is_base_currency=True,
        )
        budget = Budget(academic_year=year, base_currency=currency, name="Annual")
        section = BudgetSection(budget=budget, name="Revenue", section_type="revenue")
        line = BudgetLine(section=section, name="Tuition")
        period = BudgetLinePeriod(
            line=line, start_date=date(2025, 9, 1), end_date=date(2025, 9, 30),
            planned_amount=Decimal("100.00"),
        )
        mock_filter.return_value.exists.return_value = True

        with self.assertRaisesMessage(DjangoValidationError, "cannot overlap"):
            period.clean()

    def test_line_serializer_effective_amount_uses_only_approved_revisions(self):
        approved = SimpleNamespace(
            amount_delta=Decimal("25.00"),
            revision=SimpleNamespace(status=BudgetRevision.Status.APPROVED),
        )
        rejected = SimpleNamespace(
            amount_delta=Decimal("50.00"),
            revision=SimpleNamespace(status=BudgetRevision.Status.REJECTED),
        )
        line = SimpleNamespace(
            annual_planned_amount=Decimal("100.00"),
            revision_deltas=MagicMock(),
        )
        line.revision_deltas.all.return_value = [approved, rejected]

        amount = BudgetLineSerializer().get_effective_planned_amount(line)

        self.assertEqual(amount, Decimal("125.00"))


class BudgetImmutabilityAndPolicyTests(SimpleTestCase):
    def test_non_draft_structural_data_requires_revision(self):
        view = BudgetViewSet()
        with self.assertRaises(ValidationError):
            view._ensure_editable(Budget(status=Budget.Status.APPROVED))

    def test_policy_is_restricted_to_finance_roles_or_explicit_privileges(self):
        serialized = str(BudgetAccessPolicy.statements)
        self.assertIn("superadmin,admin,accountant", serialized)
        self.assertIn("BUDGET_VIEW", serialized)
        self.assertIn("BUDGET_MANAGE", serialized)
        self.assertIn("BUDGET_APPROVE", serialized)
        self.assertNotIn("anonymous", serialized)

    def test_budget_privileges_are_registered(self):
        self.assertEqual(
            {"BUDGET_VIEW", "BUDGET_MANAGE", "BUDGET_APPROVE"},
            {code for code in PRIVILEGES if code.startswith("BUDGET_")},
        )

    def test_superadmin_satisfies_budget_role_condition(self):
        policy = BudgetAccessPolicy()
        request = SimpleNamespace(user=SimpleNamespace(
            is_authenticated=True, role="superadmin", is_superuser=False
        ))

        self.assertTrue(policy.is_role_in(request, None, "get", "admin,accountant"))


class BudgetPlanningApiTests(SimpleTestCase):
    @patch("budgeting.views.transaction.atomic")
    @patch("budgeting.views.BudgetSection.objects.create")
    def test_new_budget_gets_ready_to_use_revenue_and_expense_sections(
        self, mock_create, mock_atomic,
    ):
        mock_atomic.return_value.__enter__.return_value = None
        serializer = MagicMock()
        serializer.save.return_value = Budget(name="2025/26 Budget")
        view = BudgetViewSet()
        view.request = SimpleNamespace(user=User())

        view.perform_create(serializer)

        sections = [call.kwargs for call in mock_create.call_args_list]
        self.assertEqual([section["name"] for section in sections], ["Revenue", "Operating Expenses"])
        self.assertEqual(
            [section["section_type"] for section in sections],
            [BudgetSection.SectionType.REVENUE, BudgetSection.SectionType.EXPENSE],
        )

    def test_bulk_enrollment_requires_a_rows_list(self):
        view = BudgetViewSet()
        view.request = SimpleNamespace(data={})
        view.get_object = MagicMock(return_value=Budget(status=Budget.Status.DRAFT))

        with self.assertRaises(ValidationError) as error:
            view.bulk_enrollment_assumptions(view.request)

        self.assertIn("rows", error.exception.detail)

    @patch("budgeting.views.GradeLevel.objects.filter")
    def test_bulk_enrollment_validates_editable_previous_year_values(self, mock_filter):
        grade = GradeLevel(id=uuid4(), name="Grade 1", level=1)
        mock_filter.return_value = [grade]
        view = BudgetViewSet()
        view.request = SimpleNamespace(data={
            "rows": [{
                "grade_level": str(grade.id),
                "estimated_students": 50,
                "prior_actual_students": -1,
            }],
        })
        view.get_object = MagicMock(return_value=Budget(status=Budget.Status.DRAFT))

        with self.assertRaises(ValidationError) as error:
            view.bulk_enrollment_assumptions(view.request)

        self.assertIn("rows", error.exception.detail)


class BudgetActualAndReportTests(SimpleTestCase):
    @patch("budgeting.services.AccountingJournalLine.objects.filter")
    def test_actuals_use_posted_journal_lines_and_preserve_decimals(self, mock_filter):
        queryset = mock_filter.return_value
        queryset.values.return_value.annotate.return_value = [
            {"ledger_account_id": "income", "net_debit": Decimal("-125.25")},
            {"ledger_account_id": "expense", "net_debit": Decimal("40.10")},
        ]
        budget = SimpleNamespace(
            academic_year=SimpleNamespace(start_date=date(2025, 9, 1), end_date=date(2026, 6, 30))
        )

        result = actuals_by_account(budget)

        self.assertEqual(result["income"], Decimal("-125.25"))
        self.assertEqual(result["expense"], Decimal("40.10"))
        filters = mock_filter.call_args.kwargs
        self.assertEqual(filters["journal_entry__status"], "posted")
        self.assertIs(filters["journal_entry__academic_year"], budget.academic_year)
        self.assertEqual(filters["journal_entry__posting_date__range"], (date(2025, 9, 1), date(2026, 6, 30)))

    @patch("budgeting.services.effective_planned_amounts")
    @patch("budgeting.services.actuals_by_account")
    def test_summary_uses_credit_revenue_debit_expense_and_revision_delta(self, mock_actuals, mock_lines):
        year = SimpleNamespace(id="year", start_date=date(2025, 9, 1), end_date=date(2026, 6, 30))
        budget = SimpleNamespace(
            id="budget", name="Annual", academic_year=year, academic_year_id="year",
            base_currency=SimpleNamespace(code="USD"),
        )
        revenue = SimpleNamespace(
            id="r", name="Tuition", annual_planned_amount=Decimal("100.00"), approved_delta=Decimal("10.00"),
            source_type="fee_rate", periods=MagicMock(),
            gl_account_id="income", gl_account=SimpleNamespace(code="4000"),
            section=SimpleNamespace(name="Revenue", section_type="revenue"),
        )
        expense = SimpleNamespace(
            id="e", name="Payroll", annual_planned_amount=Decimal("80.00"), approved_delta=Decimal("0.00"),
            source_type="payroll", periods=MagicMock(),
            gl_account_id="expense", gl_account=SimpleNamespace(code="5000"),
            section=SimpleNamespace(name="Expense", section_type="expense"),
        )
        mock_lines.return_value = [revenue, expense]
        revenue.periods.all.return_value = []
        expense.periods.all.return_value = []
        mock_actuals.return_value = {"income": Decimal("-125.00"), "expense": Decimal("70.00")}

        payload = budget_summary_payload(budget)

        self.assertEqual(payload["summary"]["actual_revenue"], Decimal("125.00"))
        self.assertEqual(payload["summary"]["actual_expense"], Decimal("70.00"))
        self.assertEqual(payload["results"][0]["planned_amount"], Decimal("110.00"))
        self.assertEqual(payload["results"][0]["variance_amount"], Decimal("15.00"))

    @patch("budgeting.services.effective_planned_amounts")
    @patch("budgeting.services.actuals_by_account", return_value={})
    def test_partial_report_prorates_overlapping_budget_period_by_days(self, _mock_actuals, mock_lines):
        year = SimpleNamespace(
            id="year", start_date=date(2025, 9, 1), end_date=date(2026, 6, 30)
        )
        period = SimpleNamespace(
            start_date=date(2026, 1, 1), end_date=date(2026, 1, 31),
            planned_amount=Decimal("310.00"),
        )
        line = SimpleNamespace(
            id="line", name="Tuition", annual_planned_amount=Decimal("310.00"),
            approved_delta=Decimal("31.00"), source_type="fee_rate",
            periods=MagicMock(), gl_account_id=None, gl_account=None,
            section=SimpleNamespace(name="Revenue", section_type="revenue"),
        )
        line.periods.all.return_value = [period]
        mock_lines.return_value = [line]
        budget = SimpleNamespace(
            id="budget", name="Annual", academic_year=year, academic_year_id="year",
            base_currency=SimpleNamespace(code="USD"),
        )

        payload = budget_summary_payload(
            budget, date(2026, 1, 1), date(2026, 1, 15)
        )

        self.assertEqual(payload["results"][0]["planned_amount"], Decimal("165.00"))

    @patch("budgeting.services.projection_payload")
    def test_comprehensive_details_include_plan_enrollment_staffing_and_amendments(
        self, mock_projection
    ):
        line = SimpleNamespace(
            id="line", name="Tuition", source_type="fee_rate", source_ref="rates",
            annual_planned_amount=Decimal("100.00"), gl_account=None,
        )
        line.periods = MagicMock()
        line.periods.all.return_value = []
        section = SimpleNamespace(
            id="section", name="Revenue", section_type="revenue", lines=MagicMock()
        )
        section.lines.all.return_value = [line]
        line.section = section
        delta = SimpleNamespace(
            budget_line_id="line", budget_line=line, amount_delta=Decimal("10.00"),
            rationale="Updated enrollment",
        )
        revision = SimpleNamespace(
            number=1, status=BudgetRevision.Status.APPROVED, reason="Enrollment changed",
            approved_at=None, approved_by=None, line_deltas=MagicMock(),
        )
        revision.line_deltas.all.return_value = [delta]
        assumption = SimpleNamespace(
            grade_level_id="g1", grade_level=SimpleNamespace(name="Grade 1"), student_category="",
            prior_actual_students=20, estimated_students=24,
        )
        budget = SimpleNamespace(
            name="Annual", status="approved", version=2, is_original=True,
            notes="Plan notes", academic_year=SimpleNamespace(
                start_date=date(2025, 9, 1), end_date=date(2026, 6, 30),
                __str__=lambda self: "2025/26",
            ),
            base_currency=SimpleNamespace(code="USD"), submitted_at=None,
            submitted_by=None, approved_at=None, approved_by=None, activated_at=None,
            activated_by=None, closed_at=None, closed_by=None,
            created_at=date(2025, 8, 1), updated_at=date(2025, 8, 2),
            sections=MagicMock(), revisions=MagicMock(),
            enrollment_assumptions=MagicMock(), lifecycle_events=MagicMock(),
        )
        budget.sections.all.return_value = [section]
        budget.revisions.all.return_value = [revision]
        budget.enrollment_assumptions.all.return_value = [assumption]
        budget.lifecycle_events.all.return_value = []
        mock_projection.return_value = {
            "summary": {
                "estimated_students": 24, "actual_students": 22,
                "tuition_projection": Decimal("2400.00"),
                "other_student_fee_projection": Decimal("240.00"),
                "student_fee_projection": Decimal("2640.00"),
            },
            "results": [
                {
                    "projection_type": "enrollment_fees", "grade_level_id": "g1",
                    "grade_level": "Grade 1",
                    "student_category": "", "headcount": 24, "actual_headcount": 22,
                    "headcount_variance": -2,
                    "projected_tuition_amount": Decimal("2400.00"),
                    "projected_other_fee_amount": Decimal("240.00"),
                    "projected_amount": Decimal("2640.00"),
                },
                {
                    "projection_type": "payroll", "headcount": 12,
                    "projected_amount": Decimal("60000.00"),
                },
            ],
            "definitions": {
                "enrollment": "Current enrollment.", "fees": "Fee rates.",
                "tuition": "Grade tuition.", "setup": "Academic setup.",
                "payroll": "Effective-dated compensation.",
            },
        }
        summary = {
            "results": [{
                "line_id": "line", "source_type": "fee_rate",
                "planned_amount": Decimal("110.00"), "actual_amount": Decimal("90.00"),
                "variance_amount": Decimal("-20.00"), "variance_percentage": Decimal("-18.18"),
            }],
            "context": {"start_date": "2025-09-01", "end_date": "2026-06-30"},
            "definitions": {"planned": "Effective plan."},
        }

        details = comprehensive_budget_details(budget, summary)

        self.assertEqual(details["sections"][0]["lines"][0]["effective_amount"], Decimal("110.00"))
        self.assertEqual(details["enrollment"][0]["estimated_students"], 24)
        self.assertEqual(details["workforce"]["compensation_covered_employees"], 12)
        self.assertFalse(details["workforce"]["staffing_plan_available"])
        self.assertEqual(details["revisions"][0]["line_deltas"][0]["amount_delta"], Decimal("10.00"))

        summary["summary"] = {
            "planned_revenue": Decimal("110.00"),
            "actual_revenue": Decimal("90.00"),
            "planned_expense": Decimal("50.00"),
            "actual_surplus": Decimal("40.00"),
        }
        add_projected_student_revenue(summary, details)
        self.assertEqual(summary["summary"]["projected_student_tuition"], Decimal("2400.00"))
        self.assertEqual(summary["summary"]["projected_class_section_fees"], Decimal("240.00"))
        self.assertEqual(summary["summary"]["planned_revenue"], Decimal("2750.00"))
        self.assertEqual(summary["summary"]["planned_surplus"], Decimal("2700.00"))

    @patch("budgeting.services.budget_summary_payload")
    def test_canonical_report_filters_same_payload_without_recalculating_totals(self, mock_summary):
        canonical = {
            "summary": {
                "planned_revenue": Decimal("10.00"),
                "actual_revenue": Decimal("12.00"),
                "revenue_variance": Decimal("2.00"),
                "revenue_performance_percentage": Decimal("120.00"),
                "planned_expense": Decimal("8.00"),
                "actual_expense": Decimal("13.00"),
                "expense_variance": Decimal("-5.00"),
                "planned_surplus": Decimal("2.00"),
                "actual_surplus": Decimal("-1.00"),
                "surplus_variance": Decimal("-3.00"),
            },
            "results": [
                {"section_type": "revenue", "variance_amount": Decimal("2.00")},
                {"section_type": "expense", "variance_amount": Decimal("-5.00")},
            ],
            "count": 2, "context": {}, "definitions": {},
        }
        mock_summary.side_effect = lambda *args, **kwargs: deepcopy(canonical)

        revenue = build_budget_report(SimpleNamespace(), "revenue-performance")
        variance = build_budget_report(SimpleNamespace(), "variance-analysis")

        self.assertEqual(revenue["summary"]["planned_revenue"], Decimal("10.00"))
        self.assertEqual(set(revenue["summary"]), {
            "planned_revenue", "actual_revenue", "revenue_variance",
            "revenue_performance_percentage",
        })
        self.assertEqual(revenue["count"], 1)
        self.assertEqual(variance["results"][0]["variance_amount"], Decimal("-5.00"))
        self.assertEqual(set(variance["summary"]), {
            "revenue_variance", "expense_variance", "planned_surplus",
            "actual_surplus", "surplus_variance",
        })


class BudgetBaselineAndProjectionTests(SimpleTestCase):
    @patch("budgeting.services.Enrollment.objects.filter")
    @patch("budgeting.services.actuals_by_account_for_year")
    @patch("budgeting.services.effective_planned_amounts")
    @patch("budgeting.services.AcademicYear.objects.filter")
    def test_baseline_uses_immediately_preceding_year_and_current_gl_mapping_without_prior_budget(
        self, mock_year_filter, mock_lines, mock_actuals, mock_enrollments
    ):
        previous_year = SimpleNamespace(
            id="prior-year", name="2024/25",
            start_date=date(2024, 9, 1), end_date=date(2025, 6, 30),
        )
        mock_year_filter.return_value.order_by.return_value.first.return_value = previous_year
        line = SimpleNamespace(
            id="line", name="Tuition", annual_planned_amount=Decimal("150.00"),
            approved_delta=Decimal("10.00"), gl_account_id="income",
            gl_account=SimpleNamespace(code="4000"),
            section=SimpleNamespace(name="Revenue", section_type="revenue"),
        )
        mock_lines.return_value = [line]
        mock_actuals.return_value = {"income": Decimal("-125.00")}
        enrollment_query = mock_enrollments.return_value.values.return_value.annotate.return_value.order_by.return_value
        enrollment_query.__iter__.return_value = iter([
            {"grade_level_id": "g1", "grade_level__name": "Grade 1", "actual_students": 22}
        ])
        budget = SimpleNamespace(
            id="budget", academic_year_id="current-year",
            academic_year=SimpleNamespace(start_date=date(2025, 9, 1)),
            base_currency=SimpleNamespace(code="USD"),
        )

        payload = prior_year_baseline(budget)

        mock_lines.assert_called_once_with(budget, include_periods=False)
        mock_actuals.assert_called_once_with(previous_year, account_ids={"income"})
        self.assertEqual(payload["results"][0]["prior_actual_amount"], Decimal("125.00"))
        self.assertEqual(payload["summary"]["prior_enrollment_actual"], 22)
        self.assertEqual(payload["context"]["prior_academic_year_id"], "prior-year")
        self.assertNotIn("prior_budget_id", payload["context"])

    @patch("budgeting.services.EmployeeCompensation.objects.filter")
    @patch("budgeting.services.Enrollment.objects.filter")
    @patch("budgeting.services.SectionFee.objects.filter")
    @patch("budgeting.services.Section.objects.filter")
    @patch("budgeting.services.GradeLevelTuitionFee.objects.filter")
    @patch("budgeting.services.GradeLevel.objects.filter")
    def test_projection_uses_grade_tuition_and_average_active_section_fees(
        self, mock_grades, mock_tuitions, mock_sections, mock_section_fees,
        mock_enrollments, mock_compensations,
    ):
        tuition = SimpleNamespace(
            grade_level_id="g1", targeted_student_type="returning",
            amount=Decimal("100.00"),
        )
        mock_tuitions.return_value.order_by.return_value = [tuition]
        mock_sections.return_value.values.return_value = [
            {"id": "s1", "grade_level_id": "g1"},
            {"id": "s2", "grade_level_id": "g1"},
        ]
        section_fees = [
            SimpleNamespace(
                section_id=section_id,
                amount=amount,
                general_fee=SimpleNamespace(student_target=""),
            )
            for section_id, amount in (
                ("s1", Decimal("20.00")),
                ("s2", Decimal("30.00")),
            )
        ]
        mock_section_fees.return_value.select_related.return_value = section_fees
        enrollment_rows = mock_enrollments.return_value.values.return_value.annotate.return_value
        enrollment_rows.__iter__.return_value = iter([
            {"grade_level_id": "g1", "enrolled_as": "new", "actual_students": 2}
        ])
        mock_compensations.return_value.filter.return_value = []
        assumption = SimpleNamespace(
            grade_level_id="g1", grade_level=SimpleNamespace(id="g1", name="Grade 1"),
            student_category="", estimated_students=3,
        )
        mock_grades.return_value.order_by.return_value = [assumption.grade_level]
        assumptions = MagicMock()
        assumptions.select_related.return_value = [assumption]
        year = SimpleNamespace(
            start_date=date(2025, 9, 1), end_date=date(2026, 6, 30)
        )
        budget = SimpleNamespace(
            id="budget", academic_year_id="year", academic_year=year,
            base_currency=SimpleNamespace(code="USD"),
            enrollment_assumptions=assumptions,
        )

        payload = projection_payload(budget)

        self.assertEqual(payload["summary"]["student_fee_projection"], Decimal("375.00"))
        self.assertEqual(payload["summary"]["tuition_projection"], Decimal("300.00"))
        self.assertEqual(payload["summary"]["other_student_fee_projection"], Decimal("75.00"))
        self.assertEqual(payload["results"][0]["actual_headcount"], 2)
        self.assertEqual(payload["results"][0]["tuition_per_student"], Decimal("100.00"))
        self.assertEqual(payload["results"][0]["total_fees_per_student"], Decimal("125.00"))
        self.assertTrue(payload["results"][0]["setup_complete"])
        self.assertEqual(mock_enrollments.call_count, 1)
        self.assertTrue(mock_compensations.call_args.kwargs["is_active"])

    @patch("budgeting.services.AccountingCashTransaction.objects.annotate")
    @patch("budgeting.services.AccountingStudentPaymentAllocation.objects.filter")
    @patch("budgeting.services.AccountingStudentBillLine.objects.filter")
    @patch("budgeting.services.AccountingStudentBill.objects.filter")
    def test_receivables_metrics_use_tuition_bill_lines_current_ar_and_completed_cash_once(
        self, mock_bills, mock_bill_lines, mock_allocations, mock_cash
    ):
        valid_bills = mock_bills.return_value.exclude.return_value
        valid_bills.aggregate.return_value = {"total": Decimal("40.00")}
        mock_bill_lines.return_value.exclude.return_value.aggregate.return_value = {
            "total": Decimal("120.00")
        }
        mock_allocations.return_value.exclude.return_value = MagicMock()
        cash_query = mock_cash.return_value.filter.return_value.filter.return_value
        cash_query.aggregate.return_value = {"total": Decimal("90.00")}
        budget = SimpleNamespace(
            academic_year=SimpleNamespace(
                start_date=date(2025, 9, 1), end_date=date(2026, 6, 30)
            ),
            base_currency=SimpleNamespace(code="USD"),
        )

        metrics = student_receivables_metrics(
            budget, date(2026, 1, 1), date(2026, 1, 31)
        )

        self.assertEqual(metrics["actual_tuition_billed"], Decimal("120.00"))
        self.assertEqual(metrics["total_student_collections"], Decimal("90.00"))
        self.assertEqual(metrics["current_student_outstanding"], Decimal("40.00"))
        completed_filter = mock_cash.return_value.filter.call_args.kwargs
        self.assertEqual(completed_filter["status"], "completed")
        self.assertEqual(
            completed_filter["transaction_date__range"],
            (date(2026, 1, 1), date(2026, 1, 31)),
        )

    @patch("budgeting.services.student_receivables_metrics")
    @patch("budgeting.services.projection_payload")
    def test_tuition_report_has_exact_summary_and_explicit_collection_limitation(
        self, mock_projection, mock_receivables
    ):
        mock_projection.return_value = {
            "summary": {
                "student_fee_projection": Decimal("150.00"),
                "tuition_projection": Decimal("100.00"),
                "other_student_fee_projection": Decimal("50.00"),
                "payroll_projection": Decimal("0.00"),
            },
            "results": [{"projection_type": "enrollment_fees"}],
            "count": 1,
            "context": {},
            "definitions": {},
        }
        mock_receivables.return_value = {
            "actual_tuition_billed": Decimal("110.00"),
            "total_student_collections": Decimal("80.00"),
            "current_student_outstanding": Decimal("30.00"),
        }
        year = SimpleNamespace(start_date=date(2025, 9, 1), end_date=date(2026, 6, 30))
        budget = SimpleNamespace(academic_year=year)

        payload = build_budget_report(
            budget, "tuition-projection-vs-actual",
            date(2026, 1, 1), date(2026, 1, 31),
        )

        self.assertEqual(payload["summary"]["tuition_billing_variance"], Decimal("10.00"))
        self.assertNotIn("payroll_projection", payload["summary"])
        self.assertIn("not tuition-only", payload["definitions"]["total_student_collections"])
        self.assertEqual(payload["context"]["actual_start_date"], "2026-01-01")
