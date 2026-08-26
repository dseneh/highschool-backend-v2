from types import SimpleNamespace
from unittest.mock import Mock

from django.test import SimpleTestCase

from students.access_policies import (
    AttendanceAccessPolicy,
    BillingAccessPolicy,
    HistoricalGradeAccessPolicy,
    StudentContactAccessPolicy,
    StudentDisciplineAccessPolicy,
    StudentGuardianAccessPolicy,
)
from students.authorization import filter_students_for_view_scope
from students.views.attendance import (
    AttendanceDetailView,
    AttendanceListView,
    AttendanceSectionRosterView,
)
from students.views.bill_recreation import (
    BillRecreationPreviewView,
    BillRecreationStatusView,
    BillRecreationView,
)
from students.views.concession import (
    StudentConcessionDetailView,
    StudentConcessionListCreateView,
)
from students.views.contact import StudentContactDetailView, StudentContactListView
from students.views.discipline import (
    DisciplinaryActionTypeDetailView,
    DisciplinaryActionTypeListCreateView,
    StudentDisciplinaryActionByStudentListCreateView,
    StudentDisciplinaryActionDetailView,
    StudentDisciplinaryActionListCreateView,
)
from students.views.guardian import StudentGuardianDetailView, StudentGuardianListView
from students.views.distributions import _require_all_student_view_scope
from students.views.enrollment import EnrollmentDetailView, EnrollmentListView
from students.views.enrollment_lifecycle import (
    StudentCompleteYearView,
    StudentGraduateView,
    StudentTransferOutView,
)
from students.views.enrollment_lifecycle_bulk import (
    EnrollmentLifecycleBulkApplyView,
    EnrollmentLifecycleBulkPreviewView,
    EnrollmentLifecyclePromotedListView,
    EnrollmentLifecycleRulesView,
    EnrollmentLifecycleUndoView,
)
from students.views.student import (
    StudentImportStatusView,
    StudentImportView,
    StudentReinstateView,
    StudentWithdrawView,
)
from students.views.historical_grade import (
    HistoricalGradeRecordDetailView,
    HistoricalGradeRecordListView,
    HistoricalGradeRecordUnverifyView,
    HistoricalGradeRecordVerifyView,
)
from students.views.year_end_wizard import YearEndWizardApplyView, YearEndWizardView


class StudentPolicyActionMapTests(SimpleTestCase):
    def test_cross_domain_views_use_exact_permission_actions(self):
        expected = {
            AttendanceSectionRosterView: {"get": "get", "post": "take"},
            AttendanceListView: {"get": "get", "post": "take"},
            AttendanceDetailView: {"get": "get", "put": "update", "delete": "correct"},
            StudentConcessionListCreateView: {"get": "get", "post": "manage"},
            StudentConcessionDetailView: {"get": "get", "put": "manage", "delete": "manage"},
            BillRecreationView: {"post": "manage"},
            BillRecreationPreviewView: {"get": "manage"},
            BillRecreationStatusView: {"get": "manage"},
            HistoricalGradeRecordListView: {"get": "get", "post": "update"},
            HistoricalGradeRecordDetailView: {"get": "get", "patch": "update", "delete": "delete"},
            HistoricalGradeRecordVerifyView: {"post": "verify"},
            HistoricalGradeRecordUnverifyView: {"post": "unverify"},
            StudentContactListView: {"get": "get", "post": "manage"},
            StudentContactDetailView: {"get": "get", "put": "manage", "delete": "manage"},
            StudentGuardianListView: {"get": "get", "post": "manage"},
            StudentGuardianDetailView: {"get": "get", "put": "manage", "delete": "manage"},
            DisciplinaryActionTypeListCreateView: {"get": "get", "post": "manage"},
            DisciplinaryActionTypeDetailView: {"get": "get", "put": "manage", "delete": "manage"},
            StudentDisciplinaryActionListCreateView: {"get": "get", "post": "manage"},
            StudentDisciplinaryActionDetailView: {"get": "get", "put": "manage", "delete": "manage"},
            StudentDisciplinaryActionByStudentListCreateView: {"get": "get", "post": "manage"},
        }

        for view_class, action_map in expected.items():
            with self.subTest(view=view_class.__name__):
                self.assertEqual(view_class.policy_action_map, action_map)

    def test_cross_domain_policies_reference_domain_permissions(self):
        conditions = {
            policy.__name__: {
                condition
                for statement in policy.statements
                for condition in (
                    statement.get("condition")
                    if isinstance(statement.get("condition"), list)
                    else [statement.get("condition")]
                )
                if condition
            }
            for policy in (
                AttendanceAccessPolicy,
                BillingAccessPolicy,
                HistoricalGradeAccessPolicy,
                StudentContactAccessPolicy,
                StudentGuardianAccessPolicy,
                StudentDisciplineAccessPolicy,
            )
        }

        self.assertEqual(
            conditions["AttendanceAccessPolicy"],
            {
                "has_domain_permission:attendance.view",
                "has_domain_permission:attendance.take",
                "has_domain_permission:attendance.update",
                "has_domain_permission:attendance.correct",
            },
        )
        self.assertEqual(
            conditions["BillingAccessPolicy"],
            {
                "has_domain_permission:billing.view",
                "has_domain_permission:billing.manage",
            },
        )
        self.assertEqual(
            conditions["HistoricalGradeAccessPolicy"],
            {
                "has_domain_permission:grades.view",
                "has_domain_permission:grades.enter",
                "has_domain_permission:grades.review",
                "has_domain_permission:grades.unlock",
            },
        )
        self.assertEqual(
            conditions["StudentContactAccessPolicy"],
            {
                "has_domain_permission:students.contacts.view",
                "has_domain_permission:students.contacts.manage",
            },
        )
        self.assertEqual(
            conditions["StudentGuardianAccessPolicy"],
            {
                "has_domain_permission:students.guardians.view",
                "has_domain_permission:students.guardians.manage",
            },
        )
        self.assertEqual(
            conditions["StudentDisciplineAccessPolicy"],
            {
                "has_domain_permission:students.discipline.view",
                "has_domain_permission:students.discipline.manage",
            },
        )

    def test_lifecycle_and_import_views_use_exact_permission_actions(self):
        expected = {
            EnrollmentListView: {"get": "get", "post": "enroll"},
            EnrollmentDetailView: {"get": "get", "put": "enroll", "delete": "delete"},
            StudentCompleteYearView: {"post": "promote"},
            StudentGraduateView: {"post": "promote"},
            StudentTransferOutView: {"post": "transfer"},
            StudentWithdrawView: {"post": "withdraw"},
            StudentReinstateView: {"post": "update"},
            StudentImportView: {"post": "create_student"},
            StudentImportStatusView: {"get": "get", "delete": "create_student"},
            EnrollmentLifecycleRulesView: {"get": "promote"},
            EnrollmentLifecycleBulkPreviewView: {"post": "lifecycle"},
            EnrollmentLifecycleBulkApplyView: {"post": "lifecycle"},
            EnrollmentLifecyclePromotedListView: {"get": "promote"},
            EnrollmentLifecycleUndoView: {"post": "promote"},
            YearEndWizardView: {"post": "promote"},
            YearEndWizardApplyView: {"post": "promote"},
        }

        for view_class, action_map in expected.items():
            with self.subTest(view=view_class.__name__):
                self.assertEqual(view_class.policy_action_map, action_map)

    def test_unknown_student_scope_fails_closed(self):
        queryset = Mock()
        denied = Mock()
        queryset.none.return_value = denied
        request = SimpleNamespace(
            user=SimpleNamespace(id_number="USER-1"),
            permission_scope=Mock(return_value="unexpected"),
        )

        self.assertIs(filter_students_for_view_scope(queryset, request), denied)

    def test_school_wide_aggregates_require_all_scope(self):
        assigned_request = SimpleNamespace(
            user=SimpleNamespace(id_number="TEACHER-1"),
            permission_scope=Mock(return_value="assigned"),
        )
        all_request = SimpleNamespace(
            user=SimpleNamespace(id_number="ADMIN-1"),
            permission_scope=Mock(return_value="all"),
        )

        self.assertEqual(
            _require_all_student_view_scope(assigned_request).status_code,
            403,
        )
        self.assertIsNone(_require_all_student_view_scope(all_request))
