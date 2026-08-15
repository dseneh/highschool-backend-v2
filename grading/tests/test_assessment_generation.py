"""Assessment generation must follow the configured grading style."""

from datetime import date

from django_tenants.test.cases import TenantTestCase

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
from grading.models import Assessment, AssessmentType, DefaultAssessmentTemplate, GradeBook
from grading.utils import (
    generate_assessments_for_gradebook_with_settings,
    generate_default_assessments_for_academic_year,
    regenerate_assessments_for_academic_year,
)
from settings.models import GradingSettings
from users.models import User


class AssessmentGenerationByStyleTests(TenantTestCase):
    @classmethod
    def setup_tenant(cls, tenant):
        tenant.name = "Assessment Generation Test School"
        tenant.id_number = "AGT001"
        tenant.owner, _ = User.objects.get_or_create(
            email="assessment-owner@example.com",
            defaults={
                "username": "assessment-owner",
                "id_number": "ASSESSMENT-OWNER-001",
                "role": "admin",
                "first_name": "Assessment",
                "last_name": "Owner",
            },
        )

    def setUp(self):
        self.academic_year = AcademicYear.objects.create(
            name="2028-2029",
            start_date=date(2028, 9, 1),
            end_date=date(2029, 6, 30),
            current=True,
        )
        semester = Semester.objects.create(
            academic_year=self.academic_year,
            name="Semester 1",
            start_date=date(2028, 9, 1),
            end_date=date(2029, 1, 31),
        )
        self.regular_period = MarkingPeriod.objects.create(
            semester=semester,
            name="First Period",
            start_date=date(2028, 9, 1),
            end_date=date(2028, 11, 30),
        )
        self.exam_period = MarkingPeriod.objects.create(
            semester=semester,
            name="Semester Exam Period",
            start_date=date(2028, 12, 1),
            end_date=date(2029, 1, 31),
        )

        division = Division.objects.create(name="Elementary")
        self.grade_level = GradeLevel.objects.create(
            name="Grade 1", level=1, division=division
        )
        self.section = Section.objects.create(name="General", grade_level=self.grade_level)
        self.subject = Subject.objects.create(name="Mathematics", code="MATH")
        self.section_subject = SectionSubject.objects.create(
            section=self.section, subject=self.subject
        )

        self.gradebook = GradeBook.objects.create(
            section_subject=self.section_subject,
            section=self.section,
            subject=self.subject,
            academic_year=self.academic_year,
            name=f"{self.subject.name} - {self.section.name}",
            calculation_method="weighted",
        )

        self.quiz_type = AssessmentType.objects.create(name="Quiz")
        self.exam_type = AssessmentType.objects.create(name="Exam")

        self.actor, _ = User.objects.get_or_create(
            email="assessment-actor@example.com",
            defaults={
                "username": "assessment-actor",
                "id_number": "ASSESSMENT-ACTOR-001",
                "role": "admin",
                "first_name": "Assessment",
                "last_name": "Actor",
            },
        )

    def _generate(self):
        # created_by mirrors the API view; it used to be passed positionally
        # into the grading_style slot, forcing multiple-entry generation.
        return generate_default_assessments_for_academic_year(
            self.academic_year, created_by=self.actor
        )

    def _add_templates(self):
        DefaultAssessmentTemplate.objects.create(
            name="Quiz 1",
            assessment_type=self.quiz_type,
            max_score=30,
            weight=1,
            target="marking_period",
        )
        DefaultAssessmentTemplate.objects.create(
            name="Semester Exam",
            assessment_type=self.exam_type,
            max_score=100,
            weight=1,
            target="exam",
        )

    def test_single_entry_style_generates_final_grade_per_marking_period(self):
        """Reproduces the bug where bulk generation ignored the configured style."""
        GradingSettings.objects.create(
            grading_style="single_entry", single_entry_assessment_name="Final Grade"
        )

        stats = self._generate()

        self.assertEqual(stats["gradebooks_processed"], 1)
        self.assertEqual(stats["single_entry_gradebooks"], 1)
        self.assertEqual(stats["multiple_entry_gradebooks"], 0)
        self.assertEqual(stats["assessments_created"], 2)
        self.assertEqual(stats["gradebooks_with_errors"], [])

        assessments = Assessment.objects.all()
        self.assertEqual(assessments.count(), 2)
        self.assertTrue(all(a.assessment_type.is_single_entry for a in assessments))
        self.assertEqual({a.name for a in assessments}, {"Final Grade"})
        self.assertEqual(
            {a.marking_period_id for a in assessments},
            {self.regular_period.id, self.exam_period.id},
        )

    def test_multiple_entry_style_generates_template_assessments_by_target(self):
        GradingSettings.objects.create(grading_style="multiple_entry")
        self._add_templates()

        stats = self._generate()

        self.assertEqual(stats["multiple_entry_gradebooks"], 1)
        self.assertEqual(stats["single_entry_gradebooks"], 0)
        self.assertEqual(stats["assessments_created"], 2)

        # Exam templates only land on exam marking periods and vice versa.
        self.assertEqual(
            Assessment.objects.get(marking_period=self.regular_period).name, "Quiz 1"
        )
        self.assertEqual(
            Assessment.objects.get(marking_period=self.exam_period).name, "Semester Exam"
        )

    def test_generated_assessments_are_linked_to_the_correct_scope(self):
        GradingSettings.objects.create(grading_style="single_entry")

        self._generate()

        assessment = Assessment.objects.filter(marking_period=self.regular_period).get()
        self.assertEqual(assessment.gradebook, self.gradebook)
        self.assertEqual(assessment.gradebook.academic_year, self.academic_year)
        self.assertEqual(assessment.gradebook.subject, self.subject)
        self.assertEqual(assessment.gradebook.section, self.section)
        self.assertEqual(assessment.gradebook.section.grade_level, self.grade_level)
        self.assertEqual(assessment.gradebook.section_subject, self.section_subject)
        self.assertEqual(assessment.marking_period.semester.academic_year, self.academic_year)
        self.assertEqual(assessment.due_date, self.regular_period.end_date)

    def test_generation_only_targets_the_requested_academic_year(self):
        GradingSettings.objects.create(grading_style="single_entry")
        other_year = AcademicYear.objects.create(
            name="2029-2030",
            start_date=date(2029, 9, 1),
            end_date=date(2030, 6, 30),
        )
        other_gradebook = GradeBook.objects.create(
            section_subject=self.section_subject,
            section=self.section,
            subject=self.subject,
            academic_year=other_year,
            name="Mathematics - General (next year)",
            calculation_method="weighted",
        )

        self._generate()

        self.assertEqual(Assessment.objects.filter(gradebook=self.gradebook).count(), 2)
        self.assertEqual(Assessment.objects.filter(gradebook=other_gradebook).count(), 0)

    def test_rerunning_generation_creates_no_duplicates(self):
        GradingSettings.objects.create(grading_style="single_entry")

        self._generate()
        stats = self._generate()

        self.assertEqual(stats["assessments_created"], 0)
        self.assertEqual(Assessment.objects.count(), 2)

    def test_rerunning_multiple_entry_generation_creates_no_duplicates(self):
        GradingSettings.objects.create(grading_style="multiple_entry")
        self._add_templates()

        self._generate()
        stats = self._generate()

        self.assertEqual(stats["assessments_created"], 0)
        self.assertEqual(Assessment.objects.count(), 2)

    def test_regeneration_respects_single_entry_style(self):
        GradingSettings.objects.create(grading_style="single_entry")
        self._add_templates()

        self._generate()
        stats = regenerate_assessments_for_academic_year(
            self.academic_year, created_by=self.actor
        )

        self.assertEqual(stats["assessments_deleted"], 2)
        self.assertEqual(stats["assessments_created"], 2)
        self.assertEqual(
            Assessment.objects.filter(assessment_type__is_single_entry=True).count(), 2
        )

    def test_missing_marking_periods_raises_clear_error(self):
        GradingSettings.objects.create(grading_style="single_entry")
        MarkingPeriod.objects.all().delete()

        with self.assertRaises(ValueError) as raised:
            self._generate()

        self.assertIn("marking period", str(raised.exception).lower())
        self.assertEqual(Assessment.objects.count(), 0)

    def test_multiple_entry_without_templates_raises_clear_error(self):
        GradingSettings.objects.create(grading_style="multiple_entry")

        with self.assertRaises(ValueError) as raised:
            self._generate()

        self.assertIn("template", str(raised.exception).lower())
        self.assertEqual(Assessment.objects.count(), 0)

    def test_invalid_grading_style_raises_clear_error(self):
        GradingSettings.objects.create(grading_style="not_a_style")

        with self.assertRaises(ValueError) as raised:
            self._generate()

        self.assertIn("invalid grading style", str(raised.exception).lower())

    def test_explicit_style_overrides_configured_style(self):
        GradingSettings.objects.create(grading_style="multiple_entry")
        self._add_templates()

        result = generate_assessments_for_gradebook_with_settings(
            self.gradebook, grading_style="single_entry"
        )

        self.assertEqual(result["mode"], "single_entry")
        self.assertEqual(result["assessments_created"], 2)
        self.assertTrue(
            Assessment.objects.filter(assessment_type__is_single_entry=True).exists()
        )
