from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from payroll_v2.settings_services import (
    SALARY_ADVANCE_FEATURE,
    WARD_SPONSORSHIP_FEATURE,
    ensure_payroll_feature_enabled,
)


class PayrollFeatureGateTests(SimpleTestCase):
    @patch(
        "payroll_v2.settings_services.get_tenant_payroll_settings",
        return_value=SimpleNamespace(allow_salary_advance=False, allow_ward_sponsorship=True),
    )
    def test_disabled_salary_advance_is_rejected_with_settings_message(self, _settings_mock):
        with self.assertRaisesMessage(ValueError, "Salary Advance is disabled in Payroll Settings."):
            ensure_payroll_feature_enabled(SALARY_ADVANCE_FEATURE)

    @patch(
        "payroll_v2.settings_services.get_tenant_payroll_settings",
        return_value=SimpleNamespace(allow_salary_advance=True, allow_ward_sponsorship=False),
    )
    def test_disabled_ward_sponsorship_is_rejected_with_settings_message(self, _settings_mock):
        with self.assertRaisesMessage(ValueError, "Ward Sponsorship is disabled in Payroll Settings."):
            ensure_payroll_feature_enabled(WARD_SPONSORSHIP_FEATURE)

    @patch(
        "payroll_v2.settings_services.get_tenant_payroll_settings",
        return_value=SimpleNamespace(allow_salary_advance=True, allow_ward_sponsorship=False),
    )
    def test_enabled_feature_is_allowed(self, _settings_mock):
        settings = ensure_payroll_feature_enabled(SALARY_ADVANCE_FEATURE)
        self.assertTrue(settings.allow_salary_advance)