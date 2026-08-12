from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from payroll_v2.services import persisted_compensation_or_none


class PersistedCompensationGuardTests(SimpleTestCase):
    @patch("payroll_v2.services.EmployeeCompensation.objects.filter")
    def test_returns_none_when_compensation_row_missing(self, compensation_filter):
        compensation_filter.return_value.exists.return_value = False

        compensation = SimpleNamespace(id="538e805a-5744-4071-b056-8b60d5a5b323")

        self.assertIsNone(persisted_compensation_or_none(compensation))

    @patch("payroll_v2.services.EmployeeCompensation.objects.filter")
    def test_returns_compensation_when_row_exists(self, compensation_filter):
        compensation_filter.return_value.exists.return_value = True

        compensation = SimpleNamespace(id="538e805a-5744-4071-b056-8b60d5a5b323")

        self.assertIs(persisted_compensation_or_none(compensation), compensation)

    def test_returns_none_for_unsaved_compensation(self):
        compensation = SimpleNamespace(id=None)

        self.assertIsNone(persisted_compensation_or_none(compensation))