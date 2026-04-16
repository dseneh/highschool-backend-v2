from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from accounting.access_policies import (
    AccountingFinanceAccessPolicy,
    AccountingTransactionAccessPolicy,
)
from accounting.models import (
    AccountingAccountTransfer,
    AccountingBankAccount,
    AccountingCashTransaction,
    AccountingJournalEntry,
    AccountingPaymentMethod,
    AccountingTransactionType,
)
from accounting.serializers import (
    AccountingBankAccountDetailSerializer,
    AccountingBankAccountSerializer,
    AccountingAccountTransferSerializer,
    AccountingCashTransactionSerializer,
    AccountingPaymentMethodSerializer,
    AccountingTransactionTypeSerializer,
)
from accounting.services import (
    post_cash_transaction_to_ledger,
    recalculate_bank_account_current_balance,
    reverse_cash_transaction_journal_entry,
)
from accounting.views.base import AccountingErrorFormattingMixin


def _delete_transfer_bundle(transfer: AccountingAccountTransfer) -> None:
    """Delete a transfer and all linked cash transactions/journal entries atomically."""
    linked_transactions = AccountingCashTransaction.objects.filter(
        source_reference=transfer.reference_number
    )

    bank_account_ids = list(
        linked_transactions.values_list("bank_account_id", flat=True).distinct()
    )

    journal_entry_ids = list(
        linked_transactions.exclude(journal_entry_id__isnull=True)
        .values_list("journal_entry_id", flat=True)
        .distinct()
    )

    linked_transactions.delete()

    if journal_entry_ids:
        AccountingJournalEntry.objects.filter(id__in=journal_entry_ids).delete()

    transfer.delete()

    for account in AccountingBankAccount.objects.filter(id__in=bank_account_ids):
        recalculate_bank_account_current_balance(account)


class AccountingTransactionTypeViewSet(AccountingErrorFormattingMixin, viewsets.ModelViewSet):
    queryset = AccountingTransactionType.objects.select_related("default_ledger_account").order_by("name")
    serializer_class = AccountingTransactionTypeSerializer
    permission_classes = [AccountingFinanceAccessPolicy]
    pagination_class = None


class AccountingPaymentMethodViewSet(AccountingErrorFormattingMixin, viewsets.ReadOnlyModelViewSet):
    queryset = AccountingPaymentMethod.objects.filter(is_active=True).order_by("name")
    serializer_class = AccountingPaymentMethodSerializer
    permission_classes = [AccountingFinanceAccessPolicy]
    pagination_class = None


class AccountingBankAccountViewSet(AccountingErrorFormattingMixin, viewsets.ModelViewSet):
    queryset = AccountingBankAccount.objects.select_related("currency", "ledger_account").order_by("account_name")
    serializer_class = AccountingBankAccountSerializer
    permission_classes = [AccountingFinanceAccessPolicy]
    pagination_class = None

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(queryset, many=True)

        balances_by_currency: dict[str, dict[str, object]] = {}
        for account in queryset:
            currency = account.currency
            key = str(currency.id)
            if key not in balances_by_currency:
                balances_by_currency[key] = {
                    "currency_id": key,
                    "currency_code": currency.code,
                    "currency_symbol": currency.symbol,
                    "total_balance": Decimal("0"),
                }
            balances_by_currency[key]["total_balance"] = (
                Decimal(str(balances_by_currency[key]["total_balance"]))
                + Decimal(str(account.current_balance or 0))
            )

        summary = {
            "total_accounts": len(queryset),
            "active_accounts": sum(1 for account in queryset if account.status == AccountingBankAccount.AccountStatus.ACTIVE),
            "cash_accounts": sum(1 for account in queryset if account.account_type == "cash"),
            "balances_by_currency": [
                {
                    **item,
                    "total_balance": str(item["total_balance"]),
                }
                for item in balances_by_currency.values()
            ],
        }

        return Response({
            "results": serializer.data,
            "summary": summary,
        })

    def get_serializer_class(self):
        if self.action == "retrieve":
            return AccountingBankAccountDetailSerializer
        return super().get_serializer_class()


class AccountingCashTransactionViewSet(AccountingErrorFormattingMixin, viewsets.ModelViewSet):
    queryset = AccountingCashTransaction.objects.select_related(
        "transaction_type",
        "payment_method",
        "bank_account",
        "currency",
        "ledger_account",
        "journal_entry",
    ).order_by("-transaction_date", "-created_at")
    serializer_class = AccountingCashTransactionSerializer
    permission_classes = [AccountingTransactionAccessPolicy]

    @staticmethod
    def _to_bool(value):
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        if isinstance(value, int):
            return value == 1
        return False

    def get_queryset(self):
        queryset = super().get_queryset()
        category = self.request.query_params.get("category")
        status_param = self.request.query_params.get("status")
        bank_account = self.request.query_params.get("bank_account")
        transaction_type = self.request.query_params.get("transaction_type")
        start_date = self.request.query_params.get("start_date")
        end_date = self.request.query_params.get("end_date")
        amount = self.request.query_params.get("amount")
        amount_min = self.request.query_params.get("amount_min")
        amount_max = self.request.query_params.get("amount_max")

        if category:
            queryset = queryset.filter(transaction_type__transaction_category=category)
        if status_param:
            queryset = queryset.filter(status=status_param)
        if bank_account:
            queryset = queryset.filter(bank_account_id=bank_account)
        if transaction_type:
            queryset = queryset.filter(transaction_type_id=transaction_type)
        transaction_type_code = self.request.query_params.get("transaction_type_code")
        if transaction_type_code:
            queryset = queryset.filter(transaction_type__code=transaction_type_code)
        if start_date:
            queryset = queryset.filter(transaction_date__gte=start_date)
        if end_date:
            queryset = queryset.filter(transaction_date__lte=end_date)
        if amount:
            try:
                queryset = queryset.filter(amount=Decimal(amount))
            except (InvalidOperation, TypeError):
                pass
        if amount_min:
            try:
                queryset = queryset.filter(amount__gte=Decimal(amount_min))
            except (InvalidOperation, TypeError):
                pass
        if amount_max:
            try:
                queryset = queryset.filter(amount__lte=Decimal(amount_max))
            except (InvalidOperation, TypeError):
                pass

        return queryset

    def _update_status(
        self,
        cash_transaction,
        new_status,
        rejection_reason=None,
        prevent_journal_posting=False,
    ):
        valid_statuses = {
            AccountingCashTransaction.TransactionStatus.PENDING,
            AccountingCashTransaction.TransactionStatus.APPROVED,
            AccountingCashTransaction.TransactionStatus.REJECTED,
        }

        if new_status not in valid_statuses:
            return Response(
                {"detail": f"Invalid status. Allowed: {', '.join(sorted(valid_statuses))}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        previous_status = cash_transaction.status
        try:
            with transaction.atomic():
                cash_transaction.status = new_status
                if new_status == AccountingCashTransaction.TransactionStatus.REJECTED:
                    cash_transaction.rejection_reason = rejection_reason or cash_transaction.rejection_reason
                else:
                    cash_transaction.rejection_reason = None

                cash_transaction.save(update_fields=["status", "rejection_reason", "updated_at"])

                # Auto-post on approval.
                if (
                    previous_status != AccountingCashTransaction.TransactionStatus.APPROVED
                    and new_status == AccountingCashTransaction.TransactionStatus.APPROVED
                    and not prevent_journal_posting
                ):
                    post_cash_transaction_to_ledger(cash_transaction, actor=self.request.user)

                # Reverse and unlink journal entry if status moves away from approved.
                if (
                    previous_status == AccountingCashTransaction.TransactionStatus.APPROVED
                    and new_status != AccountingCashTransaction.TransactionStatus.APPROVED
                ):
                    reverse_cash_transaction_journal_entry(cash_transaction, actor=self.request.user)
        except ValidationError as exc:
            message = exc.messages[0] if hasattr(exc, "messages") and exc.messages else str(exc)
            return Response({"detail": message}, status=status.HTTP_400_BAD_REQUEST)

        approved_status = AccountingCashTransaction.TransactionStatus.APPROVED
        if previous_status != new_status and (previous_status == approved_status or new_status == approved_status):
            recalculate_bank_account_current_balance(cash_transaction.bank_account)

        return Response(self.get_serializer(cash_transaction).data, status=status.HTTP_200_OK)

    def perform_create(self, serializer):
        """Validate student balance before creating an income transaction linked to a student."""
        from academics.models import AcademicYear
        from finance.validators import get_student_net_remaining_balance
        from students.models.student import Student

        data = serializer.validated_data
        transaction_type = data.get("transaction_type")
        source_reference = (data.get("source_reference") or "").strip()
        amount = data.get("amount")

        if (
            transaction_type
            and transaction_type.transaction_category == "income"
            and source_reference
            and amount is not None
        ):
            student = Student.objects.filter(
                Q(id=source_reference)
                | Q(id_number=source_reference)
                | Q(prev_id_number=source_reference)
            ).first()
            if student:
                tx_date = data.get("transaction_date")
                academic_year = (
                    AcademicYear.objects.filter(
                        Q(start_date__lte=tx_date) & Q(end_date__gte=tx_date)
                    ).first()
                    if tx_date
                    else None
                ) or AcademicYear.objects.filter(current=True).first()

                if academic_year:
                    remaining = get_student_net_remaining_balance(student, academic_year)

                    if remaining <= 0:
                        raise serializers.ValidationError(
                            {"detail": "Student has no balance due. Cannot create transaction."}
                        )

                    if Decimal(str(amount)) > remaining:
                        raise serializers.ValidationError(
                            {"detail": f"Payment amount of {amount:,.2f} exceeds student balance due of {remaining:,.2f}."}
                        )

        cash_transaction = serializer.save()
        if cash_transaction.status == AccountingCashTransaction.TransactionStatus.APPROVED:
            post_cash_transaction_to_ledger(cash_transaction, actor=self.request.user)
            recalculate_bank_account_current_balance(cash_transaction.bank_account)

    def _validate_editable(self, cash_transaction):
        if cash_transaction.journal_entry_id:
            return Response(
                {
                    "detail": (
                        "Posted transactions are immutable because they are already journalized. "
                        "Create a reversing entry and re-enter the corrected transaction."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if cash_transaction.status == AccountingCashTransaction.TransactionStatus.APPROVED:
            return Response(
                {"detail": "Approved transactions cannot be edited. Move to pending/rejected first if needed."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return None

    def update(self, request, *args, **kwargs):
        cash_transaction = self.get_object()
        error_response = self._validate_editable(cash_transaction)
        if error_response:
            return error_response
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        cash_transaction = self.get_object()
        error_response = self._validate_editable(cash_transaction)
        if error_response:
            return error_response
        return super().partial_update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        cash_transaction = self.get_object()

        transfer = None
        if cash_transaction.source_reference:
            transfer = AccountingAccountTransfer.objects.filter(
                reference_number=cash_transaction.source_reference
            ).first()

        if transfer is not None:
            with transaction.atomic():
                _delete_transfer_bundle(transfer)

            return Response(status=status.HTTP_204_NO_CONTENT)

        linked_journal_entry = cash_transaction.journal_entry
        bank_account = cash_transaction.bank_account
        was_approved = cash_transaction.status == AccountingCashTransaction.TransactionStatus.APPROVED

        with transaction.atomic():
            self.perform_destroy(cash_transaction)
            if linked_journal_entry is not None:
                linked_journal_entry.delete()
            if was_approved:
                recalculate_bank_account_current_balance(bank_account)

        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["put"], url_path="status")
    def set_status(self, request, pk=None):
        cash_transaction = self.get_object()
        new_status = request.data.get("status")
        rejection_reason = request.data.get("rejection_reason")
        prevent_journal_posting = self._to_bool(request.data.get("prevent_journal_posting", False))
        return self._update_status(
            cash_transaction,
            new_status,
            rejection_reason=rejection_reason,
            prevent_journal_posting=prevent_journal_posting,
        )

    @action(detail=True, methods=["put"], url_path="approve")
    def approve(self, request, pk=None):
        cash_transaction = self.get_object()
        prevent_journal_posting = self._to_bool(request.data.get("prevent_journal_posting", False))
        return self._update_status(
            cash_transaction,
            AccountingCashTransaction.TransactionStatus.APPROVED,
            prevent_journal_posting=prevent_journal_posting,
        )

    @action(detail=True, methods=["put"], url_path="reject")
    def reject(self, request, pk=None):
        rejection_reason = request.data.get("rejection_reason")
        if not rejection_reason:
            return Response(
                {"detail": "rejection_reason is required when rejecting a transaction"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        cash_transaction = self.get_object()
        return self._update_status(
            cash_transaction,
            AccountingCashTransaction.TransactionStatus.REJECTED,
            rejection_reason=rejection_reason,
        )

    @action(detail=True, methods=["post"], url_path="post")
    def post_transaction(self, request, pk=None):
        cash_transaction = self.get_object()

        try:
            journal_entry = post_cash_transaction_to_ledger(cash_transaction, actor=request.user)
        except ValidationError as exc:
            message = exc.messages[0] if hasattr(exc, "messages") and exc.messages else str(exc)
            return Response({"detail": message}, status=status.HTTP_400_BAD_REQUEST)

        recalculate_bank_account_current_balance(cash_transaction.bank_account)

        serializer = self.get_serializer(cash_transaction)
        return Response(
            {
                "detail": "Transaction posted successfully",
                "journal_entry_id": str(journal_entry.id),
                "transaction": serializer.data,
            },
            status=status.HTTP_200_OK,
        )


class AccountingAccountTransferViewSet(AccountingErrorFormattingMixin, viewsets.ModelViewSet):
    queryset = AccountingAccountTransfer.objects.select_related(
        "from_account",
        "to_account",
        "from_currency",
        "to_currency",
    ).order_by("-transfer_date", "-created_at")
    serializer_class = AccountingAccountTransferSerializer
    permission_classes = [AccountingTransactionAccessPolicy]

    def perform_create(self, serializer):
        from_account = serializer.validated_data.get("from_account")
        to_account = serializer.validated_data.get("to_account")
        amount = serializer.validated_data.get("amount")

        if from_account is None or to_account is None:
            raise serializers.ValidationError(
                {"detail": "Both from_account and to_account are required."}
            )

        if from_account.id == to_account.id:
            raise serializers.ValidationError({"to_account": "Destination account must be different from source account."})

        # Validate source account balance before transfer creation.
        available_balance = recalculate_bank_account_current_balance(from_account)
        if amount is not None and Decimal(str(amount)) > available_balance:
            raise serializers.ValidationError(
                {
                    "amount": (
                        f"Insufficient balance in source account. Available: {available_balance:,.2f}."
                    )
                }
            )

        payment_method = (
            AccountingPaymentMethod.objects.filter(code__iexact="system", is_active=True).first()
            or AccountingPaymentMethod.objects.filter(name__iexact="system", is_active=True).first()
        )
        if payment_method is None:
            raise serializers.ValidationError(
                {"payment_method": "System payment method not found. Create an active 'system' payment method first."}
            )

        transfer_out_type = AccountingTransactionType.objects.filter(code__iexact="TRANSFER_OUT", is_active=True).first()
        transfer_in_type = AccountingTransactionType.objects.filter(code__iexact="TRANSFER_IN", is_active=True).first()
        if transfer_out_type is None or transfer_in_type is None:
            raise serializers.ValidationError(
                {
                    "transaction_type": (
                        "Transfer transaction types not found. Please create active TRANSFER_OUT and TRANSFER_IN types."
                    )
                }
            )

        # Posting service currently supports income/expense categories only.
        if transfer_out_type.transaction_category != "expense" or transfer_in_type.transaction_category != "income":
            raise serializers.ValidationError(
                {
                    "transaction_type": (
                        "TRANSFER_OUT must be category 'expense' and TRANSFER_IN must be category 'income' for auto-posting."
                    )
                }
            )

        cash_tx_serializer = AccountingCashTransactionSerializer()
        with transaction.atomic():
            transfer = serializer.save()

            transfer_out_tx = AccountingCashTransaction.objects.create(
                bank_account=transfer.from_account,
                transaction_date=transfer.transfer_date,
                reference_number=cash_tx_serializer._generate_reference_number(transfer.transfer_date),
                transaction_type=transfer_out_type,
                payment_method=payment_method,
                amount=transfer.amount,
                currency=transfer.from_currency,
                exchange_rate=Decimal("1"),
                base_amount=transfer.amount,
                payer_payee=transfer.to_account.account_name,
                description=transfer.description or f"Transfer to {transfer.to_account.account_name}",
                status=AccountingCashTransaction.TransactionStatus.APPROVED,
                source_reference=transfer.reference_number,
            )

            transfer_in_tx = AccountingCashTransaction.objects.create(
                bank_account=transfer.to_account,
                transaction_date=transfer.transfer_date,
                reference_number=cash_tx_serializer._generate_reference_number(transfer.transfer_date),
                transaction_type=transfer_in_type,
                payment_method=payment_method,
                amount=transfer.to_amount,
                currency=transfer.to_currency,
                exchange_rate=Decimal("1"),
                base_amount=transfer.to_amount,
                payer_payee=transfer.from_account.account_name,
                description=transfer.description or f"Transfer from {transfer.from_account.account_name}",
                status=AccountingCashTransaction.TransactionStatus.APPROVED,
                source_reference=transfer.reference_number,
            )

            post_cash_transaction_to_ledger(transfer_out_tx, actor=self.request.user)
            post_cash_transaction_to_ledger(transfer_in_tx, actor=self.request.user)

            recalculate_bank_account_current_balance(transfer.from_account)
            recalculate_bank_account_current_balance(transfer.to_account)

            transfer.status = AccountingAccountTransfer.TransferStatus.COMPLETED
            transfer.save(update_fields=["status", "updated_at"])

    def destroy(self, request, *args, **kwargs):
        transfer = self.get_object()

        with transaction.atomic():
            _delete_transfer_bundle(transfer)

        return Response(status=status.HTTP_204_NO_CONTENT)
