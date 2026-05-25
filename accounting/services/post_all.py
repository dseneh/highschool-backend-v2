"""Bulk-post approved cash transactions to the ledger."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal, InvalidOperation

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction

from accounting.models import AccountingBankAccount, AccountingCashTransaction
from accounting.services import (
    post_cash_transaction_to_ledger,
    recalculate_bank_account_current_balance,
)

FILTER_PARAM_KEYS = (
    "category",
    "status",
    "bank_account",
    "transaction_type",
    "transaction_type_code",
    "start_date",
    "end_date",
    "amount",
    "amount_min",
    "amount_max",
    "reference",
)


def extract_filter_params(query_params) -> dict[str, str]:
    return {
        key: query_params.get(key)
        for key in FILTER_PARAM_KEYS
        if query_params.get(key) not in (None, "")
    }


def apply_cash_transaction_list_filters(queryset, params) -> object:
    category = params.get("category")
    status_param = params.get("status")
    bank_account = params.get("bank_account")
    transaction_type = params.get("transaction_type")
    start_date = params.get("start_date")
    end_date = params.get("end_date")
    amount = params.get("amount")
    amount_min = params.get("amount_min")
    amount_max = params.get("amount_max")
    reference = params.get("reference")
    transaction_type_code = params.get("transaction_type_code")

    if category:
        queryset = queryset.filter(transaction_type__transaction_category=category)
    if status_param:
        queryset = queryset.filter(status=status_param)
    if bank_account:
        queryset = queryset.filter(bank_account_id=bank_account)
    if transaction_type:
        queryset = queryset.filter(transaction_type_id=transaction_type)
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
    if reference:
        queryset = queryset.filter(reference_number__icontains=reference)

    return queryset


def get_eligible_post_all_queryset(
    *,
    apply_filters: bool,
    filter_params: dict[str, str],
):
    queryset = AccountingCashTransaction.objects.all()
    if apply_filters and filter_params:
        queryset = apply_cash_transaction_list_filters(queryset, filter_params)

    eligible_ids = list(
        queryset.filter(
            status=AccountingCashTransaction.TransactionStatus.APPROVED,
            journal_entry__isnull=True,
        ).values_list("id", flat=True)
    )

    return AccountingCashTransaction.objects.filter(id__in=eligible_ids).select_related(
        "bank_account", "transaction_type"
    )


def execute_post_all(
    *,
    user_id: int | None,
    apply_filters: bool,
    filter_params: dict[str, str],
    progress_callback: Callable[[int, int], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> dict:
    actor = None
    if user_id is not None:
        actor = get_user_model().objects.filter(id=user_id).first()

    eligible = get_eligible_post_all_queryset(
        apply_filters=apply_filters,
        filter_params=filter_params,
    )
    eligible_ids = list(eligible.values_list("id", flat=True))
    total = len(eligible_ids)

    posted_journal_ids: list[str] = []
    errors: list[dict] = []
    affected_bank_account_ids: set = set()
    processed = 0

    for cash_tx in eligible.iterator(chunk_size=200):
        if cancel_check and cancel_check():
            break

        try:
            with transaction.atomic():
                journal_entry = post_cash_transaction_to_ledger(cash_tx, actor=actor)
            posted_journal_ids.append(str(journal_entry.id))
            if cash_tx.bank_account_id:
                affected_bank_account_ids.add(cash_tx.bank_account_id)
        except ValidationError as exc:
            message = (
                exc.messages[0]
                if hasattr(exc, "messages") and exc.messages
                else str(exc)
            )
            errors.append(
                {
                    "id": str(cash_tx.id),
                    "reference_number": cash_tx.reference_number or "",
                    "detail": message,
                }
            )
        except Exception as exc:
            errors.append(
                {
                    "id": str(cash_tx.id),
                    "reference_number": cash_tx.reference_number or "",
                    "detail": str(exc),
                }
            )

        processed += 1
        if progress_callback:
            progress_callback(processed, total)

    for bank_account in AccountingBankAccount.objects.filter(
        id__in=affected_bank_account_ids
    ):
        recalculate_bank_account_current_balance(bank_account)

    return {
        "posted_count": len(posted_journal_ids),
        "skipped_count": len(errors),
        "journal_entry_ids": posted_journal_ids,
        "errors": errors,
    }
