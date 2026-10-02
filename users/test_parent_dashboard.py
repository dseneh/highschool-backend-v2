from contextlib import nullcontext
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock, patch
from django.test import SimpleTestCase
from users.parent_views import parent_dashboard_snapshot


class ParentDashboardSnapshotTests(SimpleTestCase):
    def test_snapshot_uses_destination_parent_role_and_respects_revoked_permissions(self):
        user = SimpleNamespace(_active_role_selection="staff-role")
        student = SimpleNamespace(date_of_birth=date(2010, 5, 3), enrollments=Mock())
        student.enrollments.filter.return_value.select_related.return_value.first.return_value = object()
        assignment = SimpleNamespace(pk="parent-role")
        context = Mock()
        context.permission_scope.return_value = None
        with patch("users.parent_views.schema_context", return_value=nullcontext()), patch("authorization.runtime.resolve_authorization_context", return_value=context) as resolve, patch("finance.models.get_student_payment_plan") as plan, patch("users.parent_views.parent_communications") as messages:
            snapshot = parent_dashboard_snapshot(user, SimpleNamespace(tenant=SimpleNamespace(schema_name="school-two")), SimpleNamespace(student=student), assignment)
        self.assertEqual(resolve.call_args.args[0]._active_role_selection, "parent-role")
        self.assertEqual(user._active_role_selection, "staff-role")
        self.assertEqual(snapshot, {"birthday": {"month": 5, "day": 3}, "tuition": None, "announcements": []})
        plan.assert_not_called()
        messages.assert_not_called()

    def test_only_outstanding_installments_and_delivered_messages_are_returned(self):
        student = SimpleNamespace(date_of_birth=None, enrollments=Mock())
        context = Mock()
        context.permission_scope.return_value = "own"
        with patch("users.parent_views.schema_context", return_value=nullcontext()), patch("authorization.runtime.resolve_authorization_context", return_value=context), patch("finance.models.get_student_payment_plan", return_value=[{"id": "paid", "balance": 0}, {"id": "due", "balance": 25}]), patch("users.parent_views.parent_communications", return_value=[{"id": "delivered"}]):
            snapshot = parent_dashboard_snapshot(SimpleNamespace(), SimpleNamespace(tenant=SimpleNamespace(schema_name="school")), SimpleNamespace(student=student), SimpleNamespace(pk="parent"))
        self.assertEqual(snapshot["tuition"], [{"id": "due", "balance": 25}])
        self.assertEqual(snapshot["announcements"], [{"id": "delivered"}])


class ParentStudentReadPolicyTests(SimpleTestCase):
    def test_enrollment_summary_omits_billing_when_parent_permission_is_removed(self):
        from students.serializers.enrollment import EnrollmentListSerializer
        request = SimpleNamespace(user=object())
        instance = SimpleNamespace(
            student=SimpleNamespace(id_number="91001"),
            section=SimpleNamespace(id="section", name="A"),
            grade_level=SimpleNamespace(id="grade", name="Grade 1"),
            year_end_outcome=None,
            next_grade_level=None,
            academic_year=SimpleNamespace(id="year", name="2026", start_date=None, end_date=None, current=True),
        )
        serializer = EnrollmentListSerializer(context={"request": request})
        with patch("rest_framework.serializers.ModelSerializer.to_representation", return_value={}), patch.object(serializer, "_resolve_duration", return_value=180), patch("authorization.services.get_assigned_role", return_value=SimpleNamespace(system_key="parent")), patch("students.authorization.permission_scope", return_value=None), patch("students.serializers.enrollment.get_enrollment_bill_summary") as billing:
            result = serializer.to_representation(instance)
        self.assertNotIn("billing_summary", result)
        billing.assert_not_called()

    def check(self, method="GET", module="students.views.student", name="StudentDetailView", owned=True, query=None):
        from users.parent_student_access import parent_student_read_allowed
        view = type(name, (), {"__module__": module})()
        view.kwargs = {"id": "91001", "student_id": "91001"}
        request = SimpleNamespace(method=method, user=object(), query_params=query or {})
        guardians = Mock()
        guardians.filter.return_value.exists.return_value = owned
        with patch("students.authorization.permission_scope", return_value="own"), patch("users.parent_portal.verified_guardians", return_value=guardians):
            return parent_student_read_allowed(request, view)

    def test_student_read_requires_ownership_and_all_mutations_remain_denied(self):
        from rest_framework.exceptions import NotFound
        self.assertTrue(self.check())
        with self.assertRaises(NotFound):
            self.check(owned=False)
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            self.assertFalse(self.check(method=method))
        self.assertFalse(self.check(name="StudentListView"))
        self.assertFalse(self.check(module="hr.views.employee", name="EmployeeListView"))

    def test_draft_grades_and_full_admin_reports_remain_denied(self):
        self.assertTrue(self.check(module="grading.views.final_grades", name="StudentFinalGradesView"))
        self.assertFalse(self.check(module="grading.views.final_grades", name="StudentFinalGradesView", query={"status": "any"}))
        self.assertFalse(self.check(module="reports.views.students", name="StudentIndividualReportView", query={"report_type": "full"}))
        self.assertTrue(self.check(module="reports.views.students", name="StudentIndividualReportView", query={"report_type": "bio"}))


class ParentTuitionCalculationTests(SimpleTestCase):
    def plan(self, paid):
        from decimal import Decimal
        from finance.models import get_student_payment_plan
        year = SimpleNamespace(id="year")
        enrollment = SimpleNamespace(id="enrollment", academic_year=year)
        installments = [
            {"id": "first", "due_date": date(2020, 1, 1), "percentage": Decimal("50")},
            {"id": "second", "due_date": date(2040, 2, 1), "percentage": Decimal("25")},
            {"id": "third", "due_date": date(2040, 3, 1), "percentage": Decimal("25")},
        ]
        with patch("finance.models._get_net_total_bills_for_enrollment", return_value=Decimal("1000")), patch("finance.models._get_effective_paid_for_enrollment", return_value=Decimal(paid)), patch("finance.models._get_installments_for_academic_year", return_value=installments), patch("django.core.cache.cache.set"):
            return get_student_payment_plan(enrollment)

    def test_partial_payment_reduces_oldest_installments_first(self):
        rows = self.plan("600")
        self.assertEqual([row["balance"] for row in rows], [0, 150, 250])
        self.assertEqual(sum(row["balance"] for row in rows), 400)
        self.assertEqual(rows[1]["payment_date"], "2040-02-01")

    def test_fully_paid_and_overpaid_accounts_have_no_outstanding_schedule(self):
        for paid in ("1000", "1200"):
            with self.subTest(paid=paid):
                self.assertEqual(self.plan(paid), [])
