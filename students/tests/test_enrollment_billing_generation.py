from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from students.views.utils import create_student_bill


class CreateStudentBillBroughtForwardTests(SimpleTestCase):
    @patch("students.views.utils.get_enrollment_arrears_amount", return_value=Decimal("0.00"))
    def test_create_student_bill_prepends_zero_brought_forward_item(self, _mock_arrears):
        created_rows = []

        def create_bill(**kwargs):
            created_rows.append(kwargs)
            return kwargs

        section_fee = SimpleNamespace(
            amount=Decimal("50.00"),
            general_fee=SimpleNamespace(name="PTA", student_target="", description=""),
        )
        tuition_fee = SimpleNamespace(amount=Decimal("400.00"))
        enrollment = SimpleNamespace(
            enrolled_as="new",
            section=SimpleNamespace(
                section_fees=SimpleNamespace(
                    select_related=MagicMock(
                        return_value=SimpleNamespace(filter=MagicMock(return_value=[section_fee]))
                    )
                )
            ),
            grade_level=SimpleNamespace(
                tuition_fees=SimpleNamespace(
                    filter=MagicMock(
                        return_value=SimpleNamespace(first=MagicMock(return_value=tuition_fee))
                    )
                )
            ),
            student_bills=SimpleNamespace(create=create_bill),
        )
        request = SimpleNamespace(user=MagicMock())

        bills = create_student_bill(enrollment, request)

        self.assertEqual(created_rows[0]["name"], "Brought Forward")
        self.assertEqual(created_rows[0]["amount"], Decimal("0.00"))
        self.assertEqual(created_rows[0]["type"], "other")
        self.assertEqual(created_rows[1]["name"], "PTA")
        self.assertEqual(created_rows[2]["name"], "Tuition")
        self.assertEqual(len(bills), 3)
