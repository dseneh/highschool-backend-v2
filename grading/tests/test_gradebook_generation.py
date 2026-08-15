"""Regression tests for gradebook/assessment generation used by the year-end wizard."""

from datetime import date
from unittest.mock import patch

from django.test import SimpleTestCase
from django_tenants.test.cases import TenantTestCase
from rest_framework.exceptions import ValidationError

from academics.models import (
    AcademicYear,
    Division,
    GradeLevel,
    MarkingPeriod,
    Section,
    SectionSubject,
    Semester,
    Subject,
)
from grading.gradebook_initializer import initialize_gradebooks_for_academic_year
from grading.models import Assessment, AssessmentType, DefaultAssessmentTemplate, GradeBook
from grading.utils import create_gradebook_with_assessments
from settings.models import GradingSettings
from students.services.year_end_wizard import apply_year_end_wizard
from users.models import User


class GradingTaskImportTests(SimpleTestCase):
    """`grading/tasks.py` used to be shadowed by the `grading/tasks/` package."""

    def test_grading_task_manager_is_importable_from_tasks_package(self):
        from grading.tasks import GradingTaskManager, MockTaskProcessor

        self.assertTrue(hasattr(GradingTaskManager, "create_task"))
        self.assertTrue(hasattr(MockTaskProcessor, "process_gradebook_initialization"))

    def test_gradebook_and_transcript_task_modules_coexist(self):
        from grading.tasks.gradebook_tasks import GradingTaskManager
        from grading.tasks.transcript_worker import (
            start_official_transcript_background_task,
        )

        self.assertTrue(callable(start_official_transcript_background_task))
        self.assertFalse(GradingTaskManager.should_use_background(0))


class GradebookGenerationFixtureMixin:
    """Minimal academic/grading setup shared by generation and wizard tests."""

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.name = "Gradebook Generation Test School"
        tenant.id_number = "GGT001"
        tenant.owner, _ = User.objects.get_or_create(
            email="gradebook-owner@example.com",
            defaults={
                "username": "gradebook-owner",
                "id_number": "GRADEBOOK-OWNER-001",
                "role": "admin",
                "first_name": "Gradebook",
                "last_name": "Owner",
            },
        )

    def setUp(self):
        self.academic_year = AcademicYear.objects.create(
            name="2025-2026",
            start_date=date(2025, 9, 1),
            end_date=date(2026, 6, 30),
            current=True,
        )
        semester = Semester.objects.create(
            academic_year=self.academic_year,
            name="Semester 1",
            start_date=date(2025, 9, 1),
            end_date=date(2026, 1, 31),
        )
        self.marking_period = MarkingPeriod.objects.create(
            semester=semester,
            name="First Period",
            start_date=date(2025, 9, 1),
            end_date=date(2025, 11, 30),
        )

        division = Division.objects.create(name="Elementary")
        self.grade_one = GradeLevel.objects.create(name="Grade 1", level=1, division=division)
        self.grade_two = GradeLevel.objects.create(name="Grade 2", level=2, division=division)
        self.section_one = Section.objects.create(name="1A", grade_level=self.grade_one)
        self.section_two = Section.objects.create(name="2A", grade_level=self.grade_two)

        self.math = Subject.objects.create(name="Mathematics", code="MATH")
        SectionSubject.objects.create(section=self.section_one, subject=self.math)
        SectionSubject.objects.create(section=self.section_two, subject=self.math)

        self.assessment_type = AssessmentType.objects.create(name="Quiz")
        DefaultAssessmentTemplate.objects.create(
            name="Quiz 1",
            assessment_type=self.assessment_type,
            max_score=100,
            weight=1,
        )


class GradebookGenerationTests(GradebookGenerationFixtureMixin, TenantTestCase):
    def _generate(self, **kwargs):
        kwargs.setdefault("grading_style", "multiple_entry")
        return initialize_gradebooks_for_academic_year(
            academic_year=self.academic_year,
            skip_assessment_types=True,
            skip_grade_letters=True,
            skip_templates=True,
            **kwargs,
        )

    def test_generates_gradebooks_and_assessments_for_full_year(self):
        result = self._generate()

        self.assertTrue(result["success"], result["message"])
        self.assertEqual(result["stats"]["gradebooks_created"], 2)
        self.assertEqual(GradeBook.objects.count(), 2)
        self.assertEqual(
            Assessment.objects.filter(marking_period=self.marking_period).count(), 2
        )

    def test_rerunning_generation_does_not_duplicate_records(self):
        self._generate()
        result = self._generate()

        self.assertTrue(result["success"], result["message"])
        self.assertEqual(result["stats"]["gradebooks_created"], 0)
        self.assertEqual(result["stats"]["gradebooks_skipped"], 2)
        self.assertEqual(GradeBook.objects.count(), 2)
        self.assertEqual(Assessment.objects.count(), 2)

    def test_backfills_assessments_missing_on_existing_gradebooks(self):
        self._generate()
        Assessment.objects.all().delete()

        result = self._generate()

        self.assertTrue(result["success"], result["message"])
        self.assertEqual(result["stats"]["gradebooks_created"], 0)
        self.assertEqual(result["stats"]["gradebooks_backfilled"], 2)
        self.assertEqual(Assessment.objects.count(), 2)

    def test_grade_level_scope_only_affects_selected_grade_level(self):
        result = self._generate(grade_level_id=str(self.grade_one.id))

        self.assertTrue(result["success"], result["message"])
        self.assertEqual(result["stats"]["gradebooks_created"], 1)
        self.assertEqual(GradeBook.objects.count(), 1)
        self.assertEqual(GradeBook.objects.first().section, self.section_one)

    def test_section_scope_only_affects_selected_section(self):
        result = self._generate(section_id=str(self.section_two.id))

        self.assertTrue(result["success"], result["message"])
        self.assertEqual(result["stats"]["gradebooks_created"], 1)
        self.assertEqual(GradeBook.objects.count(), 1)
        self.assertEqual(GradeBook.objects.first().section, self.section_two)

    def test_missing_marking_periods_returns_clear_error(self):
        MarkingPeriod.objects.all().delete()

        result = self._generate()

        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "NO_MARKING_PERIODS")
        self.assertIn("marking period", result["message"].lower())
        self.assertEqual(GradeBook.objects.count(), 0)

    def test_missing_assessment_templates_returns_clear_error(self):
        DefaultAssessmentTemplate.objects.all().delete()

        result = self._generate()

        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "NO_ASSESSMENT_TEMPLATES")
        self.assertEqual(GradeBook.objects.count(), 0)

    def test_empty_scope_returns_clear_error(self):
        result = self._generate(section_id=str(self.section_one.id), grade_level_id=str(self.grade_two.id))

        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "NO_SECTIONS_IN_SCOPE")
        self.assertEqual(GradeBook.objects.count(), 0)

    def test_sections_without_subjects_return_clear_error(self):
        SectionSubject.objects.all().delete()

        result = self._generate()

        self.assertFalse(result["success"])
        self.assertEqual(result["error_code"], "NO_SECTION_SUBJECTS")
        self.assertEqual(GradeBook.objects.count(), 0)

    def test_grading_style_defaults_to_configured_settings(self):
        GradingSettings.objects.create(grading_style="single_entry")

        result = self._generate(grading_style=None)

        self.assertTrue(result["success"], result["message"])
        self.assertEqual(result["grading_style"], "single_entry")
        self.assertEqual(Assessment.objects.count(), 2)
        self.assertTrue(
            Assessment.objects.filter(assessment_type__is_single_entry=True).exists()
        )

    def test_backfills_single_entry_assessments_after_style_switch(self):
        self._generate(grading_style="multiple_entry")
        self.assertFalse(
            Assessment.objects.filter(assessment_type__is_single_entry=True).exists()
        )

        result = self._generate(grading_style="single_entry")

        self.assertTrue(result["success"], result["message"])
        self.assertEqual(result["stats"]["gradebooks_created"], 0)
        self.assertEqual(result["stats"]["gradebooks_backfilled"], 2)
        self.assertEqual(
            Assessment.objects.filter(assessment_type__is_single_entry=True).count(), 2
        )

    def test_generated_assessments_are_linked_to_full_scope(self):
        self._generate(section_id=str(self.section_one.id))

        gradebook = GradeBook.objects.get(section=self.section_one)
        assessment = Assessment.objects.get(gradebook=gradebook)

        self.assertEqual(assessment.marking_period, self.marking_period)
        self.assertEqual(assessment.gradebook.academic_year, self.academic_year)
        self.assertEqual(assessment.gradebook.section, self.section_one)
        self.assertEqual(assessment.gradebook.subject, self.math)
        self.assertEqual(
            assessment.gradebook.section_subject.section.grade_level, self.grade_one
        )


class CreateGradebookWithAssessmentsTests(GradebookGenerationFixtureMixin, TenantTestCase):
    """The shared service every gradebook workflow routes through."""

    def _create(self, **kwargs):
        return create_gradebook_with_assessments(
            section_subject=SectionSubject.objects.get(section=self.section_one),
            academic_year=self.academic_year,
            **kwargs,
        )

    def test_creates_gradebook_and_assessments(self):
        result = self._create(grading_style="multiple_entry")

        self.assertTrue(result["created"])
        self.assertEqual(result["generation_result"]["assessments_created"], 1)
        self.assertEqual(
            Assessment.objects.filter(gradebook=result["gradebook"]).count(), 1
        )

    def test_retry_is_idempotent(self):
        first = self._create(grading_style="multiple_entry")
        second = self._create(grading_style="multiple_entry")

        self.assertFalse(second["created"])
        self.assertEqual(second["gradebook"].id, first["gradebook"].id)
        self.assertEqual(second["generation_result"]["assessments_created"], 0)
        self.assertEqual(GradeBook.objects.count(), 1)
        self.assertEqual(Assessment.objects.count(), 1)

    def test_uses_configured_grading_style_when_not_supplied(self):
        GradingSettings.objects.create(grading_style="single_entry")

        result = self._create()

        self.assertEqual(result["generation_result"]["mode"], "single_entry")
        self.assertTrue(
            Assessment.objects.filter(
                gradebook=result["gradebook"], assessment_type__is_single_entry=True
            ).exists()
        )


class YearEndWizardGradebookGenerationTests(
    GradebookGenerationFixtureMixin, TenantTestCase
):
    """The wizard must reuse the shared generation service, not its own logic."""

    def _apply(self, **kwargs):
        return apply_year_end_wizard(
            academic_year=self.academic_year,
            outcomes={},
            consent_acknowledged=True,
            **kwargs,
        )

    def test_wizard_generates_gradebooks_with_assessments(self):
        result = self._apply()

        stats = result["gradebook_initialization"]["stats"]
        self.assertEqual(result["gradebook_initialization"]["grading_style"], "multiple_entry")
        self.assertEqual(stats["gradebooks_created"], 2)
        self.assertEqual(Assessment.objects.count(), stats["assessments_created"])
        self.assertEqual(GradeBook.objects.count(), 2)
        for gradebook in GradeBook.objects.all():
            assessments = Assessment.objects.filter(gradebook=gradebook)
            self.assertTrue(assessments.exists())
            self.assertEqual(
                assessments.exclude(marking_period=self.marking_period).count(), 0
            )

    def test_wizard_uses_configured_single_entry_style(self):
        GradingSettings.objects.create(grading_style="single_entry")

        result = self._apply()

        self.assertEqual(result["gradebook_initialization"]["grading_style"], "single_entry")
        self.assertEqual(
            Assessment.objects.filter(assessment_type__is_single_entry=True).count(), 2
        )

    def test_wizard_respects_section_scope(self):
        self._apply(section_id=str(self.section_one.id))

        self.assertEqual(GradeBook.objects.count(), 1)
        gradebook = GradeBook.objects.get()
        self.assertEqual(gradebook.section, self.section_one)
        self.assertTrue(Assessment.objects.filter(gradebook=gradebook).exists())

    def test_wizard_retry_does_not_duplicate_assessments(self):
        self._apply()
        gradebooks = GradeBook.objects.count()
        assessments = Assessment.objects.count()

        self._apply()

        self.assertEqual(GradeBook.objects.count(), gradebooks)
        self.assertEqual(Assessment.objects.count(), assessments)

    def test_wizard_surfaces_missing_grading_configuration(self):
        MarkingPeriod.objects.all().delete()

        with self.assertRaises(ValidationError) as ctx:
            self._apply()

        detail = ctx.exception.detail
        self.assertEqual(str(detail["error_code"]), "NO_MARKING_PERIODS")
        self.assertIn("marking period", str(detail["detail"]).lower())
        self.assertEqual(GradeBook.objects.count(), 0)


class CurrentAcademicYearResolutionTests(TenantTestCase):
    """Gradebook initialization must target the current year, not any active row."""

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.name = "Current Year Test School"
        tenant.id_number = "CYT001"
        tenant.owner, _ = User.objects.get_or_create(
            email="current-year-owner@example.com",
            defaults={
                "username": "current-year-owner",
                "id_number": "CURRENT-YEAR-OWNER-001",
                "role": "admin",
                "first_name": "Current",
                "last_name": "Owner",
            },
        )

    def setUp(self):
        self.previous_year = AcademicYear.objects.create(
            name="2025-2026",
            start_date=date(2025, 9, 1),
            end_date=date(2026, 6, 30),
            current=False,
        )
        self.current_year = AcademicYear.objects.create(
            name="2026-2027",
            start_date=date(2026, 9, 1),
            end_date=date(2027, 6, 30),
            current=True,
        )

    def test_resolves_the_year_flagged_current(self):
        self.assertEqual(AcademicYear.get_current_academic_year(), self.current_year)

    def test_soft_delete_flag_does_not_identify_the_current_year(self):
        # Every row is active=True by default, so filtering on it can return
        # the previous year -- the bug that validated against 2025-2026.
        self.assertTrue(self.previous_year.active)
        self.assertNotEqual(
            AcademicYear.objects.filter(active=True).count(),
            AcademicYear.objects.filter(current=True).count(),
        )

    def test_historical_years_are_never_treated_as_current(self):
        AcademicYear.objects.update(current=False)
        AcademicYear.objects.create(
            name="2019-2020 (archive)",
            start_date=date(2019, 9, 1),
            end_date=date(2020, 6, 30),
            current=True,
            year_type=AcademicYear.YearType.HISTORICAL,
        )

        self.assertIsNone(AcademicYear.get_current_academic_year())

    def test_grading_view_resolves_current_year_not_active_flag(self):
        import inspect

        from settings.views import grading as grading_views

        source = inspect.getsource(grading_views)
        self.assertNotIn("AcademicYear.objects.filter(active=True)", source)
        self.assertIn("AcademicYear.get_current_academic_year()", source)


class BackgroundTaskReportingTests(SimpleTestCase):
    """A failed initialization must not be reported to the user as completed."""

    def _run_task(self, init_result):
        from grading.tasks import GradingTaskManager, MockTaskProcessor

        task_id = GradingTaskManager.create_task(
            task_type="gradebook_initialization",
            academic_year_id="ay-1",
            user_id="user-1",
            params={},
            schema_name="tenant1",
        )

        class _InlineThread:
            def __init__(self, target=None, **kwargs):
                self._target = target

            def start(self):
                self._target()

        with patch("threading.Thread", _InlineThread), patch(
            "django_tenants.utils.schema_context"
        ), patch(
            "academics.models.AcademicYear.objects.get"
        ), patch(
            "users.models.User.objects.get"
        ), patch(
            "grading.gradebook_initializer.initialize_gradebooks_for_academic_year",
            return_value=init_result,
        ):
            MockTaskProcessor.process_gradebook_initialization(task_id)

        return GradingTaskManager.get_task(task_id)

    def test_unsuccessful_initialization_marks_task_failed(self):
        task = self._run_task(
            {
                "success": False,
                "message": "No active marking periods are configured for 2025-2026.",
                "error_code": "NO_MARKING_PERIODS",
                "stats": {},
                "errors": ["No active marking periods are configured for 2025-2026."],
            }
        )

        self.assertEqual(task["status"], "failed")
        self.assertEqual(task["error_code"], "NO_MARKING_PERIODS")
        self.assertIn("marking periods", task["error"])

    def test_successful_initialization_marks_task_completed(self):
        task = self._run_task({"success": True, "message": "done", "stats": {}})

        self.assertEqual(task["status"], "completed")
        self.assertEqual(task["progress"], 100)

    def test_task_status_response_is_not_successful_when_task_failed(self):
        from grading.response import GradingResponse

        response = GradingResponse.task_status(
            task_id="task-1",
            status="failed",
            progress=100,
            message="No active marking periods are configured for 2025-2026.",
            created_at="2026-08-15T19:00:20Z",
            updated_at="2026-08-15T19:00:20Z",
            error="No active marking periods are configured for 2025-2026.",
            error_code="NO_MARKING_PERIODS",
        )

        self.assertFalse(response.data["success"])
        self.assertEqual(response.data["task"]["status"], "failed")
        self.assertIn("marking periods", response.data["task"]["detail"])
