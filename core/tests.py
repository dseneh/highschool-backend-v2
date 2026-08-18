from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError

from core.services.grading_bypass import _json_safe, _validate_outcomes
from core.services.features import feature_access


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
