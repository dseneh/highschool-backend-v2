"""Tests for student identifier lookup."""

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from students.services.student_lookup import (
    get_student_by_identifier,
    get_student_by_identifier_or_none,
)


class StudentLookupTests(SimpleTestCase):
    @patch("students.services.student_lookup.Student.objects")
    def test_lookup_by_id_number(self, mock_objects):
        student = SimpleNamespace(id_number="10001")
        mock_objects.filter.return_value.first.side_effect = [student, None]

        result = get_student_by_identifier("10001")

        self.assertIs(result, student)
        mock_objects.filter.assert_any_call(id_number="10001")

    @patch("students.services.student_lookup.Student.objects")
    def test_lookup_by_uuid(self, mock_objects):
        student_id = uuid.uuid4()
        student = SimpleNamespace(pk=student_id)
        mock_objects.filter.return_value.first.return_value = student

        result = get_student_by_identifier(str(student_id))

        self.assertIs(result, student)
        mock_objects.filter.assert_called_with(pk=student_id)

    @patch("students.services.student_lookup.Student.objects")
    def test_lookup_does_not_query_uuid_for_numeric_id_number(self, mock_objects):
        mock_qs = MagicMock()
        mock_qs.first.return_value = None
        mock_objects.filter.return_value = mock_qs

        result = get_student_by_identifier_or_none("10001")

        self.assertIsNone(result)
        mock_objects.filter.assert_any_call(id_number="10001")
        for call in mock_objects.filter.call_args_list:
            self.assertNotIn("pk", call.kwargs)

    @patch("students.services.student_lookup.Student.objects")
    def test_lookup_raises_when_missing(self, mock_objects):
        mock_qs = MagicMock()
        mock_qs.first.return_value = None
        mock_objects.filter.return_value = mock_qs

        with self.assertRaises(Exception):
            get_student_by_identifier("missing")
