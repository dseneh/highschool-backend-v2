from datetime import date
from types import SimpleNamespace
from unittest.mock import patch
import uuid

from django.test import SimpleTestCase
from django_tenants.test.cases import TenantTestCase
from django_tenants.utils import schema_context
from rest_framework.exceptions import ValidationError

from core.services.grading_bypass import _json_safe, _validate_outcomes
from core.services.features import feature_access
from core.services.tenant_clone import (
	MODULE_REGISTRY,
	TenantCloneService,
	resolve_modules,
	run_clone_job,
)
from core.models import Tenant, TenantCreationJob


class GradingBypassOutcomeValidationTests(SimpleTestCase):
	def setUp(self):
		self.enrollments = [
			SimpleNamespace(pk="enrollment-1"),
			SimpleNamespace(pk="enrollment-2"),
		]

	def test_requires_one_supported_outcome_for_each_open_enrollment(self):
		outcomes = _validate_outcomes(
			self.enrollments,
			{"enrollment-1": "promoted", "enrollment-2": "repeated"},
		)

		self.assertEqual(outcomes["enrollment-1"], "promoted")
		self.assertEqual(outcomes["enrollment-2"], "repeated")

	def test_rejects_missing_or_unsupported_outcomes(self):
		with self.assertRaises(ValidationError):
			_validate_outcomes(
				self.enrollments,
				{"enrollment-1": "promoted", "enrollment-2": "skip"},
			)

	def test_default_outcome_applies_to_unlisted_enrollments(self):
		outcomes = _validate_outcomes(
			self.enrollments,
			{"enrollment-2": "graduated"},
			default_outcome="promoted",
		)

		self.assertEqual(outcomes["enrollment-1"], "promoted")
		self.assertEqual(outcomes["enrollment-2"], "graduated")

	def test_json_safe_converts_dates_for_operation_audit_storage(self):
		payload = _json_safe({"completion_date": date(2026, 8, 14)})

		self.assertEqual(payload, {"completion_date": "2026-08-14"})


class FeatureAccessTests(SimpleTestCase):
	def test_local_disable_overrides_an_active_commercial_entitlement(self):
		feature = SimpleNamespace(key="payroll")
		entitlement = SimpleNamespace(
			locally_enabled=False,
			status="active",
			active_from=None,
			active_until=None,
		)
		tenant = SimpleNamespace(enabled_addons=[])

		with patch("core.services.features.Feature.objects.get", return_value=feature), patch(
			"core.services.features.TenantFeatureEntitlement.objects.filter",
			return_value=SimpleNamespace(first=lambda: entitlement),
		):
			access = feature_access(tenant, "payroll")

		self.assertFalse(access.enabled)
		self.assertEqual(access.reason, "feature_disabled_by_tenant")

	def test_legacy_addon_remains_available_without_an_entitlement_record(self):
		feature = SimpleNamespace(key="payroll")
		tenant = SimpleNamespace(enabled_addons=["payroll"])

		with patch("core.services.features.Feature.objects.get", return_value=feature), patch(
			"core.services.features.TenantFeatureEntitlement.objects.filter",
			return_value=SimpleNamespace(first=lambda: None),
		):
			access = feature_access(tenant, "payroll")

		self.assertTrue(access.enabled)
		self.assertEqual(access.reason, "legacy_addon")


class TenantCloneModuleTests(SimpleTestCase):
	def test_dependencies_are_explicit_and_required(self):
		with self.assertRaises(ValidationError):
			resolve_modules(["sections"])

		modules = resolve_modules(["grade_levels", "sections", "subjects"])
		self.assertEqual([module.key for module in modules], ["grade_levels", "sections", "subjects"])

	def test_only_selected_modules_are_in_clone_plan(self):
		service = TenantCloneService(
			"source",
			"destination",
			resolve_modules(["grading_configuration"]),
		)

		self.assertIn("grading.GradeLetter", service.model_labels)
		self.assertNotIn("academics.GradeLevel", service.model_labels)
		self.assertNotIn("finance.Transaction", service.model_labels)

	def test_operational_and_identity_models_are_never_registered(self):
		registered = {
			label
			for module in MODULE_REGISTRY.values()
			for label in module.model_labels
		}
		for excluded in {
			"users.User",
			"students.Student",
			"students.Attendance",
			"grading.Grade",
			"finance.Transaction",
			"accounting.AccountingJournalEntry",
			"payroll_v2.PayrollRunRecord",
		}:
			self.assertNotIn(excluded, registered)

	def test_unknown_modules_are_rejected(self):
		with self.assertRaises(ValidationError):
			resolve_modules(["students"])


class TenantCloneIntegrationTests(TenantTestCase):
	"""Exercises ID remapping and transaction boundaries across real schemas."""

	@classmethod
	def setup_tenant(cls, tenant):
		from users.models import User

		tenant.name = "Clone Source"
		tenant.short_name = "source"
		tenant.owner, _ = User.objects.get_or_create(
			email="tenant-clone-test-owner@example.com",
			defaults={
				"username": "tenant-clone-test-owner",
				"id_number": "TENANT-CLONE-TEST-OWNER",
				"role": "admin",
				"first_name": "Clone",
				"last_name": "Owner",
			},
		)

	def _destination(self):
		suffix = uuid.uuid4().hex[:10]
		with schema_context("public"):
			return Tenant.objects.create(
				name=f"Clone Destination {suffix}",
				short_name=f"dest-{suffix}",
				schema_name=f"clone_dest_{suffix}",
				owner=self.tenant.owner,
			)

	def test_selected_models_get_new_ids_and_remapped_foreign_keys(self):
		from academics.models import Division, GradeLevel, Section, SectionSubject, Subject
		from grading.models import GradeLetter

		division = Division.objects.create(name="Primary")
		grade_level = GradeLevel.objects.create(name="Grade 1", level=1, division=division)
		section = Section.objects.create(name="A", grade_level=grade_level)
		subject = Subject.objects.create(name="Mathematics", code="MATH")
		assignment = SectionSubject.objects.create(section=section, subject=subject)
		GradeLetter.objects.create(letter="A", min_percentage=90, max_percentage=100, order=1)
		source_ids = {division.pk, grade_level.pk, section.pk, subject.pk, assignment.pk}

		destination = self._destination()
		try:
			modules = resolve_modules(["grade_levels", "sections", "subjects"])
			service = TenantCloneService(self.tenant.schema_name, destination.schema_name, modules)
			snapshot = service.snapshot_source()
			service.clone(snapshot)

			with schema_context(destination.schema_name):
				cloned_assignment = SectionSubject.objects.select_related(
					"section__grade_level__division", "subject"
				).get()
				destination_ids = {
					cloned_assignment.pk,
					cloned_assignment.section_id,
					cloned_assignment.section.grade_level_id,
					cloned_assignment.subject_id,
				}
				self.assertTrue(source_ids.isdisjoint(destination_ids))
				self.assertEqual(
					cloned_assignment.section.grade_level.division_id,
					division.id,
				)
				self.assertEqual(cloned_assignment.section.grade_level.name, "Grade 1")
				self.assertEqual(cloned_assignment.subject.code, "MATH")
				self.assertEqual(GradeLetter.objects.count(), 0)

			self.assertEqual(Division.objects.filter(pk=division.pk).count(), 1)
			self.assertEqual(SectionSubject.objects.filter(pk=assignment.pk).count(), 1)
		finally:
			from core.services.tenant_deletion import hard_delete_tenant_workspace

			with schema_context("public"):
				hard_delete_tenant_workspace(destination)

	def test_validation_failure_rolls_back_all_cloned_rows(self):
		from academics.models import Division

		Division.objects.create(name="Primary")
		destination = self._destination()
		try:
			service = TenantCloneService(
				self.tenant.schema_name,
				destination.schema_name,
				resolve_modules(["grade_levels"]),
			)
			snapshot = service.snapshot_source()
			with patch.object(service, "_validate", side_effect=ValidationError("invalid clone")):
				with self.assertRaises(ValidationError):
					service.clone(snapshot)

			with schema_context(destination.schema_name):
				from academics.models import GradeLevel

				self.assertEqual(GradeLevel.objects.count(), 0)
		finally:
			from core.services.tenant_deletion import hard_delete_tenant_workspace

			with schema_context("public"):
				hard_delete_tenant_workspace(destination)

	def test_failed_background_clone_cleans_up_destination_and_can_be_retried(self):
		from academics.models import Division

		Division.objects.create(name="Retry Source Division")
		source_division_count = Division.objects.count()
		suffix = uuid.uuid4().hex[:10]
		destination_schema = f"failed_clone_{suffix}"
		payload = {
			"name": f"Failed Clone {suffix}",
			"short_name": f"failed-{suffix}",
			"schema_name": destination_schema,
			"domain": f"{destination_schema}.localhost",
		}
		job = TenantCreationJob.objects.create(
			source_tenant=self.tenant,
			source_schema=self.tenant.schema_name,
			destination_schema=destination_schema,
			requested_by=self.tenant.owner,
			selected_modules=["grade_levels"],
			request_payload=payload,
		)

		with schema_context("public"), patch(
			"core.services.tenant_clone.close_old_connections"
		), patch.object(TenantCloneService, "clone", side_effect=RuntimeError("forced clone failure")):
			run_clone_job(str(job.pk))

		job.refresh_from_db()
		self.assertEqual(job.status, TenantCreationJob.Status.FAILED)
		self.assertIn("forced clone failure", job.failure_detail)
		self.assertFalse(Tenant.objects.filter(schema_name=destination_schema).exists())

		retry = TenantCreationJob.objects.create(
			source_tenant=self.tenant,
			source_schema=self.tenant.schema_name,
			destination_schema=destination_schema,
			requested_by=self.tenant.owner,
			selected_modules=["grade_levels"],
			request_payload=payload,
		)
		self.assertEqual(retry.status, TenantCreationJob.Status.PENDING)
		with schema_context("public"), patch("core.services.tenant_clone.close_old_connections"):
			run_clone_job(str(retry.pk))
		retry.refresh_from_db()
		self.assertEqual(retry.status, TenantCreationJob.Status.COMPLETED)
		self.assertEqual(retry.stage, "Completed")
		self.assertEqual(retry.progress_percent, 100)
		retried_tenant = Tenant.objects.get(schema_name=destination_schema)
		try:
			with schema_context(destination_schema):
				self.assertEqual(Division.objects.count(), source_division_count)
		finally:
			from core.services.tenant_deletion import hard_delete_tenant_workspace

			with schema_context("public"):
				hard_delete_tenant_workspace(retried_tenant)

	def test_standard_tenant_creation_serializer_still_creates_a_workspace(self):
		from core.serializers import CreateTenantSerializer

		suffix = uuid.uuid4().hex[:10]
		schema_name = f"default_create_{suffix}"
		request = type("TestRequest", (), {"user": self.tenant.owner})()
		serializer = CreateTenantSerializer(
			data={
				"name": f"Default Tenant {suffix}",
				"short_name": f"default-{suffix}",
				"schema_name": schema_name,
				"domain": f"{schema_name}.localhost",
			},
			context={"request": request},
		)
		serializer.is_valid(raise_exception=True)
		with schema_context("public"):
			created = serializer.save()
		try:
			self.assertEqual(created.schema_name, schema_name)
			self.assertTrue(Tenant.objects.filter(pk=created.pk).exists())
		finally:
			from core.services.tenant_deletion import hard_delete_tenant_workspace

			with schema_context("public"):
				hard_delete_tenant_workspace(created)

	def test_tenant_creation_maps_shared_division_and_onboarding_preserves_it(self):
		from core.serializers import CreateTenantSerializer, TenantSerializer
		from core.models import Division
		from defaults.services import build_initial_plan

		suffix = uuid.uuid4().hex[:10]
		division = Division.objects.order_by("name").first()
		self.assertIsNotNone(division)
		request = type("TestRequest", (), {"user": self.tenant.owner})()
		serializer = CreateTenantSerializer(
			data={
				"name": f"Division Seed Tenant {suffix}",
				"short_name": f"div-{suffix}",
				"schema_name": f"division_seed_{suffix}",
				"domain": f"division_seed_{suffix}.localhost",
				"school_division": str(division.id),
			},
			context={"request": request},
		)
		serializer.is_valid(raise_exception=True)
		self.assertEqual(serializer.validated_data["school_division"], division)
		captured_tenant_data = {}

		def capture_create(**kwargs):
			captured_tenant_data.update(kwargs)
			raise RuntimeError("stop before schema creation")

		with patch("core.models.Tenant.objects.create", side_effect=capture_create):
			with self.assertRaisesMessage(RuntimeError, "stop before schema creation"):
				serializer.save()
		self.assertEqual(captured_tenant_data["school_division"], division)

		self.tenant.school_division = division
		self.tenant.save(update_fields=["school_division"])
		self.assertEqual(
			TenantSerializer(self.tenant).data["school_division"],
			{"id": str(division.id), "name": division.name},
		)
		plan = build_initial_plan(self.tenant)
		self.assertEqual(
			plan["steps"]["school_profile"]["payload"]["school_division"],
			str(division.id),
		)

	def test_tenant_update_persists_and_returns_shared_division_object(self):
		from academics.serializers import SchoolSerializer
		from core.models import Division
		from core.serializers import PublicTenantSerializer, TenantSerializer
		from core.views import TenantViewSet
		from defaults.services import _apply_school_profile

		division = Division.objects.order_by("name").last()
		serializer = TenantSerializer(
			self.tenant,
			data={"school_division": str(division.id)},
			partial=True,
		)
		serializer.is_valid(raise_exception=True)
		updated = serializer.save()
		updated.refresh_from_db()

		self.assertEqual(updated.school_division_id, division.id)
		self.assertIn("school_division", TenantViewSet.ALLOWED_UPDATE_FIELDS)
		self.assertEqual(
			serializer.data["school_division"],
			{"id": str(division.id), "name": division.name},
		)
		self.assertEqual(
			SchoolSerializer(updated).data["school_division"],
			{"id": str(division.id), "name": division.name},
		)
		self.assertEqual(
			PublicTenantSerializer(updated).data["school_division"],
			{"id": str(division.id), "name": division.name},
		)

		other_division = Division.objects.exclude(pk=division.pk).first()
		result = _apply_school_profile(
			updated, {"school_division": str(other_division.id)}
		)
		updated.refresh_from_db()

		self.assertTrue(result["ok"])
		self.assertEqual(updated.school_division_id, other_division.id)
