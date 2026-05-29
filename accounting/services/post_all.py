"""Bulk-post approved cash transactions to the ledger."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from uuid import UUID

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Case, Count, DecimalField, F, Q, Sum, When
from django.db.models.functions import Abs

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
    "student_payments",
    "start_date",
    "end_date",
    "amount",
    "amount_min",
    "amount_max",
    "reference",
)


def build_student_payment_list_filter() -> Q:
    """Match cash transactions that represent student tuition/fee payments."""
    return (
        Q(student__isnull=False)
        | Q(transaction_type__code__iexact="TUITION")
        | Q(bill_allocations__isnull=False)
    )


def extract_filter_params(query_params) -> dict[str, str]:
    return {
        key: query_params.get(key)
        for key in FILTER_PARAM_KEYS
        if query_params.get(key) not in (None, "")
    }


def build_cash_transaction_search_filter(search: str) -> Q:
    """Match a free-text query against the main cash-transaction list columns."""
    term = (search or "").strip()
    if not term:
        return Q()

    query = (
        Q(reference_number__icontains=term)
        | Q(description__icontains=term)
        | Q(payer_payee__icontains=term)
        | Q(source_reference__icontains=term)
        | Q(rejection_reason__icontains=term)
        | Q(approved_by__icontains=term)
        | Q(bank_account__account_name__icontains=term)
        | Q(bank_account__account_number__icontains=term)
        | Q(bank_account__bank_name__icontains=term)
        | Q(transaction_type__name__icontains=term)
        | Q(transaction_type__code__icontains=term)
        | Q(payment_method__name__icontains=term)
        | Q(payment_method__code__icontains=term)
        | Q(currency__code__icontains=term)
        | Q(currency__name__icontains=term)
        | Q(currency__symbol__icontains=term)
        | Q(ledger_account__name__icontains=term)
        | Q(ledger_account__code__icontains=term)
        | Q(journal_entry__reference_number__icontains=term)
        | Q(journal_entry__source_reference__icontains=term)
        | Q(journal_entry__description__icontains=term)
        | Q(student__id_number__icontains=term)
        | Q(student__first_name__icontains=term)
        | Q(student__last_name__icontains=term)
        | Q(student__middle_name__icontains=term)
        | Q(student__prev_id_number__icontains=term)
    )

    status_term = term.lower()
    if status_term in {
        AccountingCashTransaction.TransactionStatus.PENDING,
        AccountingCashTransaction.TransactionStatus.APPROVED,
        AccountingCashTransaction.TransactionStatus.REJECTED,
    }:
        query |= Q(status=status_term)

    normalized_digits = term.replace("-", "").replace("/", "").replace(",", "")
    if normalized_digits.replace(".", "").isdigit():
        query |= Q(transaction_date__icontains=term)
        try:
            amount = Decimal(normalized_digits)
            query |= Q(amount=amount) | Q(base_amount=amount)
        except (InvalidOperation, ValueError):
            pass
        if term.isdigit():
            query |= Q(student__id_number__startswith=term)

    return query


def _build_bank_account_filter(bank_account: str) -> Q:
    """Match bank account by account number, or by id when the value is a UUID."""
    bank_account_value = str(bank_account).strip()
    if not bank_account_value:
        return Q()

    account_filter = Q(bank_account__account_number__iexact=bank_account_value)
    try:
        UUID(bank_account_value)
    except (ValueError, AttributeError, TypeError):
        return account_filter

    return account_filter | Q(bank_account_id=bank_account_value)


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
    student_payments = params.get("student_payments")
    search = params.get("search")

    if search:
        search_term = str(search).strip()
        if search_term:
            queryset = queryset.filter(build_cash_transaction_search_filter(search_term))

    if category:
        queryset = queryset.filter(transaction_type__transaction_category=category)
    if status_param:
        queryset = queryset.filter(status=status_param)
    if bank_account:
        bank_account_filter = _build_bank_account_filter(bank_account)
        if bank_account_filter:
            queryset = queryset.filter(bank_account_filter)
    if transaction_type:
        queryset = queryset.filter(transaction_type_id=transaction_type)
    if transaction_type_code:
        queryset = queryset.filter(transaction_type__code__iexact=transaction_type_code)
    if student_payments in {"1", "true", "yes", "on"}:
        queryset = queryset.filter(build_student_payment_list_filter()).distinct()
    if start_date:
        queryset = queryset.filter(transaction_date__gte=start_date)
    if end_date:
        queryset = queryset.filter(transaction_date__lte=end_date)
    if amount:
        try:
            queryset = queryset.filter(amount=Decimal(amount))
        except (InvalidOperation, TypeError):
            pass
    if amount_min not in (None, ""):
        try:
            queryset = queryset.filter(amount__gte=Decimal(amount_min))
        except (InvalidOperation, TypeError):
            pass
    if amount_max not in (None, ""):
        try:
            queryset = queryset.filter(amount__lte=Decimal(amount_max))
        except (InvalidOperation, TypeError):
            pass
    if reference:
        queryset = queryset.filter(reference_number__icontains=reference)

    ordering = params.get("ordering")
    ordering_map = {
        "transaction_date": "transaction_date",
        "-transaction_date": "-transaction_date",
        "updated_at": "updated_at",
        "-updated_at": "-updated_at",
        "reference_number": "reference_number",
        "-reference_number": "-reference_number",
        "description": "description",
        "-description": "-description",
        "status": "status",
        "-status": "-status",
        "amount": "amount",
        "-amount": "-amount",
        "created_at": "created_at",
        "-created_at": "-created_at",
    }
    order_by = ordering_map.get(str(ordering or "").strip(), "-updated_at")
    return queryset.order_by(order_by, "-created_at")


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


def _approved_signed_amount_expression():
    """Mirror frontend getSignedAmount() for approved-net aggregation."""
    return Case(
        When(
            transaction_type__code__iexact="TRANSFER_OUT",
            then=-Abs(F("amount")),
        ),
        When(
            transaction_type__code__iexact="TRANSFER_IN",
            then=Abs(F("amount")),
        ),
        When(
            transaction_type__transaction_category="expense",
            then=-Abs(F("amount")),
        ),
        When(
            transaction_type__transaction_category="income",
            then=Abs(F("amount")),
        ),
        default=F("amount"),
        output_field=DecimalField(max_digits=18, decimal_places=2),
    )


def build_cash_transaction_list_summary(queryset) -> dict[str, object]:
    """Aggregate list stats across the full filtered queryset (before pagination)."""
    approved_status = AccountingCashTransaction.TransactionStatus.APPROVED
    signed_amount = _approved_signed_amount_expression()

    agg = queryset.aggregate(
        pending_count=Count("id", filter=Q(status=AccountingCashTransaction.TransactionStatus.PENDING)),
        approved_count=Count("id", filter=Q(status=approved_status)),
        rejected_count=Count("id", filter=Q(status=AccountingCashTransaction.TransactionStatus.REJECTED)),
        posted_count=Count("id", filter=Q(journal_entry__isnull=False)),
        not_posted_count=Count("id", filter=Q(journal_entry__isnull=True)),
        approved_unposted_count=Count(
            "id",
            filter=Q(status=approved_status, journal_entry__isnull=True),
        ),
        approved_net_total=Sum(
            signed_amount,
            filter=Q(status=approved_status),
        ),
        approved_income_total=Sum(
            Abs(F("amount")),
            filter=Q(status=approved_status)
            & (
                Q(transaction_type__transaction_category="income")
                | Q(transaction_type__code__iexact="TRANSFER_IN")
            ),
        ),
        approved_expense_total=Sum(
            Abs(F("amount")),
            filter=Q(status=approved_status)
            & (
                Q(transaction_type__transaction_category="expense")
                | Q(transaction_type__code__iexact="TRANSFER_OUT")
            ),
        ),
    )

    return {
        "pending_count": agg["pending_count"] or 0,
        "approved_count": agg["approved_count"] or 0,
        "rejected_count": agg["rejected_count"] or 0,
        "posted_count": agg["posted_count"] or 0,
        "not_posted_count": agg["not_posted_count"] or 0,
        "approved_unposted_count": agg["approved_unposted_count"] or 0,
        "approved_net_total": str(agg["approved_net_total"] or Decimal("0")),
        "approved_income_total": str(agg["approved_income_total"] or Decimal("0")),
        "approved_expense_total": str(agg["approved_expense_total"] or Decimal("0")),
    }
