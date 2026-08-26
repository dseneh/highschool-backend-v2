from django_tenants.test.cases import TenantTestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from authorization.models import Role
from authorization.services import assign_user_role, replace_role_permissions
from students.access_policies import (
    AttendanceAccessPolicy,
    BillingAccessPolicy,
    HistoricalGradeAccessPolicy,
    StudentContactAccessPolicy,
    StudentDisciplineAccessPolicy,
    StudentGuardianAccessPolicy,
)
from students.views.attendance import AttendanceDetailView, AttendanceListView
from students.views.concession import StudentConcessionDetailView
from students.views.contact import StudentContactDetailView
from students.views.discipline import StudentDisciplinaryActionDetailView
from students.views.guardian import StudentGuardianDetailView
from students.views.historical_grade import (
    HistoricalGradeRecordDetailView,
    HistoricalGradeRecordVerifyView,
)
from students.views.student_bill import StudentEnrollmentBillListView
from users.models import User


class CrossDomainPermissionMatrixTests(TenantTestCase):
    @classmethod
    def get_test_schema_name(cls):
        return "cross_domain_rbac"

    @classmethod
    def get_test_tenant_domain(cls):
        return "cross-domain-rbac.tenant.test.com"

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.name = "Cross Domain RBAC Test School"
        tenant.id_number = "CDR001"
        tenant.owner, _ = User.objects.get_or_create(
            email="cross-domain-owner@example.com",
            defaults={
                "username": "cross-domain-owner",
                "id_number": "CROSS-DOMAIN-OWNER-001",
                "account_type": "staff",
            },
        )

    def setUp(self):
        super().setUp()
        self.factory = APIRequestFactory()
        self.user, _ = User.objects.get_or_create(
            email="cross-domain-user@example.com",
            defaults={
                "username": "cross-domain-user",
                "id_number": "CROSS-DOMAIN-USER-001",
                "account_type": "staff",
            },
        )
        self.tenant.add_user(self.user)
        self.role = Role.objects.create(name="Cross Domain Operator")
        assign_user_role(user=self.user, role=self.role, actor=self.tenant.owner)

    def assert_policy_result(self, policy, view_class, method, permission, expected):
        prerequisite = {
            "attendance.take": "attendance.view",
            "attendance.update": "attendance.view",
            "attendance.correct": "attendance.view",
            "billing.manage": "billing.view",
            "grades.enter": "grades.view",
            "grades.review": "grades.view",
            "grades.unlock": "grades.view",
            "students.contacts.manage": "students.contacts.view",
            "students.guardians.manage": "students.guardians.view",
            "students.discipline.manage": "students.discipline.view",
        }.get(permission)
        grants = {"students.view": "all", permission: "all"}
        if prerequisite:
            grants[prerequisite] = "all"
        replace_role_permissions(
            self.role,
            grants,
            actor=self.tenant.owner,
        )
        raw_request = getattr(self.factory, method)("/test/", {}, format="json")
        raw_request.tenant = self.tenant
        force_authenticate(raw_request, user=self.user)
        view = view_class()
        request = view.initialize_request(raw_request)
        request.tenant = self.tenant
        view.request = request

        self.assertEqual(policy().has_permission(request, view), expected)

    def test_attendance_view_does_not_grant_attendance_mutations(self):
        self.assert_policy_result(
            AttendanceAccessPolicy,
            AttendanceListView,
            "get",
            "attendance.view",
            True,
        )
        self.assert_policy_result(
            AttendanceAccessPolicy,
            AttendanceListView,
            "post",
            "attendance.view",
            False,
        )
        self.assert_policy_result(
            AttendanceAccessPolicy,
            AttendanceListView,
            "post",
            "attendance.take",
            True,
        )

    def test_attendance_correction_is_distinct_from_update(self):
        self.assert_policy_result(
            AttendanceAccessPolicy,
            AttendanceDetailView,
            "put",
            "attendance.update",
            True,
        )
        self.assert_policy_result(
            AttendanceAccessPolicy,
            AttendanceDetailView,
            "delete",
            "attendance.update",
            False,
        )
        self.assert_policy_result(
            AttendanceAccessPolicy,
            AttendanceDetailView,
            "delete",
            "attendance.correct",
            True,
        )

    def test_billing_view_does_not_grant_billing_management(self):
        self.assert_policy_result(
            BillingAccessPolicy,
            StudentEnrollmentBillListView,
            "get",
            "billing.view",
            True,
        )
        self.assert_policy_result(
            BillingAccessPolicy,
            StudentConcessionDetailView,
            "put",
            "billing.view",
            False,
        )
        self.assert_policy_result(
            BillingAccessPolicy,
            StudentConcessionDetailView,
            "put",
            "billing.manage",
            True,
        )

    def test_student_subdomains_require_their_own_permissions(self):
        cases = (
            (StudentContactAccessPolicy, StudentContactDetailView, "students.contacts.view"),
            (StudentGuardianAccessPolicy, StudentGuardianDetailView, "students.guardians.view"),
            (StudentDisciplineAccessPolicy, StudentDisciplinaryActionDetailView, "students.discipline.view"),
        )
        for policy, view_class, permission in cases:
            with self.subTest(permission=permission):
                self.assert_policy_result(policy, view_class, "get", permission, True)
                self.assert_policy_result(policy, view_class, "get", "students.view", False)

    def test_discipline_management_is_distinct_from_read_access(self):
        self.assert_policy_result(
            StudentDisciplineAccessPolicy,
            StudentDisciplinaryActionDetailView,
            "put",
            "students.discipline.view",
            False,
        )
        self.assert_policy_result(
            StudentDisciplineAccessPolicy,
            StudentDisciplinaryActionDetailView,
            "put",
            "students.discipline.manage",
            True,
        )

    def test_historical_grade_workflows_use_grading_permissions(self):
        self.assert_policy_result(
            HistoricalGradeAccessPolicy,
            HistoricalGradeRecordDetailView,
            "patch",
            "grades.enter",
            True,
        )
        self.assert_policy_result(
            HistoricalGradeAccessPolicy,
            HistoricalGradeRecordVerifyView,
            "post",
            "grades.enter",
            False,
        )
        self.assert_policy_result(
            HistoricalGradeAccessPolicy,
            HistoricalGradeRecordVerifyView,
            "post",
            "grades.review",
            True,
        )
