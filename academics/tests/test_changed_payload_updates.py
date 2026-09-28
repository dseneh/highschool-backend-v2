from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import SimpleTestCase

from academics.models import GradeLevelTuitionFee
from academics.views.section_time_slot import SectionTimeSlotDetailView
from business.core.adapters.supporting_adapter import bulk_update_tuition_fees
from users.models import User


class TuitionChangedPayloadTests(SimpleTestCase):
    def call_bulk_update(self, grade_level, updates, user):
        return bulk_update_tuition_fees.__wrapped__(grade_level, updates, user)

    @patch("common.cache_service.DataCache.invalidate_grade_levels")
    @patch("business.core.adapters.supporting_adapter.GradeLevelTuitionFee.objects.get")
    def test_unchanged_tuition_is_not_saved(self, get_fee, invalidate):
        fee = SimpleNamespace(amount=Decimal("100.00"), save=Mock())
        get_fee.return_value = fee

        result = self.call_bulk_update(
            SimpleNamespace(id="grade-1"),
            [{"id": "fee-1", "amount": 100}],
            SimpleNamespace(id="user-1"),
        )

        self.assertEqual(result, [])
        fee.save.assert_not_called()
        invalidate.assert_not_called()

    @patch("common.cache_service.DataCache.invalidate_grade_levels")
    @patch("business.core.adapters.supporting_adapter.GradeLevelTuitionFee.objects.get")
    def test_changed_tuition_uses_targeted_update_fields(self, get_fee, invalidate):
        fee = GradeLevelTuitionFee(amount=Decimal("100.00"))
        fee.save = Mock()
        get_fee.return_value = fee
        user = User(username="tuition-editor")

        result = self.call_bulk_update(
            SimpleNamespace(id="grade-1"),
            [{"id": "fee-1", "amount": "125.00"}],
            user,
        )

        self.assertEqual(result, [fee])
        self.assertEqual(fee.amount, Decimal("125.00"))
        self.assertIs(fee.updated_by, user)
        fee.save.assert_called_once_with(
            update_fields=["amount", "updated_by", "updated_at"],
        )
        invalidate.assert_called_once_with()


class SectionTimeSlotPartialUpdateTests(SimpleTestCase):
    def test_patch_is_supported(self):
        self.assertTrue(callable(getattr(SectionTimeSlotDetailView, "patch", None)))
