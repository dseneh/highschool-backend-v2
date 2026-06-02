from django.test import SimpleTestCase

from common.utils import (
    ID_ENTITY_EMPLOYEE,
    ID_ENTITY_PARENT,
    ID_ENTITY_STUDENT,
    compute_id_number,
    id_number_prefix,
)


class ComputeIdNumberTests(SimpleTestCase):
    def test_student_ids_for_school_ending_in_1(self):
        self.assertEqual(
            compute_id_number(1, ID_ENTITY_STUDENT, 1),
            "110001",
        )
        self.assertEqual(
            compute_id_number(1, ID_ENTITY_STUDENT, 2),
            "110002",
        )

    def test_employee_ids_for_school_ending_in_1(self):
        self.assertEqual(
            compute_id_number(1, ID_ENTITY_EMPLOYEE, 1),
            "120001",
        )
        self.assertEqual(
            compute_id_number(1, ID_ENTITY_EMPLOYEE, 2),
            "120002",
        )

    def test_parent_ids_for_school_ending_in_1(self):
        self.assertEqual(
            compute_id_number(1, ID_ENTITY_PARENT, 1),
            "130001",
        )
        self.assertEqual(
            compute_id_number(1, ID_ENTITY_PARENT, 2),
            "130002",
        )

    def test_sequence_expands_after_9999(self):
        self.assertEqual(
            compute_id_number(1, ID_ENTITY_STUDENT, 9999),
            "119999",
        )
        self.assertEqual(
            compute_id_number(1, ID_ENTITY_STUDENT, 10000),
            "1110000",
        )

    def test_prefix_is_school_digit_plus_entity_type(self):
        self.assertEqual(id_number_prefix(1, ID_ENTITY_STUDENT), "11")
        self.assertEqual(id_number_prefix(1, ID_ENTITY_EMPLOYEE), "12")
        self.assertEqual(id_number_prefix(1, ID_ENTITY_PARENT), "13")
