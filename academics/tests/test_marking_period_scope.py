"""Marking-period list requests must always be scoped to one academic year."""

from datetime import date

from django_tenants.test.cases import TenantTestCase
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from academics.models import AcademicYear, MarkingPeriod, Semester
from academics.views.marking_period import MarkingPeriodListAllView
from users.models import User


class MarkingPeriodAcademicYearScopeTests(TenantTestCase):
    @classmethod
    def setup_tenant(cls, tenant):
        tenant.name = "Marking Period Scope Test School"
        tenant.id_number = "MPST001"
        tenant.owner, _ = User.objects.get_or_create(
            email="marking-period-owner@example.com",
            defaults={
                "username": "marking-period-owner",
                "id_number": "MARKING-PERIOD-OWNER-001",
                "account_type": "staff",
                "first_name": "Marking Period",
                "last_name": "Owner",
            },
        )

    def setUp(self):
        self.current_year = AcademicYear.objects.create(
            name="2026-2027",
            start_date=date(2026, 9, 1),
            end_date=date(2027, 6, 30),
            current=True,
        )
        self.other_year = AcademicYear.objects.create(
            name="2025-2026",
            start_date=date(2025, 9, 1),
            end_date=date(2026, 6, 30),
        )
        current_semester = Semester.objects.create(
            academic_year=self.current_year,
            name="Current Semester",
            start_date=date(2026, 9, 1),
            end_date=date(2027, 1, 31),
        )
        other_semester = Semester.objects.create(
            academic_year=self.other_year,
            name="Previous Semester",
            start_date=date(2025, 9, 1),
            end_date=date(2026, 1, 31),
        )
        self.current_period = MarkingPeriod.objects.create(
            semester=current_semester,
            name="Current Period",
            start_date=date(2026, 9, 1),
            end_date=date(2026, 11, 30),
        )
        self.other_period = MarkingPeriod.objects.create(
            semester=other_semester,
            name="Previous Period",
            start_date=date(2025, 9, 1),
            end_date=date(2025, 11, 30),
        )
        self.factory = APIRequestFactory()
        self.view = MarkingPeriodListAllView()

    def get(self, query: str = ""):
        request = Request(self.factory.get(f"/marking-periods/{query}"))
        return self.view.get(request)

    def test_requires_academic_year_scope(self):
        response = self.get()

        self.assertEqual(response.status_code, 400)
        self.assertIn("academic_year", response.data["detail"])

    def test_filters_by_selected_academic_year(self):
        response = self.get(f"?academic_year={self.other_year.id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["name"] for item in response.data], ["Previous Period"])

    def test_current_alias_only_returns_current_year_periods(self):
        response = self.get("?academic_year=current")

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["name"] for item in response.data], ["Current Period"])
