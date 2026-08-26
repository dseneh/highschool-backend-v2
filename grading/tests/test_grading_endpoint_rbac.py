"""RBAC coverage for grading endpoints that mutate configuration and assessments."""

from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase
from django_tenants.test.cases import TenantTestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from authorization.models import Role
from authorization.services import assign_user_role, replace_role_permissions
from grading.access_policies import GradebookAccessPolicy
from grading.views.assessment import AssessmentListCreateView
from grading.views.assessment_type import AssessmentTypeListCreateView
from grading.views.bulk_upload import (
    BulkGradeAllSubjectsTemplateDownloadView,
    BulkGradeTemplateDownloadView,
    GradebookTemplateBatchDownloadView,
)
from grading.views.default_assessment_template import (
    DefaultAssessmentTemplateListCreateView,
    GenerateAssessmentsForAcademicYearView,
)
from grading.views.grade_letter import (
    GenerateDefaultGradeLettersView,
    GradeLetterListCreateView,
)
from grading.views.honor_category import (
    HonorCategoryDetailView,
    HonorCategoryListCreateView,
)
from grading.models import Grade
from grading.views.grade import (
    GradeMarkForCorrectionView,
    require_grade_transition_permissions,
)
from users.models import User


class GradingEndpointPolicyDeclarationTests(SimpleTestCase):
    def test_mutating_views_declare_gradebook_access_policy(self):
        guarded_views = [
            AssessmentListCreateView,
            AssessmentTypeListCreateView,
            BulkGradeTemplateDownloadView,
            BulkGradeAllSubjectsTemplateDownloadView,
            GradebookTemplateBatchDownloadView,
            DefaultAssessmentTemplateListCreateView,
            GenerateAssessmentsForAcademicYearView,
            GradeLetterListCreateView,
            GenerateDefaultGradeLettersView,
            HonorCategoryListCreateView,
            HonorCategoryDetailView,
        ]

        for view_class in guarded_views:
            with self.subTest(view=view_class.__name__):
                self.assertIn(GradebookAccessPolicy, view_class.permission_classes)


class GradeTransitionPermissionTests(SimpleTestCase):
    def assert_required_permission(
        self,
        source,
        target,
        expected_permission,
        *,
        require_review=True,
        require_approval=True,
    ):
        authorization = Mock()
        request = SimpleNamespace(user=object())
        with (
            patch(
                "grading.views.grade.get_workflow_settings",
                return_value={
                    "require_grade_review": require_review,
                    "require_grade_approval": require_approval,
                },
            ),
            patch(
                "grading.views.grade.initialize_request_authorization",
                return_value=authorization,
            ),
        ):
            require_grade_transition_permissions(request, target, [source])

        authorization.require_permission.assert_called_once_with(expected_permission)

    def test_entry_submission_requires_grades_enter(self):
        self.assert_required_permission(
            Grade.Status.DRAFT,
            Grade.Status.PENDING,
            "grades.enter",
        )

    def test_review_requires_grades_review(self):
        self.assert_required_permission(
            Grade.Status.PENDING,
            Grade.Status.REVIEWED,
            "grades.review",
        )

    def test_rejection_requires_grades_reject(self):
        self.assert_required_permission(
            Grade.Status.PENDING,
            Grade.Status.REJECTED,
            "grades.reject",
        )

    def test_approval_requires_grades_approve(self):
        self.assert_required_permission(
            Grade.Status.SUBMITTED,
            Grade.Status.APPROVED,
            "grades.approve",
        )

    def test_unlock_requires_grades_unlock(self):
        self.assert_required_permission(
            Grade.Status.APPROVED,
            Grade.Status.DRAFT,
            "grades.unlock",
        )

    def test_automatic_entry_finalization_requires_grades_enter(self):
        self.assert_required_permission(
            Grade.Status.PENDING,
            Grade.Status.APPROVED,
            "grades.enter",
            require_review=False,
            require_approval=False,
        )


class GradingCustomRolePolicyTests(TenantTestCase):
    @classmethod
    def get_test_schema_name(cls):
        return "grading_endpoint_rbac"

    @classmethod
    def get_test_tenant_domain(cls):
        return "grading-endpoint-rbac.tenant.test.com"

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.name = "Grading Endpoint RBAC Test School"
        tenant.id_number = "GER001"
        tenant.owner, _ = User.objects.get_or_create(
            email="grading-endpoint-owner@example.com",
            defaults={
                "username": "grading-endpoint-owner",
                "id_number": "GRADING-ENDPOINT-OWNER-001",
                "account_type": "staff",
            },
        )

    def setUp(self):
        super().setUp()
        self.factory = APIRequestFactory()
        self.user, _ = User.objects.get_or_create(
            email="grading-endpoint-user@example.com",
            defaults={
                "username": "grading-endpoint-user",
                "id_number": "GRADING-ENDPOINT-USER-001",
                "account_type": "staff",
            },
        )
        self.tenant.add_user(self.user)
        self.role = Role.objects.create(name="Assessment Coordinator")
        assign_user_role(user=self.user, role=self.role, actor=self.tenant.owner)

    def policy_allows_post(self):
        raw_request = self.factory.post("/grading/assessment-types/", {})
        raw_request.tenant = self.tenant
        force_authenticate(raw_request, user=self.user)
        view = AssessmentTypeListCreateView()
        request = view.initialize_request(raw_request)
        request.tenant = self.tenant
        view.request = request
        return GradebookAccessPolicy().has_permission(request, view)

    def policy_allows_get(self):
        raw_request = self.factory.get("/grading/assessment-types/")
        raw_request.tenant = self.tenant
        force_authenticate(raw_request, user=self.user)
        view = AssessmentTypeListCreateView()
        request = view.initialize_request(raw_request)
        request.tenant = self.tenant
        view.request = request
        return GradebookAccessPolicy().has_permission(request, view)

    def policy_allows_mark_for_correction(self):
        raw_request = self.factory.post("/grading/grades/grade-1/mark-for-correction/", {})
        raw_request.tenant = self.tenant
        force_authenticate(raw_request, user=self.user)
        view = GradeMarkForCorrectionView()
        request = view.initialize_request(raw_request)
        request.tenant = self.tenant
        view.request = request
        return GradebookAccessPolicy().has_permission(request, view)

    def test_grades_enter_grant_allows_grading_mutation(self):
        replace_role_permissions(
            self.role,
            {"grades.view": "all", "grades.enter": "all"},
            actor=self.tenant.owner,
        )

        self.assertTrue(self.policy_allows_post())

    def test_grades_view_alone_denies_grading_mutation(self):
        replace_role_permissions(
            self.role,
            {"grades.view": "all"},
            actor=self.tenant.owner,
        )

        self.assertFalse(self.policy_allows_post())

    def test_assigned_grades_enter_grant_allows_grading_mutation(self):
        replace_role_permissions(
            self.role,
            {"grades.view": "assigned", "grades.enter": "assigned"},
            actor=self.tenant.owner,
        )

        self.assertTrue(self.policy_allows_post())

    def test_grades_view_grant_is_required_for_read(self):
        replace_role_permissions(
            self.role,
            {"grades.view": "own"},
            actor=self.tenant.owner,
        )
        self.assertTrue(self.policy_allows_get())

        replace_role_permissions(self.role, {}, actor=self.tenant.owner)
        self.assertFalse(self.policy_allows_get())

    def test_mark_for_correction_requires_review_grant(self):
        replace_role_permissions(
            self.role,
            {"grades.view": "assigned", "grades.review": "assigned"},
            actor=self.tenant.owner,
        )
        self.assertTrue(self.policy_allows_mark_for_correction())

        replace_role_permissions(
            self.role,
            {"grades.view": "assigned", "grades.enter": "assigned"},
            actor=self.tenant.owner,
        )
        self.assertFalse(self.policy_allows_mark_for_correction())
