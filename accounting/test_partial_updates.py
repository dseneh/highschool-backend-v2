from contextlib import nullcontext
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from django.test import SimpleTestCase
from rest_framework import serializers
from rest_framework.test import APIRequestFactory

from accounting.models import AccountingCashTransaction, AccountingTransactionType
from accounting.serializers import AccountingCashTransactionSerializer
from accounting.views.cash_transaction import AccountingCashTransactionViewSet
from common.update_utils import validate_partial_update
from finance.views.transaction import TransactionViewSet


class CashTransactionPartialUpdateTests(SimpleTestCase):
    def setUp(self):
        self.transaction_type = AccountingTransactionType(
            code="TUITION", name="Tuition", transaction_category="income"
        )
        self.instance = AccountingCashTransaction(
            transaction_type=self.transaction_type,
            transaction_date=date(2026, 9, 1),
            reference_number="TXN-TEST",
            amount=Decimal("50.00"),
            exchange_rate=Decimal("2.00"),
            base_amount=Decimal("100.00"),
            description="Existing payment",
            notes="Old note",
        )
        self.instance.save = Mock()

    def update_serializer(self, payload):
        return validate_partial_update(
            AccountingCashTransactionSerializer, self.instance, payload
        )

    def test_notes_only_does_not_require_or_write_other_fields(self):
        serializer = self.update_serializer({"notes": "Corrected note"})
        self.assertEqual(serializer.validated_data, {"notes": "Corrected note"})
        serializer.save()
        self.assertEqual(self.instance.notes, "Corrected note")
        self.assertEqual(self.instance.transaction_type, self.transaction_type)
        self.assertEqual(self.instance.base_amount, Decimal("100.00"))
        self.instance.save.assert_called_once_with(update_fields=["notes", "updated_at"])

    def test_amount_only_does_not_overwrite_omitted_base_amount(self):
        serializer = self.update_serializer({"amount": "75.00"})
        self.assertEqual(serializer.validated_data, {"amount": Decimal("75.00")})
        serializer.save()
        self.assertEqual(self.instance.exchange_rate, Decimal("2.00"))
        self.assertEqual(self.instance.base_amount, Decimal("100.00"))
        self.instance.save.assert_called_once_with(update_fields=["amount", "updated_at"])

    def test_rate_only_does_not_inject_amount_or_base_amount(self):
        serializer = self.update_serializer({"exchange_rate": "3.00"})
        self.assertEqual(serializer.validated_data, {"exchange_rate": Decimal("3.00")})

    def test_explicit_base_amount_is_saved(self):
        serializer = self.update_serializer({"amount": "75.00", "base_amount": "150.00"})
        serializer.save()
        self.assertEqual(self.instance.base_amount, Decimal("150.00"))
        self.assertEqual(
            set(self.instance.save.call_args.kwargs["update_fields"]),
            {"amount", "base_amount", "updated_at"},
        )

    def test_unchanged_or_empty_payload_skips_model_save(self):
        for payload in ({}, {"notes": "Old note"}):
            with self.subTest(payload=payload):
                self.update_serializer(payload).save()
                self.instance.save.assert_not_called()

    def test_explicit_null_clears_nullable_fields(self):
        for field in ("notes", "ledger_account", "student_id"):
            with self.subTest(field=field):
                serializer = self.update_serializer({field: None})
                model_field = "student" if field == "student_id" else field
                self.assertEqual(serializer.validated_data, {model_field: None})

    def test_required_relations_reject_explicit_null_for_alias_and_id(self):
        for field in ("transaction_type", "bank_account", "payment_method", "currency"):
            for key in (field, f"{field}_id"):
                with self.subTest(key=key):
                    with self.assertRaises(serializers.ValidationError) as error:
                        self.update_serializer({key: None})
                    self.assertIn(f"{field}_id", error.exception.detail)
        self.instance.save.assert_not_called()

    def test_invalid_amount_and_exchange_rate_are_rejected(self):
        for field in ("amount", "exchange_rate"):
            for value in ("0", "-1", "invalid"):
                with self.subTest(field=field, value=value):
                    with self.assertRaises(serializers.ValidationError) as error:
                        self.update_serializer({field: value})
                    self.assertIn(field, error.exception.detail)
        self.instance.save.assert_not_called()

    def test_unknown_transaction_type_is_rejected(self):
        queryset = AccountingTransactionType.objects.none()
        with patch.object(queryset.__class__, "get", side_effect=AccountingTransactionType.DoesNotExist):
            with self.assertRaises(serializers.ValidationError) as error:
                self.update_serializer({"transaction_type": str(uuid4())})
        self.assertIn("transaction_type_id", error.exception.detail)
        self.instance.save.assert_not_called()

    @patch("accounting.services.student_resolution.resolve_student_pk_from_identifier")
    def test_source_reference_edit_does_not_reassign_student(self, resolve_student):
        resolve_student.return_value = None
        reference = str(uuid4())
        serializer = self.update_serializer({"source_reference": reference})
        self.assertEqual(serializer.validated_data, {"source_reference": reference})
        self.assertNotIn(reference, [call.args[0] for call in resolve_student.call_args_list])

    def test_create_still_requires_fields(self):
        serializer = AccountingCashTransactionSerializer(data={"notes": "New payment"})
        self.assertFalse(serializer.is_valid())
        for field in ("bank_account_id", "payment_method_id", "currency_id", "amount"):
            self.assertIn(field, serializer.errors)
        with self.assertRaises(serializers.ValidationError) as error:
            serializer.validate({"amount": Decimal("50.00")})
        self.assertIn("transaction_type", error.exception.detail)

    def test_create_still_derives_base_amount(self):
        serializer = AccountingCashTransactionSerializer()
        data = serializer.validate({
            "transaction_type": self.transaction_type,
            "amount": Decimal("50.00"),
            "exchange_rate": Decimal("2.00"),
        })
        self.assertEqual(data["base_amount"], Decimal("100.00"))

    @patch("accounting.serializers.resolve_student_refund_transaction_type")
    def test_explicit_refund_mapping_still_changes_type(self, resolve_refund):
        refund_type = AccountingTransactionType(
            code="REFUND", name="Refund", transaction_category="expense"
        )
        resolve_refund.return_value = refund_type
        serializer = self.update_serializer({"use_student_refund_mapping": True})
        serializer.save()
        self.assertEqual(self.instance.transaction_type, refund_type)
        self.instance.save.assert_called_once_with(update_fields=["transaction_type", "updated_at"])

    def test_put_and_patch_accept_notes_without_transaction_type(self):
        factory = APIRequestFactory()
        view = AccountingCashTransactionViewSet.as_view(
            {"put": "update", "patch": "partial_update"},
            authentication_classes=[], permission_classes=[],
        )
        for method in ("put", "patch"):
            with self.subTest(method=method):
                request = getattr(factory, method)(
                    "/cash-transactions/example/", {"notes": f"Edited by {method}"}, format="json"
                )
                with patch.object(
                    AccountingCashTransactionViewSet, "get_object", return_value=self.instance
                ), patch.object(
                    AccountingCashTransactionViewSet, "_validate_editable", return_value=None
                ), patch.object(
                    AccountingCashTransactionViewSet, "perform_update",
                    side_effect=lambda serializer: serializer.save(),
                ) as perform_update, patch.object(
                    self.instance, "refresh_from_db"
                ), patch.object(
                    AccountingCashTransactionSerializer, "to_representation",
                    side_effect=lambda instance: {"notes": instance.notes},
                ):
                    response = view(request, pk=str(self.instance.pk))
                self.assertEqual(response.status_code, 200, response.data)
                self.assertEqual(response.data, {"notes": f"Edited by {method}"})
                perform_update.assert_called_once()

    def test_invalid_put_and_patch_never_reach_save_hook(self):
        factory = APIRequestFactory()
        view = AccountingCashTransactionViewSet.as_view(
            {"put": "update", "patch": "partial_update"},
            authentication_classes=[], permission_classes=[],
        )
        for method in ("put", "patch"):
            with self.subTest(method=method):
                request = getattr(factory, method)(
                    "/cash-transactions/example/", {"amount": "-1"}, format="json"
                )
                with patch.object(
                    AccountingCashTransactionViewSet, "get_object", return_value=self.instance
                ), patch.object(
                    AccountingCashTransactionViewSet, "_validate_editable", return_value=None
                ), patch.object(AccountingCashTransactionViewSet, "perform_update") as perform_update:
                    response = view(request, pk=str(self.instance.pk))
                self.assertEqual(response.status_code, 400, response.data)
                perform_update.assert_not_called()

    def test_finance_fallback_accepts_partial_fields_for_put_and_patch(self):
        view = TransactionViewSet()
        for partial in (False, True):
            with self.subTest(partial=partial):
                request = SimpleNamespace(data={"notes": "Finance edit"}, user=None)
                with patch(
                    "finance.views.transaction.AccountingCashTransaction.objects.select_related"
                ) as query, patch(
                    "finance.views.transaction.transaction.atomic", return_value=nullcontext()
                ):
                    query.return_value.get.return_value = self.instance
                    response = view._update_accounting_transaction(
                        request, self.instance.pk, partial=partial
                    )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(self.instance.notes, "Finance edit")
                self.assertEqual(self.instance.transaction_type, self.transaction_type)

    def test_finance_alias_does_not_hide_invalid_explicit_null(self):
        request = SimpleNamespace(data={"type": None}, user=None)
        with patch(
            "finance.views.transaction.AccountingCashTransaction.objects.select_related"
        ) as query:
            query.return_value.get.return_value = self.instance
            with self.assertRaises(serializers.ValidationError) as error:
                TransactionViewSet()._update_accounting_transaction(request, self.instance.pk)
        self.assertIn("transaction_type_id", error.exception.detail)
        self.instance.save.assert_not_called()
