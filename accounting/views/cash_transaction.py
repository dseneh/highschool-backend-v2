from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import MultiPartParser, FormParser
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
    sync_cash_transaction_journal_entry,
    sync_ledger_account_for_type,
)
from accounting.services.settings_services import (
    ensure_system_payment_method,
    ensure_transfer_transaction_types,
    bank_accounts_missing_ledger_message,
    validation_error_detail,
)
from accounting.services.transfer_posting import post_account_transfer_to_ledger
from accounting.services.post_all import (
    apply_cash_transaction_list_filters,
    build_cash_transaction_list_summary,
    execute_post_all,
    extract_filter_params,
    get_eligible_post_all_queryset,
)
from accounting.views.base import AccountingErrorFormattingMixin


class AccountingCashTransactionPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 500


def _delete_transfer_bundle(transfer: AccountingAccountTransfer) -> None:
    """Delete a transfer and all linked cash transactions/journal entries atomically."""
    linked_transactions = AccountingCashTransaction.objects.filter(
        source_reference=transfer.reference_number
    )

    bank_account_ids = {
        transfer.from_account_id,
        transfer.to_account_id,
        *linked_transactions.values_list("bank_account_id", flat=True),
    }

    journal_entry_ids = set(
        linked_transactions.exclude(journal_entry_id__isnull=True)
        .values_list("journal_entry_id", flat=True)
    )
    journal_entry_ids.update(
        AccountingJournalEntry.objects.filter(
            source_reference=transfer.reference_number,
            source="bank_transfer",
        ).values_list("id", flat=True)
    )

    linked_transactions.delete()

    if journal_entry_ids:
        AccountingJournalEntry.objects.filter(id__in=journal_entry_ids).delete()

    transfer.delete()

    for account in AccountingBankAccount.objects.filter(id__in=bank_account_ids):
        recalculate_bank_account_current_balance(account)


class AccountingTransactionTypeViewSet(AccountingErrorFormattingMixin, viewsets.ModelViewSet):
    queryset = AccountingTransactionType.objects.select_related(
        "default_ledger_account", "managed_ledger_account"
    ).order_by("name")
    serializer_class = AccountingTransactionTypeSerializer
    permission_classes = [AccountingFinanceAccessPolicy]
    pagination_class = None

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.code.strip().upper() in {"TRANSFER_IN", "TRANSFER_OUT"}:
            return Response(
                {
                    "detail": (
                        "TRANSFER_IN and TRANSFER_OUT transaction types cannot be deleted."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super().destroy(request, *args, **kwargs)

    @action(detail=True, methods=["post"], url_path="sync-ledger-account")
    def sync_ledger_account(self, request, pk=None):
        tx_type = self.get_object()
        try:
            result = sync_ledger_account_for_type(tx_type)
        except ValidationError as exc:
            payload = exc.message_dict if hasattr(exc, "message_dict") else {"detail": exc.messages}
            return Response(payload, status=status.HTTP_400_BAD_REQUEST)
        tx_type.refresh_from_db()
        return Response(
            {
                "result": result.to_dict(),
                "transaction_type": AccountingTransactionTypeSerializer(tx_type).data,
            },
            status=status.HTTP_200_OK,
        )


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
        for account in queryset:
            recalculate_bank_account_current_balance(account)
        serializer = self.get_serializer(queryset, many=True)

        from accounting.services.posting import compute_bank_account_native_balance

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
            native_balance = compute_bank_account_native_balance(account)
            if account.opening_balance:
                native_balance += Decimal(str(account.opening_balance or 0))
            balances_by_currency[key]["total_balance"] = (
                Decimal(str(balances_by_currency[key]["total_balance"]))
                + native_balance
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

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        recalculate_bank_account_current_balance(instance)
        instance.refresh_from_db()
        serializer = self.get_serializer(instance)
        return Response(serializer.data)


class AccountingCashTransactionViewSet(AccountingErrorFormattingMixin, viewsets.ModelViewSet):
    queryset = AccountingCashTransaction.objects.select_related(
        "transaction_type",
        "payment_method",
        "bank_account",
        "currency",
        "ledger_account",
        "journal_entry",
        # Resolve the direct student FK + grade level in one round-trip so
        # the serializer can build the "student_payment" snapshot without
        # hitting the DB per row.
        "student",
        "student__grade_level",
    ).prefetch_related(
        # Bill allocations are only used as a fallback (legacy rows without
        # the direct FK) and to enrich the snapshot with the bills this
        # payment was applied against. Prefetching keeps the list endpoint
        # at a constant query count.
        "bill_allocations__student_bill__academic_year",
        "bill_allocations__student_bill__student__grade_level",
    ).order_by("-updated_at", "-created_at")
    serializer_class = AccountingCashTransactionSerializer
    permission_classes = [AccountingTransactionAccessPolicy]
    pagination_class = AccountingCashTransactionPagination

    @staticmethod
    def _to_bool(value):
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        if isinstance(value, int):
            return value == 1
        return False

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())

        # Compute summary aggregates on the full filtered queryset (before pagination).
        summary = build_cash_transaction_list_summary(queryset)

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            paginated = self.get_paginated_response(serializer.data)
            paginated.data["summary"] = summary
            return paginated

        serializer = self.get_serializer(queryset, many=True)
        return Response({"results": serializer.data, "count": queryset.count(), "summary": summary})

    def get_queryset(self):
        queryset = super().get_queryset()
        return apply_cash_transaction_list_filters(
            queryset, self.request.query_params
        )

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

    def _validate_student_income_payment(self, data, *, existing_instance=None):
        from academics.models import AcademicYear
        from accounting.services.currency_totals import effective_payment_base_amount
        from accounting.services.student_resolution import resolve_student_from_identifier
        from finance.validators import get_student_net_remaining_balance

        transaction_type = data.get("transaction_type")
        if transaction_type is None and existing_instance is not None:
            transaction_type = existing_instance.transaction_type

        amount = data.get("amount")
        if amount is None and existing_instance is not None:
            amount = existing_instance.amount

        if (
            not transaction_type
            or transaction_type.transaction_category != "income"
            or amount is None
        ):
            return

        source_reference = (data.get("source_reference") or "").strip()
        if not source_reference and existing_instance is not None:
            source_reference = (existing_instance.source_reference or "").strip()

        student = data.get("student")
        if student is None and existing_instance is not None:
            student = existing_instance.student
        if student is None and source_reference:
            student = resolve_student_from_identifier(source_reference)

        if not student:
            return

        tx_date = data.get("transaction_date")
        if tx_date is None and existing_instance is not None:
            tx_date = existing_instance.transaction_date

        academic_year = (
            AcademicYear.objects.filter(
                Q(start_date__lte=tx_date) & Q(end_date__gte=tx_date)
            ).first()
            if tx_date
            else None
        ) or AcademicYear.objects.filter(current=True).first()

        if not academic_year:
            return

        remaining = get_student_net_remaining_balance(student, academic_year)
        if remaining <= 0:
            raise serializers.ValidationError(
                {"detail": "Student has no balance due. Cannot create transaction."}
            )

        exchange_rate = data.get("exchange_rate")
        if exchange_rate is None and existing_instance is not None:
            exchange_rate = existing_instance.exchange_rate

        base_amount = data.get("base_amount")
        if base_amount is None and existing_instance is not None and "amount" not in data and "exchange_rate" not in data:
            base_amount = existing_instance.base_amount

        effective = effective_payment_base_amount(
            amount,
            exchange_rate=exchange_rate,
            base_amount=base_amount,
        )

        if effective > remaining:
            raise serializers.ValidationError(
                {
                    "detail": (
                        f"Payment amount of {effective:,.2f} (base currency equivalent) "
                        f"exceeds student balance due of {remaining:,.2f}."
                    )
                }
            )

    def perform_create(self, serializer):
        """Validate student balance before creating an income transaction linked to a student."""
        self._validate_student_income_payment(serializer.validated_data)

        cash_transaction = serializer.save()
        if cash_transaction.status == AccountingCashTransaction.TransactionStatus.APPROVED:
            post_cash_transaction_to_ledger(cash_transaction, actor=self.request.user)
            recalculate_bank_account_current_balance(cash_transaction.bank_account)

    def _validate_editable(self, cash_transaction):
        if cash_transaction.status == AccountingCashTransaction.TransactionStatus.REJECTED:
            return Response(
                {
                    "detail": (
                        "Rejected transactions cannot be edited. "
                        "Create a new transaction if corrections are needed."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if cash_transaction.source_reference:
            if AccountingAccountTransfer.objects.filter(
                reference_number=cash_transaction.source_reference
            ).exists():
                return Response(
                    {"detail": "Transfer-linked transactions cannot be edited."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        journal_entry = cash_transaction.journal_entry
        if (
            journal_entry is not None
            and journal_entry.status == AccountingJournalEntry.EntryStatus.REVERSED
        ):
            return Response(
                {
                    "detail": (
                        "This transaction's journal entry was reversed and "
                        "cannot be edited in place."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        return None

    def perform_update(self, serializer):
        cash_transaction = self.get_object()
        previous_bank_account_id = cash_transaction.bank_account_id

        self._validate_student_income_payment(
            serializer.validated_data,
            existing_instance=cash_transaction,
        )

        with transaction.atomic():
            cash_transaction = serializer.save()

            if cash_transaction.journal_entry_id:
                try:
                    sync_cash_transaction_journal_entry(
                        cash_transaction, actor=self.request.user
                    )
                except ValidationError as exc:
                    message = (
                        exc.messages[0]
                        if hasattr(exc, "messages") and exc.messages
                        else str(exc)
                    )
                    raise serializers.ValidationError({"detail": message}) from exc

        bank_account_ids = {
            account_id
            for account_id in (previous_bank_account_id, cash_transaction.bank_account_id)
            if account_id
        }
        if (
            cash_transaction.status
            == AccountingCashTransaction.TransactionStatus.APPROVED
            and bank_account_ids
        ):
            for bank_account in AccountingBankAccount.objects.filter(
                id__in=bank_account_ids
            ):
                recalculate_bank_account_current_balance(bank_account)

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

    @action(detail=False, methods=["get"], url_path="unposted-count")
    def unposted_count(self, request):
        """Lightweight count of approved transactions awaiting journal posting.

        Used by the sidebar badge and the warning banner on the cash
        transactions page. Returns the actionable backlog only (approved
        but not yet posted) — pending/rejected rows aren't counted since
        they can't be posted regardless.
        """
        count = AccountingCashTransaction.objects.filter(
            status=AccountingCashTransaction.TransactionStatus.APPROVED,
            journal_entry__isnull=True,
        ).count()
        return Response({"count": count}, status=status.HTTP_200_OK)

    @action(detail=False, methods=["post"], url_path="post-all")
    def post_all(self, request):
        """Post every approved + unposted transaction matching the filter.

        Accepts the same filter query params as ``list`` so callers can
        scope the bulk-post operation to a date range / bank account /
        transaction type / etc. Pass ``apply_current_filters=false`` to
        ignore the request filters and post every approved unposted
        transaction in the tenant.

        Large batches (>50 eligible rows) are processed in the background;
        poll ``post-all-status/{task_id}/`` for progress.

        Response payload:
            {
                "posted_count": N,
                "skipped_count": M,
                "errors": [{ "id": "<uuid>", "reference_number": "...",
                             "detail": "..." }],
                "journal_entry_ids": ["<uuid>", ...]
            }
        """
        from accounting.services.post_all_tasks import (
            PostAllBackgroundProcessor,
            PostAllTaskManager,
        )

        apply_filters = self._to_bool(
            request.data.get("apply_current_filters", True)
        )
        filter_params = extract_filter_params(request.query_params)
        eligible_count = get_eligible_post_all_queryset(
            apply_filters=apply_filters,
            filter_params=filter_params,
        ).count()

        if PostAllTaskManager.should_use_background(eligible_count):
            user_id = getattr(request.user, "id", None)
            task_id = PostAllTaskManager.create_task(
                estimated_count=eligible_count,
                user_id=user_id,
                apply_filters=apply_filters,
                filter_params=filter_params,
            )
            PostAllBackgroundProcessor.start(task_id)
            return Response(
                {
                    "task_id": task_id,
                    "status": "pending",
                    "processing_mode": "background",
                    "estimated_count": eligible_count,
                    "message": (
                        f"Posting {eligible_count:,} transactions in the background. "
                        "You can keep this dialog open to track progress."
                    ),
                    "check_status_url": (
                        f"/api/v1/accounting/cash-transactions/post-all-status/{task_id}/"
                    ),
                },
                status=status.HTTP_202_ACCEPTED,
            )

        result = execute_post_all(
            user_id=getattr(request.user, "id", None),
            apply_filters=apply_filters,
            filter_params=filter_params,
        )
        return Response(
            {**result, "processing_mode": "synchronous"},
            status=status.HTTP_200_OK,
        )

    @action(detail=False, methods=["get"], url_path=r"post-all-status/(?P<task_id>[^/.]+)")
    def post_all_status(self, request, task_id=None):
        """Poll background bulk-post progress."""
        from accounting.services.post_all_tasks import PostAllTaskManager

        task_data = PostAllTaskManager.get_task(task_id)
        if not task_data:
            return Response({"detail": "Post-all task not found."}, status=status.HTTP_404_NOT_FOUND)

        payload = {
            "task_id": task_id,
            "status": task_data.get("status"),
            "progress": task_data.get("progress", 0),
            "created_at": task_data.get("created_at"),
            "updated_at": task_data.get("updated_at"),
            "estimated_count": task_data.get("estimated_count", 0),
            "total_processed": task_data.get("total_processed", 0),
            "posted_count": task_data.get("posted_count", 0),
            "skipped_count": task_data.get("skipped_count", 0),
            "errors": task_data.get("errors") or [],
            "result": task_data.get("result"),
            "error": task_data.get("error"),
        }
        return Response(payload, status=status.HTTP_200_OK)

    # ------------------------------------------------------------------
    #  Export
    # ------------------------------------------------------------------

    # Column registry – maps column keys to (header, extractor) pairs.
    # Headers are chosen so CSVGenerator._get_data_keys produces the column key.
    _EXPORT_COLUMNS = {
        "reference": ("Reference", lambda t: t.reference_number or ""),
        "date": ("Date", lambda t: str(t.transaction_date) if t.transaction_date else ""),
        "type": ("Type", lambda t: t.transaction_type.name if t.transaction_type else ""),
        "description": ("Description", lambda t: t.description or ""),
        "bank_account": ("Bank Account", lambda t: t.bank_account.account_name if t.bank_account else ""),
        "payment_method": ("Payment Method", lambda t: t.payment_method.name if t.payment_method else ""),
        "ledger_account": ("Ledger Account", lambda t: t.ledger_account.name if t.ledger_account else ""),
        "payer_payee": ("Payer Payee", lambda t: t.payer_payee or ""),
        "amount": ("Amount", lambda t: float(t.amount or 0)),
        "currency": ("Currency", lambda t: t.currency.code if t.currency else ""),
        "exchange_rate": ("Exchange Rate", lambda t: float(t.exchange_rate or 0)),
        "base_amount": ("Base Amount", lambda t: float(t.base_amount or 0)),
        "status": ("Status", lambda t: t.status or ""),
        "journal_entry": ("Journal Entry", lambda t: t.journal_entry.reference_number if t.journal_entry else ""),
        "source_reference": ("Source Reference", lambda t: t.source_reference or ""),
        "created_at": ("Created At", lambda t: t.created_at.strftime("%Y-%m-%d %H:%M") if t.created_at else ""),
    }

    _DEFAULT_COLUMNS = [
        "reference", "date", "type", "description",
        "bank_account", "payer_payee", "amount", "currency", "status",
    ]

    @action(detail=False, methods=["get"], url_path="export")
    def export_transactions(self, request):
        from common.file_generators import FileGenerator, FileGeneratorConfig

        file_format = request.query_params.get("file_format", "csv")
        if file_format not in ("csv", "excel"):
            return Response(
                {"detail": "file_format must be 'csv' or 'excel'"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Determine which columns to include
        columns_param = request.query_params.get("columns")
        if columns_param:
            col_keys = [c for c in columns_param.split(",") if c in self._EXPORT_COLUMNS]
        else:
            col_keys = self._DEFAULT_COLUMNS

        if not col_keys:
            return Response(
                {"detail": "No valid columns specified"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Reuse get_queryset() which already handles all filter params
        queryset = self.get_queryset()

        headers = [self._EXPORT_COLUMNS[k][0] for k in col_keys]
        extractors = [self._EXPORT_COLUMNS[k][1] for k in col_keys]

        data = []
        # Django 5+ requires chunk_size when iterating a prefetch_related queryset.
        iterator_kwargs = (
            {"chunk_size": 2000}
            if getattr(queryset, "_prefetch_related_lookups", None)
            else {}
        )
        for txn in queryset.iterator(**iterator_kwargs):
            row = {}
            for key, header, extractor in zip(col_keys, headers, extractors):
                # FileGenerator looks up by snake-cased header
                row[key] = extractor(txn)
            data.append(row)

        # Build metadata
        metadata = {}
        start_date = request.query_params.get("start_date")
        end_date = request.query_params.get("end_date")
        if start_date:
            metadata["From"] = start_date
        if end_date:
            metadata["To"] = end_date
        status_param = request.query_params.get("status")
        if status_param:
            metadata["Status"] = status_param

        config = FileGeneratorConfig(
            title="Cash Transactions",
            filename_prefix="cash_transactions",
            headers=headers,
            metadata=metadata,
        )

        return FileGenerator.generate_file(
            data=data,
            config=config,
            file_format=file_format,
        )

    @action(detail=False, methods=["post"], url_path="bulk-upload", parser_classes=[MultiPartParser, FormParser])
    def bulk_upload(self, request):
        from accounting.services.bulk_upload import bulk_upload_cash_transactions

        uploaded_file = request.FILES.get("file")
        if not uploaded_file:
            return Response({"detail": "No file provided."}, status=status.HTTP_400_BAD_REQUEST)

        replace_existing = str(request.data.get("replace_existing", "false")).lower() in ("true", "1")
        bank_account_id = request.data.get("bank_account_id") or None
        override_status = request.data.get("override_status") or None
        override_transaction_type_id = request.data.get("transaction_type_id") or None

        try:
            result = bulk_upload_cash_transactions(
                uploaded_file,
                replace_existing=replace_existing,
                bank_account_id=bank_account_id,
                override_status=override_status,
                override_transaction_type_id=override_transaction_type_id,
            )
            return Response(result, status=status.HTTP_200_OK)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            return Response({"detail": f"Upload failed: {str(exc)}"}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=["post"], url_path="upload", parser_classes=[MultiPartParser, FormParser])
    def upload(self, request):
        """Upload transactions using template-based schema."""
        from accounting.services.transaction_upload import (
            _read_file_to_dataframe,
            _validate_file,
            execute_transaction_upload,
        )
        from accounting.services.transaction_upload_tasks import (
            TransactionUploadBackgroundProcessor,
            TransactionUploadTaskManager,
        )

        uploaded_file = request.FILES.get("file")
        if not uploaded_file:
            return Response({"detail": "No file provided."}, status=status.HTTP_400_BAD_REQUEST)

        template_type = request.data.get("template_type")
        if not template_type:
            return Response({"detail": "template_type is required (tuition, salary, or general)."}, status=status.HTTP_400_BAD_REQUEST)

        bank_account_id = request.data.get("bank_account_id") or None
        gl_account_override = request.data.get("gl_account_override") or None
        status_override = request.data.get("status_override") or None
        replace_by_ref_number = request.data.get("replace_by_ref_number") == "true"

        try:
            _validate_file(uploaded_file)
            df = _read_file_to_dataframe(uploaded_file)
            row_count = len(df)

            if TransactionUploadTaskManager.should_use_background(row_count):
                user_id = getattr(request.user, "id", None)
                task_id = TransactionUploadTaskManager.create_task(
                    template_type=template_type,
                    row_count=row_count,
                    user_id=user_id,
                    file_name=getattr(uploaded_file, "name", "upload"),
                )
                TransactionUploadBackgroundProcessor.start(
                    task_id,
                    df,
                    template_type=template_type,
                    bank_account_id=bank_account_id,
                    gl_account_override=gl_account_override,
                    status_override=status_override,
                    replace_by_ref_number=replace_by_ref_number,
                )
                return Response(
                    {
                        "task_id": task_id,
                        "status": "pending",
                        "processing_mode": "background",
                        "row_count": row_count,
                        "message": (
                            f"Processing {row_count:,} rows in the background. "
                            "You can close this dialog and check progress here."
                        ),
                        "check_status_url": (
                            f"/api/v1/accounting/cash-transactions/upload-status/{task_id}/"
                        ),
                    },
                    status=status.HTTP_202_ACCEPTED,
                )

            result = execute_transaction_upload(
                df,
                template_type=template_type,
                bank_account_id=bank_account_id,
                gl_account_override=gl_account_override,
                status_override=status_override,
                replace_by_ref_number=replace_by_ref_number,
            )
            return Response(
                {**result, "processing_mode": "synchronous"},
                status=status.HTTP_200_OK,
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            return Response({"detail": f"Upload failed: {str(exc)}"}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=["get"], url_path=r"upload-status/(?P<task_id>[^/.]+)")
    def upload_status(self, request, task_id=None):
        """Poll background template upload progress."""
        from accounting.services.transaction_upload_tasks import TransactionUploadTaskManager

        task_data = TransactionUploadTaskManager.get_task(task_id)
        if not task_data:
            return Response({"detail": "Upload task not found."}, status=status.HTTP_404_NOT_FOUND)

        payload = {
            "task_id": task_id,
            "status": task_data.get("status"),
            "progress": task_data.get("progress", 0),
            "created_at": task_data.get("created_at"),
            "updated_at": task_data.get("updated_at"),
            "template_type": task_data.get("template_type"),
            "file_name": task_data.get("file_name"),
            "estimated_count": task_data.get("estimated_count", 0),
            "total_processed": task_data.get("total_processed", 0),
            "created": task_data.get("created", 0),
            "updated": task_data.get("updated", 0),
            "total_errors": task_data.get("total_errors", 0),
            "errors": task_data.get("errors") or [],
            "result": task_data.get("result"),
            "error": task_data.get("error"),
        }
        return Response(payload, status=status.HTTP_200_OK)


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

        missing_ledger_accounts = []
        if from_account.ledger_account_id is None:
            missing_ledger_accounts.append(from_account)
        if to_account.ledger_account_id is None:
            missing_ledger_accounts.append(to_account)
        if missing_ledger_accounts:
            raise serializers.ValidationError(
                {"detail": bank_accounts_missing_ledger_message(missing_ledger_accounts)}
            )

        try:
            payment_method = ensure_system_payment_method()
            transfer_out_type, transfer_in_type = ensure_transfer_transaction_types()
        except ValidationError as exc:
            raise serializers.ValidationError({"detail": validation_error_detail(exc)}) from exc

        cash_tx_serializer = AccountingCashTransactionSerializer()
        with transaction.atomic():
            transfer = serializer.save()

            AccountingCashTransaction.objects.create(
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

            AccountingCashTransaction.objects.create(
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

            try:
                journal_entry = post_account_transfer_to_ledger(transfer, actor=self.request.user)
            except ValidationError as exc:
                raise serializers.ValidationError({"detail": validation_error_detail(exc)}) from exc

            AccountingCashTransaction.objects.filter(
                source_reference=transfer.reference_number,
            ).update(journal_entry=journal_entry)

            recalculate_bank_account_current_balance(transfer.from_account)
            recalculate_bank_account_current_balance(transfer.to_account)

            transfer.status = AccountingAccountTransfer.TransferStatus.COMPLETED
            transfer.save(update_fields=["status", "updated_at"])

    def destroy(self, request, *args, **kwargs):
        transfer = self.get_object()

        with transaction.atomic():
            _delete_transfer_bundle(transfer)

        return Response(status=status.HTTP_204_NO_CONTENT)
