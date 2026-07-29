from django.test import SimpleTestCase
from rest_framework import status

from students.views.discipline import _extract_status_updates


class DisciplineStatusUpdateExtractionTests(SimpleTestCase):
    def test_rejects_student_status_update(self):
        payload = {
            "student": "student-id",
            "title": "Suspension",
            "student_status_update": "SUSPENDED",
        }

        data, student_status_update, error_response = _extract_status_updates(payload)

        self.assertIsNone(data)
        self.assertIsNone(student_status_update)
        self.assertIsNotNone(error_response)
        self.assertEqual(error_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("no longer supported", str(error_response.data.get("detail", "")))

    def test_rejects_enrollment_status_update(self):
        payload = {
            "student": "student-id",
            "title": "Expulsion",
            "enrollment_status_update": "withdrawn",
        }

        data, student_status_update, error_response = _extract_status_updates(payload)

        self.assertIsNone(data)
        self.assertIsNone(student_status_update)
        self.assertIsNotNone(error_response)
        self.assertEqual(error_response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("no longer supported", str(error_response.data.get("detail", "")))

    def test_strips_unsupported_fields_when_empty(self):
        payload = {
            "student": "student-id",
            "title": "Warning",
            "student_status_update": "",
            "enrollment_status_update": "",
        }

        data, student_status_update, error_response = _extract_status_updates(payload)

        self.assertIsNone(error_response)
        self.assertEqual(data["student"], "student-id")
        self.assertEqual(data["title"], "Warning")
        self.assertNotIn("student_status_update", data)
        self.assertNotIn("enrollment_status_update", data)
        self.assertIsNone(student_status_update)
