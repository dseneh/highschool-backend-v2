"""Tests for employee list stats helpers."""

from django.test import SimpleTestCase

from hr.employee_stats import employee_list_filters_applied


class EmployeeListStatsFilterTests(SimpleTestCase):
    def test_no_filters_when_defaults(self):
        self.assertFalse(
            employee_list_filters_applied(
                {
                    "page": "1",
                    "page_size": "20",
                    "include_stats": "1",
                }
            )
        )

    def test_detects_search_filter(self):
        self.assertTrue(employee_list_filters_applied({"search": "Ada"}))

    def test_detects_status_filter(self):
        self.assertTrue(
            employee_list_filters_applied({"employment_status": "active"})
        )
        self.assertFalse(employee_list_filters_applied({"status": "all"}))

    def test_ignores_internal_manager_lookup(self):
        self.assertFalse(employee_list_filters_applied({"is_manager": "true"}))
