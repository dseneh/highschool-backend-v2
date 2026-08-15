"""Regression tests for atomic academic-year creation and overlap validation."""

from datetime import date
from unittest.mock import patch

from django_tenants.test.cases import TenantTestCase

from academics.models import AcademicYear, MarkingPeriod, Semester
from academics.services.academic_year_rollover import apply_rollover
from academics.services.current_academic_year import find_overlapping_academic_year
from users.models import User


class AcademicYearRolloverAtomicityTests(TenantTestCase):
    @classmethod
    def setup_tenant(cls, tenant):
        tenant.name = "Rollover Atomicity Test School"
        tenant.id_number = "RAT001"
        tenant.owner, _ = User.objects.get_or_create(
            email="rollover-owner@example.com",
            defaults={
                "username": "rollover-owner",
                "id_number": "ROLLOVER-OWNER-001",
                "role": "admin",
                "first_name": "Rollover",
                "last_name": "Owner",
            },
        )

    def setUp(self):
        self.source_year = AcademicYear.objects.create(
            name="2026-2027",
            start_date=date(2026, 9, 7),
            end_date=date(2027, 7, 22),
            current=True,
            status="active",
        )
        semester_one = Semester.objects.create(
            academic_year=self.source_year,
            name="Semester 1",
            start_date=date(2026, 9, 7),
            end_date=date(2027, 1, 29),
        )
        semester_two = Semester.objects.create(
            academic_year=self.source_year,
            name="Semester 2",
            start_date=date(2027, 2, 1),
            end_date=date(2027, 7, 22),
        )
        MarkingPeriod.objects.create(
            semester=semester_one,
            name="First Period",
            start_date=date(2026, 9, 7),
            end_date=date(2026, 11, 27),
        )
        MarkingPeriod.objects.create(
            semester=semester_two,
            name="Third Period",
            start_date=date(2027, 2, 1),
            end_date=date(2027, 4, 30),
        )

    def _payload(self, **option_overrides):
        options = {
            "clone_semesters": True,
            "clone_marking_periods": True,
            "clone_installments": False,
            "clone_fee_rates": False,
            "clone_accounting_installment_plans": False,
            "carry_forward_balances": False,
            "initialize_gradebooks": False,
            "set_as_current": True,
            "close_current_year": True,
            "require_ready": False,
        }
        options.update(option_overrides)
        return {
            "source_academic_year_id": str(self.source_year.id),
            "target_name": "2027-2028",
            "target_start_date": "2027-09-06",
            "target_end_date": "2028-07-20",
            "options": options,
        }

    def test_successful_rollover_creates_year_and_related_records(self):
        result = apply_rollover(self._payload(), actor=None)

        target = AcademicYear.objects.get(id=result["academic_year"]["id"])
        self.assertEqual(target.name, "2027-2028")
        self.assertEqual(target.start_date, date(2027, 9, 6))
        self.assertEqual(target.end_date, date(2028, 7, 20))
        self.assertTrue(target.current)
        self.assertEqual(target.semesters.count(), 2)
        self.assertEqual(
            MarkingPeriod.objects.filter(semester__academic_year=target).count(), 2
        )

        self.source_year.refresh_from_db()
        self.assertFalse(self.source_year.current)
        self.assertEqual(self.source_year.status, "inactive")

    def test_semester_failure_rolls_back_the_entire_operation(self):
        with patch(
            "academics.services.academic_year_rollover._clone_semesters_and_marking_periods",
            side_effect=RuntimeError("semester clone exploded"),
        ):
            with self.assertRaises(RuntimeError):
                apply_rollover(self._payload(), actor=None)

        self.assertFalse(AcademicYear.objects.filter(name="2027-2028").exists())
        self.assertEqual(AcademicYear.objects.count(), 1)
        self.assertEqual(Semester.objects.count(), 2)
        self.assertEqual(MarkingPeriod.objects.count(), 2)

    def test_no_partial_year_remains_when_a_later_step_fails(self):
        with patch(
            "academics.services.academic_year_rollover._carry_forward_balances",
            side_effect=RuntimeError("carry forward exploded"),
        ):
            with self.assertRaises(RuntimeError):
                apply_rollover(
                    self._payload(carry_forward_balances=True), actor=None
                )

        self.assertFalse(AcademicYear.objects.filter(name="2027-2028").exists())
        self.assertEqual(Semester.objects.filter(academic_year__name="2027-2028").count(), 0)

    def test_gradebook_failure_rolls_back_the_new_year(self):
        with patch(
            "academics.services.academic_year_rollover.initialize_gradebooks_for_academic_year",
            return_value={
                "success": False,
                "message": "No active marking periods are configured.",
                "error_code": "NO_MARKING_PERIODS",
            },
        ):
            with self.assertRaises(ValueError):
                apply_rollover(self._payload(initialize_gradebooks=True), actor=None)

        self.assertFalse(AcademicYear.objects.filter(name="2027-2028").exists())

    def test_source_year_activation_is_restored_after_rollback(self):
        with patch(
            "academics.services.academic_year_rollover._clone_semesters_and_marking_periods",
            side_effect=RuntimeError("boom"),
        ):
            with self.assertRaises(RuntimeError):
                apply_rollover(self._payload(), actor=None)

        self.source_year.refresh_from_db()
        self.assertTrue(self.source_year.current)
        self.assertEqual(self.source_year.status, "active")

    def test_retry_after_a_failure_is_not_blocked_by_a_phantom_overlap(self):
        with patch(
            "academics.services.academic_year_rollover._clone_semesters_and_marking_periods",
            side_effect=RuntimeError("boom"),
        ):
            with self.assertRaises(RuntimeError):
                apply_rollover(self._payload(), actor=None)

        result = apply_rollover(self._payload(), actor=None)

        self.assertEqual(result["academic_year"]["name"], "2027-2028")
        self.assertEqual(AcademicYear.objects.filter(name="2027-2028").count(), 1)

    def test_non_overlapping_dates_are_accepted(self):
        result = apply_rollover(self._payload(), actor=None)

        self.assertEqual(result["academic_year"]["name"], "2027-2028")

    def test_dates_overlapping_the_source_year_are_rejected(self):
        payload = self._payload()
        payload["target_start_date"] = "2027-05-03"
        payload["target_end_date"] = "2028-03-31"

        with self.assertRaises(ValueError) as ctx:
            apply_rollover(payload, actor=None)

        self.assertIn("overlap", str(ctx.exception).lower())
        self.assertFalse(AcademicYear.objects.filter(name="2027-2028").exists())


class OverlapDetectionTests(TenantTestCase):
    @classmethod
    def setup_tenant(cls, tenant):
        tenant.name = "Overlap Detection Test School"
        tenant.id_number = "ODT001"
        tenant.owner, _ = User.objects.get_or_create(
            email="overlap-owner@example.com",
            defaults={
                "username": "overlap-owner",
                "id_number": "OVERLAP-OWNER-001",
                "role": "admin",
                "first_name": "Overlap",
                "last_name": "Owner",
            },
        )

    def setUp(self):
        self.existing = AcademicYear.objects.create(
            name="2026-2027",
            start_date=date(2026, 9, 7),
            end_date=date(2027, 7, 22),
        )

    def test_adjacent_year_is_not_an_overlap(self):
        self.assertIsNone(
            find_overlapping_academic_year(date(2027, 7, 22), date(2028, 6, 30))
        )

    def test_later_year_is_not_an_overlap(self):
        self.assertIsNone(
            find_overlapping_academic_year(date(2027, 9, 6), date(2028, 7, 20))
        )

    def test_genuine_overlap_is_detected(self):
        conflict = find_overlapping_academic_year(date(2027, 5, 3), date(2028, 3, 31))

        self.assertEqual(conflict, self.existing)

    def test_fully_contained_range_is_detected(self):
        conflict = find_overlapping_academic_year(date(2026, 10, 1), date(2026, 12, 1))

        self.assertEqual(conflict, self.existing)

    def test_record_being_processed_never_conflicts_with_itself(self):
        self.assertIsNone(
            find_overlapping_academic_year(
                self.existing.start_date,
                self.existing.end_date,
                exclude_id=self.existing.id,
            )
        )

    def test_historical_years_do_not_block_a_regular_year(self):
        AcademicYear.objects.create(
            name="Legacy 2026",
            start_date=date(2026, 9, 7),
            end_date=date(2027, 7, 22),
            year_type=AcademicYear.YearType.HISTORICAL,
        )

        conflict = find_overlapping_academic_year(
            date(2026, 9, 7), date(2027, 7, 22), exclude_id=self.existing.id
        )

        self.assertIsNone(conflict)

    def test_years_without_dates_are_ignored(self):
        AcademicYear.objects.create(name="Undated")

        conflict = find_overlapping_academic_year(
            date(2028, 9, 4), date(2029, 7, 20)
        )

        self.assertIsNone(conflict)
