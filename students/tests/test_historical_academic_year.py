"""Tests for historical academic year resolution."""

from django.test import SimpleTestCase

from students.services.historical_academic_year import normalize_academic_year_name


class HistoricalAcademicYearTests(SimpleTestCase):
    def test_normalize_academic_year_name(self):
        self.assertEqual(normalize_academic_year_name("2024-2025"), "2024-2025")
        self.assertEqual(normalize_academic_year_name("2024/2025"), "2024-2025")
        self.assertEqual(normalize_academic_year_name(" 2023 - 2024 "), "2023-2024")
