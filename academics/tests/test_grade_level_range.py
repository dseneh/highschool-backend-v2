from django_tenants.test.cases import TenantTestCase
from django_tenants.utils import schema_context
from rest_framework.test import APIRequestFactory, force_authenticate

from academics.models import GradeLevel
from academics.services.grade_level_range import (
    default_grade_levels_through_division,
    grade_levels_through_division,
    max_level_for_division,
)
from core.models import Division
from defaults.services import _apply_grade_structure, build_initial_plan
from core.onboarding_views import save_onboarding_step
from academics.views.grade_level import GradeLevelDetailView, GradeLevelListView
from users.models import User


class DivisionGradeLevelRangeTests(TenantTestCase):
    @classmethod
    def setup_tenant(cls, tenant):
        tenant.name = "Division Range Test School"
        tenant.id_number = "DRT001"
        tenant.owner, _ = User.objects.get_or_create(
            email="division-range@example.com",
            defaults={
                "username": "division-range",
                "id_number": "DIVISION-RANGE-001",
                "account_type": "staff",
            },
        )

    def setUp(self):
        self.preschool = Division.objects.get(name="Preschool")
        self.elementary = Division.objects.get(name="Elementary")
        self.junior_high = Division.objects.get(name="Junior High School")
        self.senior_high = Division.objects.get(name="Senior High School")
        self.tenant.school_division = self.junior_high
        self.tenant.save(update_fields=["school_division"])

        self.levels = [
            GradeLevel.objects.create(name="Nursery", short_name="N", level=1, division=self.preschool),
            GradeLevel.objects.create(name="Grade 6", short_name="G6", level=10, division=self.elementary),
            GradeLevel.objects.create(name="Grade 9", short_name="G9", level=13, division=self.junior_high),
            GradeLevel.objects.create(name="Grade 12", short_name="G12", level=16, division=self.senior_high),
        ]

    def test_selected_division_defines_inclusive_maximum_level(self):
        self.assertEqual(max_level_for_division(self.junior_high), 13)

        result = list(
            grade_levels_through_division(
                GradeLevel.objects.order_by("level"),
                self.junior_high,
            ).values_list("level", flat=True)
        )

        self.assertEqual(result, [1, 10, 13])

    def test_grade_level_endpoint_returns_the_cumulative_range(self):
        request = APIRequestFactory().get(
            "/grade-levels/",
            HTTP_X_TENANT=self.tenant.schema_name,
        )
        force_authenticate(request, user=self.tenant.owner)

        response = GradeLevelListView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["level"] for item in response.data], [1, 10, 13])

    def test_deactivation_persists_and_list_immediately_returns_inactive_state(self):
        grade_level = self.levels[1]
        update_request = APIRequestFactory().put(
            f"/grade-levels/{grade_level.id}/",
            {"active": False},
            format="json",
            HTTP_X_TENANT=self.tenant.schema_name,
        )
        force_authenticate(update_request, user=self.tenant.owner)

        update_response = GradeLevelDetailView.as_view()(update_request, id=grade_level.id)
        grade_level.refresh_from_db()

        list_request = APIRequestFactory().get(
            "/grade-levels/",
            HTTP_X_TENANT=self.tenant.schema_name,
        )
        force_authenticate(list_request, user=self.tenant.owner)
        list_response = GradeLevelListView.as_view()(list_request)
        listed = next(item for item in list_response.data if item["id"] == str(grade_level.id))

        self.assertEqual(update_response.status_code, 200)
        self.assertFalse(grade_level.active)
        self.assertFalse(listed["active"])
        self.assertEqual(listed["status"], "disabled")

    def test_onboarding_plan_only_includes_defaults_through_selected_division(self):
        with schema_context("public"):
            tenant = self.tenant.__class__.objects.select_related("school_division").get(
                pk=self.tenant.pk
            )
            plan = build_initial_plan(tenant)
        levels = [
            item["level"]
            for item in plan["steps"]["grade_structure"]["payload"]["grade_levels"]
        ]

        self.assertEqual(levels, list(range(1, 14)))
        self.assertNotIn(14, levels)

    def test_shared_division_rename_preserves_default_range_by_stable_id(self):
        self.junior_high.name = "Lower Secondary"
        self.junior_high.save(update_fields=["name"])

        levels = [
            item["level"]
            for item in default_grade_levels_through_division(self.junior_high)
        ]

        self.assertEqual(levels, list(range(1, 14)))

    def test_onboarding_apply_ignores_submitted_levels_above_selected_maximum(self):
        GradeLevel.objects.all().delete()
        payload = {
            "grade_levels": [
                {
                    "name": item["name"],
                    "short_name": item["short_name"],
                    "level": item["level"],
                }
                for item in default_grade_levels_through_division(self.senior_high)
            ]
        }

        _apply_grade_structure(self.tenant, self.tenant.owner, payload)

        self.assertEqual(GradeLevel.objects.count(), 13)
        self.assertEqual(GradeLevel.objects.order_by("-level").first().level, 13)

    def test_saving_school_division_refreshes_onboarding_grade_range(self):
        self.tenant.onboarding_plan = build_initial_plan(self.tenant)
        self.tenant.save(update_fields=["onboarding_plan"])
        request = APIRequestFactory().patch(
            "/onboarding/",
            {
                "step_key": "school_profile",
                "payload": {"school_division": str(self.elementary.id)},
                "mark_completed": True,
            },
            format="json",
        )
        force_authenticate(request, user=self.tenant.owner)

        response = save_onboarding_step(request, self.tenant.schema_name)
        self.tenant.refresh_from_db()
        levels = [
            item["level"]
            for item in self.tenant.onboarding_plan["steps"]["grade_structure"]["payload"]["grade_levels"]
        ]

        self.assertEqual(response.status_code, 200)
        self.assertEqual(levels, list(range(1, 11)))
