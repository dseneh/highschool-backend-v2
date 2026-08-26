from django.test import SimpleTestCase

from grading.serializers import normalize_grade_workflow_status


class GradeWorkflowStatusSerializationTests(SimpleTestCase):
    def test_accepts_only_grade_workflow_statuses(self):
        for status in (
            "draft",
            "pending",
            "submitted",
            "reviewed",
            "approved",
            "rejected",
        ):
            with self.subTest(status=status):
                self.assertEqual(normalize_grade_workflow_status(status), status)

    def test_rejects_student_and_account_statuses(self):
        for status in (None, "", "active", "inactive", "suspended"):
            with self.subTest(status=status):
                self.assertIsNone(normalize_grade_workflow_status(status))
