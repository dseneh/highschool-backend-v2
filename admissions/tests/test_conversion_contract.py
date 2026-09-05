from django.test import SimpleTestCase

from admissions.conversion import _guardian_names


class AdmissionConversionContractTests(SimpleTestCase):
    def test_guardian_name_fields_are_preferred(self):
        self.assertEqual(
            _guardian_names({"first_name": "Mary", "last_name": "Doe"}),
            ("Mary", "Doe"),
        )

    def test_single_guardian_name_remains_valid(self):
        self.assertEqual(_guardian_names({"name": "Mary"}), ("Mary", ""))

    def test_missing_guardian_name_has_safe_placeholder(self):
        self.assertEqual(_guardian_names({}), ("Guardian", ""))
