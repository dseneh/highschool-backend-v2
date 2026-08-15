from datetime import date
from types import SimpleNamespace

from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError

from core.services.grading_bypass import _json_safe, _validate_outcomes


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
