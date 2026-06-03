from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from common.status import EnrollmentStatus, StudentStatus
from students.services.student_status import (
    apply_status_fields_to_response,
    compute_display_status,
    compute_is_enrolled,
    is_active_enrollment_status,
    is_terminal_lifecycle,
    normalize_enrollment_status,
    normalize_lifecycle_status,
)


class StudentStatusRulesTests(SimpleTestCase):
    def test_terminal_lifecycle(self):
        self.assertTrue(is_terminal_lifecycle(StudentStatus.WITHDRAWN))
        self.assertFalse(is_terminal_lifecycle(StudentStatus.ACTIVE))
        self.assertFalse(is_terminal_lifecycle(StudentStatus.ENROLLED))

    def test_normalize_lifecycle(self):
        self.assertEqual(
            normalize_lifecycle_status(StudentStatus.ENROLLED),
            StudentStatus.ACTIVE,
        )

    def test_active_enrollment_status(self):
        self.assertTrue(is_active_enrollment_status(EnrollmentStatus.PENDING))
        self.assertTrue(is_active_enrollment_status(EnrollmentStatus.ENROLLED))
        self.assertFalse(is_active_enrollment_status(EnrollmentStatus.COMPLETED))
        self.assertFalse(is_active_enrollment_status(EnrollmentStatus.CANCELED))

    def test_normalize_enrollment_status(self):
        self.assertEqual(normalize_enrollment_status("active"), EnrollmentStatus.ENROLLED)
        self.assertEqual(
            normalize_enrollment_status("completed"),
            EnrollmentStatus.COMPLETED,
        )
        self.assertEqual(normalize_enrollment_status("pending"), EnrollmentStatus.PENDING)

    def test_compute_is_enrolled_only_enrolled_row(self):
        student = SimpleNamespace(status=StudentStatus.ACTIVE)
        enrollment = SimpleNamespace(status=EnrollmentStatus.COMPLETED)
        self.assertFalse(
            compute_is_enrolled(student, current_enrollment=enrollment)
        )

        enrollment.status = EnrollmentStatus.PENDING
        self.assertFalse(compute_is_enrolled(student, current_enrollment=enrollment))

        enrollment.status = EnrollmentStatus.ENROLLED
        self.assertTrue(compute_is_enrolled(student, current_enrollment=enrollment))

    def test_compute_is_enrolled_legacy_student_enrolled(self):
        student = SimpleNamespace(status=StudentStatus.ENROLLED)
        enrollment = SimpleNamespace(status=EnrollmentStatus.ENROLLED)
        self.assertTrue(compute_is_enrolled(student, current_enrollment=enrollment))

    def test_display_status(self):
        self.assertEqual(
            compute_display_status(StudentStatus.WITHDRAWN),
            StudentStatus.WITHDRAWN,
        )
        self.assertEqual(
            compute_display_status(
                StudentStatus.ACTIVE,
                enrollment_status=EnrollmentStatus.ENROLLED,
            ),
            EnrollmentStatus.ENROLLED,
        )
        self.assertEqual(
            compute_display_status(
                StudentStatus.ACTIVE,
                enrollment_status=EnrollmentStatus.COMPLETED,
            ),
            EnrollmentStatus.COMPLETED,
        )
        self.assertEqual(
            compute_display_status(StudentStatus.ACTIVE),
            "not enrolled",
        )

    def test_apply_status_fields_to_response(self):
        student = MagicMock()
        student.status = StudentStatus.ACTIVE
        enrollment = SimpleNamespace(status=EnrollmentStatus.ENROLLED)
        response = {}

        with patch(
            "students.services.student_status.compute_is_enrolled",
            return_value=True,
        ):
            apply_status_fields_to_response(
                response,
                student,
                current_enrollment=enrollment,
            )

        self.assertEqual(response["lifecycle_status"], StudentStatus.ACTIVE)
        self.assertEqual(response["enrollment_status"], EnrollmentStatus.ENROLLED)
        self.assertTrue(response["is_enrolled"])
        self.assertEqual(response["status"], EnrollmentStatus.ENROLLED)
