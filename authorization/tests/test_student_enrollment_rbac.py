from django_tenants.test.cases import TenantTestCase
from rest_framework.exceptions import PermissionDenied
from rest_framework.test import APIRequestFactory, force_authenticate

from authorization.models import Role, TenantMembership
from authorization.services import assign_user_role, replace_role_permissions
from students.access_policies import StudentAccessPolicy, StudentRecordAccessPolicy
from students.views.enrollment import EnrollmentListView
from students.views.enrollment_lifecycle_bulk import (
    EnrollmentLifecycleBulkPreviewView,
    _require_bulk_action_permission,
)
from students.views.student import StudentListView
from users.models import User


class StudentEnrollmentRBACTests(TenantTestCase):
    @classmethod
    def get_test_schema_name(cls):
        return "student_enrollment_rbac"

    @classmethod
    def get_test_tenant_domain(cls):
        return "student-enrollment-rbac.tenant.test.com"

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.name = "Student Enrollment RBAC Test School"
        tenant.id_number = "SER001"
        tenant.owner, _ = User.objects.get_or_create(
            email="student-enrollment-owner@example.com",
            defaults={
                "username": "student-enrollment-owner",
                "id_number": "STUDENT-ENROLLMENT-OWNER-001",
            },
        )

    def setUp(self):
        super().setUp()
        self.factory = APIRequestFactory()
        self.user, _ = User.objects.get_or_create(
            email="student-enrollment-user@example.com",
            defaults={
                "username": "student-enrollment-user",
                "id_number": "STUDENT-ENROLLMENT-USER-001",
            },
        )
        self.tenant.add_user(self.user)
        self.role = Role.objects.create(name="Enrollment Specialist")
        assign_user_role(user=self.user, role=self.role, actor=self.tenant.owner)

    def _policy_allows_enrollment(self):
        raw_request = self.factory.post("/students/student-1/enrollments/", {})
        raw_request.tenant = self.tenant
        force_authenticate(raw_request, user=self.user)
        view = EnrollmentListView()
        request = view.initialize_request(raw_request)
        request.tenant = self.tenant
        view.request = request
        return StudentAccessPolicy().has_permission(request, view)

    def _request_for_view(self, view, method, path, data=None):
        raw_request = getattr(self.factory, method)(path, data or {}, format="json")
        raw_request.tenant = self.tenant
        force_authenticate(raw_request, user=self.user)
        request = view.initialize_request(raw_request)
        request.tenant = self.tenant
        view.request = request
        return request

    def test_custom_role_with_students_enroll_can_post_enrollment(self):
        replace_role_permissions(
            self.role,
            {"students.view": "all", "students.enroll": "all"},
            actor=self.tenant.owner,
        )

        self.assertTrue(self._policy_allows_enrollment())

    def test_custom_role_without_students_enroll_cannot_post_enrollment(self):
        replace_role_permissions(
            self.role,
            {"students.view": "all"},
            actor=self.tenant.owner,
        )

        self.assertFalse(self._policy_allows_enrollment())

    def test_permission_replacement_invalidates_enrollment_access(self):
        replace_role_permissions(
            self.role,
            {"students.view": "all", "students.enroll": "all"},
            actor=self.tenant.owner,
        )
        self.assertTrue(self._policy_allows_enrollment())

        with self.captureOnCommitCallbacks(execute=True):
            replace_role_permissions(
                self.role,
                {"students.view": "all"},
                actor=self.tenant.owner,
            )

        self.assertFalse(self._policy_allows_enrollment())

    def test_other_custom_permission_uses_same_policy_pipeline(self):
        replace_role_permissions(
            self.role,
            {"students.view": "all", "students.delete": "all"},
            actor=self.tenant.owner,
        )

        raw_request = self.factory.delete("/students/student-1/enrollments/")
        raw_request.tenant = self.tenant
        force_authenticate(raw_request, user=self.user)
        view = EnrollmentListView()
        request = view.initialize_request(raw_request)
        request.tenant = self.tenant
        view.request = request

        self.assertTrue(StudentAccessPolicy().has_permission(request, view))

    def test_students_create_is_distinct_from_enrollment(self):
        replace_role_permissions(
            self.role,
            {"students.view": "all", "students.create": "all"},
            actor=self.tenant.owner,
        )
        view = StudentListView()
        request = self._request_for_view(view, "post", "/students/")

        self.assertTrue(StudentRecordAccessPolicy().has_permission(request, view))

        replace_role_permissions(
            self.role,
            {"students.view": "all", "students.enroll": "all"},
            actor=self.tenant.owner,
        )
        view = StudentListView()
        request = self._request_for_view(view, "post", "/students/")
        self.assertFalse(StudentRecordAccessPolicy().has_permission(request, view))

    def test_scoped_view_grant_is_required_for_student_reads(self):
        replace_role_permissions(
            self.role,
            {"students.view": "own"},
            actor=self.tenant.owner,
        )
        view = StudentListView()
        request = self._request_for_view(view, "get", "/students/")
        self.assertTrue(StudentRecordAccessPolicy().has_permission(request, view))

        replace_role_permissions(self.role, {}, actor=self.tenant.owner)
        view = StudentListView()
        request = self._request_for_view(view, "get", "/students/")
        self.assertFalse(StudentRecordAccessPolicy().has_permission(request, view))

    def test_bulk_lifecycle_permission_matches_requested_action(self):
        replace_role_permissions(
            self.role,
            {"students.view": "all", "students.promote": "all"},
            actor=self.tenant.owner,
        )
        view = EnrollmentLifecycleBulkPreviewView()
        request = self._request_for_view(
            view,
            "post",
            "/students/enrollment-lifecycle/preview/",
            {"action": "complete_year"},
        )

        self.assertTrue(StudentAccessPolicy().has_permission(request, view))
        _require_bulk_action_permission(request, "complete_year")
        with self.assertRaises(PermissionDenied):
            _require_bulk_action_permission(request, "transfer_out")
