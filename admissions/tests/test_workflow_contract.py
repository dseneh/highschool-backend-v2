from django.test import SimpleTestCase

from admissions.enums import ApplicationStatus
from admissions.request_ids import generate_request_id
from admissions.services import ALLOWED_TRANSITIONS


class AdmissionWorkflowContractTests(SimpleTestCase):
    def test_approval_does_not_transition_directly_to_enrolled(self):
        self.assertNotIn(
            ApplicationStatus.ENROLLED,
            ALLOWED_TRANSITIONS[ApplicationStatus.APPROVED],
        )
        self.assertIn(
            ApplicationStatus.ENROLLMENT_READY,
            ALLOWED_TRANSITIONS[ApplicationStatus.APPROVED],
        )

    def test_terminal_states_have_no_outgoing_transitions(self):
        for terminal in (
            ApplicationStatus.REJECTED,
            ApplicationStatus.WITHDRAWN,
            ApplicationStatus.ENROLLED,
            ApplicationStatus.CANCELLED,
        ):
            self.assertEqual(ALLOWED_TRANSITIONS[terminal], set())

    def test_request_ids_are_readable_and_not_sequential(self):
        values = {generate_request_id() for _ in range(50)}
        self.assertEqual(len(values), 50)
        for value in values:
            self.assertRegex(value, r"^EZY-[0-9A-F]{6}-[0-9A-F]{6}$")
