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
)
from defaults.services import (
	OnboardingConfigurationError,
	_apply_grading,
	_apply_subjects,
	_generate_onboarding_gradebooks,
)
from grading.models import Assessment, GradeBook
from settings.models import GradingSettings
from users.models import User


class OnboardingGradingSetupTests(TenantTestCase):
	@classmethod
	def setup_tenant(cls, tenant):
		tenant.name = "Onboarding Grading Test School"
		tenant.id_number = "OGT001"
		tenant.owner, _ = User.objects.get_or_create(
			email="onboarding-grading@example.com",
			defaults={
				"username": "onboarding-grading",
				"id_number": "ONBOARDING-GRADING-001",
				"role": "admin",
			},
		)

	def setUp(self):
		self.user = self.tenant.owner
		self.academic_year = AcademicYear.objects.create(
			name="2026-2027",
			start_date=date(2026, 9, 1),
			end_date=date(2027, 6, 30),
			current=True,
		)
		semester = Semester.objects.create(
			academic_year=self.academic_year,
			name="Semester 1",
			start_date=date(2026, 9, 1),
			end_date=date(2027, 1, 31),
		)
		self.marking_period = MarkingPeriod.objects.create(
			semester=semester,
			name="First Period",
			start_date=date(2026, 9, 1),
			end_date=date(2026, 11, 30),
		)
		division = Division.objects.create(name="Elementary")
		grade_level = GradeLevel.objects.create(
			name="Grade 1", level=1, division=division
		)
		self.sections = [
			Section.objects.create(name="A", grade_level=grade_level),
			Section.objects.create(name="B", grade_level=grade_level),
		]
		self.subject_payload = {
			"subjects": [
				{
					"name": "Mathematics",
					"code": "MATH",
					"description": "Mathematics",
				}
			]
		}

	def _apply_style(self, grading_style):
		return _apply_grading(
			self.tenant,
			self.user,
			{
				"grading_style": grading_style,
				"grade_letters": [],
				"assessment_types": [],
			},
		)

	def test_multiple_entry_onboarding_assigns_subjects_and_generates_gradebooks(self):
		subject_result = _apply_subjects(
			self.tenant, self.user, self.subject_payload
		)
		grading_result = self._apply_style("multiple_entry")
		generation_result = _generate_onboarding_gradebooks(
			self.user, grading_result["grading_style"]
		)

		self.assertEqual(subject_result["subject_assignments_created"], 2)
		self.assertEqual(SectionSubject.objects.count(), 2)
		self.assertEqual(GradeBook.objects.count(), 2)
		self.assertGreater(Assessment.objects.count(), 2)
		self.assertFalse(
			Assessment.objects.filter(assessment_type__is_single_entry=True).exists()
		)
		self.assertEqual(
			GradingSettings.objects.get().grading_style, "multiple_entry"
		)
		self.assertTrue(generation_result["success"])

		_apply_subjects(self.tenant, self.user, self.subject_payload)
		retry_result = _generate_onboarding_gradebooks(
			self.user, "multiple_entry"
		)

		self.assertEqual(SectionSubject.objects.count(), 2)
		self.assertEqual(GradeBook.objects.count(), 2)
		self.assertEqual(retry_result["stats"]["gradebooks_created"], 0)

	def test_single_entry_onboarding_generates_one_assessment_per_scope(self):
		_apply_subjects(self.tenant, self.user, self.subject_payload)
		grading_result = self._apply_style("single_entry")

		result = _generate_onboarding_gradebooks(
			self.user, grading_result["grading_style"]
		)

		self.assertTrue(result["success"])
		self.assertEqual(GradeBook.objects.count(), 2)
		self.assertEqual(Assessment.objects.count(), 2)
		self.assertEqual(
			Assessment.objects.filter(
				assessment_type__is_single_entry=True,
				marking_period=self.marking_period,
			).count(),
			2,
		)
		self.assertEqual(
			GradingSettings.objects.get().grading_style, "single_entry"
		)

	def test_generation_returns_clear_error_when_calendar_is_incomplete(self):
		_apply_subjects(self.tenant, self.user, self.subject_payload)
		self._apply_style("single_entry")
		MarkingPeriod.objects.all().delete()

		with self.assertRaisesMessage(
			OnboardingConfigurationError, "No active marking periods"
		) as error:
			_generate_onboarding_gradebooks(self.user, "single_entry")

		self.assertEqual(error.exception.error_code, "NO_MARKING_PERIODS")
