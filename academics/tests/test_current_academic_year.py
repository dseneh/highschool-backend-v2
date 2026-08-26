"""Tests for promoting an academic year to current."""

from datetime import date

from django.core.exceptions import ValidationError
from django_tenants.test.cases import TenantTestCase

from academics.models import AcademicYear
from academics.services.current_academic_year import set_current_academic_year
from users.models import User


class SetCurrentAcademicYearTests(TenantTestCase):
    @classmethod
    def setup_tenant(cls, tenant):
        tenant.name = "Current Academic Year Test School"
        tenant.id_number = "CAY001"
        tenant.owner, _ = User.objects.get_or_create(
            email="current-year-owner@example.com",
            defaults={
                "username": "current-year-owner",
                "id_number": "CURRENT-YEAR-OWNER-001",
                "account_type": "staff",
                "first_name": "Current",
                "last_name": "Owner",
            },
        )

    def setUp(self):
        self.previous_year = AcademicYear.objects.create(
            name="2024-2025",
            start_date=date(2024, 9, 2),
            end_date=date(2025, 7, 18),
            current=False,
            status="inactive",
        )
        self.active_year = AcademicYear.objects.create(
            name="2025-2026",
            start_date=date(2025, 9, 1),
            end_date=date(2026, 7, 17),
            current=True,
            status="active",
        )

    def test_promotes_year_and_demotes_the_previous_one(self):
        updated, previous = set_current_academic_year(self.previous_year)

        self.assertTrue(updated.current)
        self.assertEqual(previous, self.active_year)

        self.active_year.refresh_from_db()
        self.assertFalse(self.active_year.current)

    def test_only_one_year_stays_current(self):
        set_current_academic_year(self.previous_year)

        self.assertEqual(AcademicYear.objects.filter(current=True).count(), 1)
        self.assertEqual(
            AcademicYear.get_current_academic_year().id, self.previous_year.id
        )

    def test_promoted_year_becomes_active(self):
        updated, _ = set_current_academic_year(self.previous_year)

        updated.refresh_from_db()
        self.assertEqual(updated.status, "active")

    def test_repeating_the_promotion_is_idempotent(self):
        set_current_academic_year(self.previous_year)
        set_current_academic_year(self.previous_year)

        self.assertEqual(AcademicYear.objects.filter(current=True).count(), 1)

    def test_historical_year_cannot_become_current(self):
        historical = AcademicYear.objects.create(
            name="2019-2020",
            start_date=date(2019, 9, 2),
            end_date=date(2020, 7, 17),
            year_type=AcademicYear.YearType.HISTORICAL,
        )

        with self.assertRaises(ValidationError):
            set_current_academic_year(historical)

        self.active_year.refresh_from_db()
        self.assertTrue(self.active_year.current)

    def test_year_without_dates_cannot_become_current(self):
        undated = AcademicYear.objects.create(name="Undated")

        with self.assertRaises(ValidationError):
            set_current_academic_year(undated)

        self.active_year.refresh_from_db()
        self.assertTrue(self.active_year.current)
