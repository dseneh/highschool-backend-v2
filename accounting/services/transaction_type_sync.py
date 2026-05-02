"""
Synchronize an `AccountingTransactionType` with a managed
`AccountingLedgerAccount` (chart of accounts entry).

The link is one-way:
    AccountingTransactionType.managed_ledger_account -> AccountingLedgerAccount

Sync rules
----------
* Only runs when ``auto_manage_ledger_account`` is True on the type.
* Refused for ``transaction_category == 'transfer'`` types — they don't map
  to a single income/expense GL account.
* Creates a new ledger account when none is linked yet.
* Updates name / code / account_type / normal_balance / description on an
  existing managed account. If the account already has journal lines posted
  against it, structural changes (code / account_type) still proceed but a
  warning is surfaced so the caller can inform the user.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from django.core.exceptions import ValidationError
from django.db import transaction as db_transaction

from accounting.models import (
    AccountingJournalLine,
    AccountingLedgerAccount,
    AccountingTransactionType,
)


_CATEGORY_TO_ACCOUNT_TYPE = {
    "income": AccountingLedgerAccount.AccountType.INCOME,
    "expense": AccountingLedgerAccount.AccountType.EXPENSE,
    "transfer": AccountingLedgerAccount.AccountType.ASSET,
}

_CATEGORY_TO_NORMAL_BALANCE = {
    "income": "credit",
    "expense": "debit",
    "transfer": "debit",
}

# Transaction type codes that represent inter-account transfers and must map
# to an asset clearing account regardless of the type's nominal category.
_TRANSFER_CLEARING_CODES = {"TRANSFER_IN", "TRANSFER_OUT"}


@dataclass
class SyncResult:
    """Outcome of a sync attempt."""

    action: str  # "created" | "updated" | "skipped" | "noop"
    account_id: Optional[int] = None
    account_code: Optional[str] = None
    account_name: Optional[str] = None
    warnings: list[str] = field(default_factory=list)
    reason: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "account_id": self.account_id,
            "account_code": self.account_code,
            "account_name": self.account_name,
            "warnings": self.warnings,
            "reason": self.reason,
        }


def _derive_fields(tx_type: AccountingTransactionType) -> dict:
    code = (tx_type.code or "").strip().upper()
    category = tx_type.transaction_category

    # Transfer In/Out always map to an ASSET clearing account, even when the
    # transaction type is nominally categorised as income/expense for posting
    # purposes.
    if code in _TRANSFER_CLEARING_CODES or category == "transfer":
        account_type = AccountingLedgerAccount.AccountType.ASSET
        normal_balance = "debit"
    else:
        account_type = _CATEGORY_TO_ACCOUNT_TYPE[category]
        normal_balance = _CATEGORY_TO_NORMAL_BALANCE[category]

    return {
        "code": code,
        "name": tx_type.name,
        "account_type": account_type,
        "normal_balance": normal_balance,
        "description": tx_type.description or "",
    }


def _account_has_postings(account: AccountingLedgerAccount) -> bool:
    return AccountingJournalLine.objects.filter(account=account).exists()


def _check_code_collision(code: str, exclude_account_id: Optional[int]) -> None:
    qs = AccountingLedgerAccount.objects.filter(code=code)
    if exclude_account_id is not None:
        qs = qs.exclude(pk=exclude_account_id)
    if qs.exists():
        raise ValidationError(
            {
                "code": (
                    f"A chart-of-accounts entry with code '{code}' already exists. "
                    "Choose a different transaction type code or unlink the existing account."
                )
            }
        )


@db_transaction.atomic
def sync_ledger_account_for_type(
    tx_type: AccountingTransactionType,
) -> SyncResult:
    """Create or update the managed ledger account for the given type.

    Sync targets, in priority order:

    1. ``managed_ledger_account`` — auto-managed entry created/owned by the
       transaction type. When ``auto_manage_ledger_account`` is True and no
       managed account exists yet, one is created.
    2. ``default_ledger_account`` — user-picked GL account. When this is set
       (and no managed account is linked) the sync still runs and updates
       the linked default account in place. Code is NOT overwritten on a
       user-picked account because the user owns the chart code; only
       descriptive / classification fields are reconciled.

    If neither account is linked and ``auto_manage_ledger_account`` is False,
    the sync is skipped.
    """

    if tx_type.transaction_category not in _CATEGORY_TO_ACCOUNT_TYPE:
        raise ValidationError(
            {
                "transaction_category": (
                    f"Unsupported transaction category '{tx_type.transaction_category}'."
                )
            }
        )

    derived = _derive_fields(tx_type)

    # --- Case 1: a managed account already exists -> update it in place. ---
    if tx_type.managed_ledger_account_id is not None:
        return _update_managed_account(tx_type, derived)

    # --- Case 2: auto-manage is on -> create a fresh managed account. ---
    if tx_type.auto_manage_ledger_account:
        _check_code_collision(derived["code"], exclude_account_id=None)
        account = AccountingLedgerAccount.objects.create(
            code=derived["code"],
            name=derived["name"],
            account_type=derived["account_type"],
            normal_balance=derived["normal_balance"],
            description=derived["description"],
            is_active=tx_type.is_active,
            is_system_managed=True,
        )
        AccountingTransactionType.objects.filter(pk=tx_type.pk).update(
            managed_ledger_account=account
        )
        tx_type.managed_ledger_account = account
        return SyncResult(
            action="created",
            account_id=account.pk,
            account_code=account.code,
            account_name=account.name,
        )

    # --- Case 3: only a default (user-picked) account is linked. ---
    if tx_type.default_ledger_account_id is not None:
        return _update_default_account(tx_type, derived)

    return SyncResult(
        action="skipped",
        reason="No linked ledger account to sync (set a default account or enable auto-manage).",
    )


def _update_managed_account(
    tx_type: AccountingTransactionType, derived: dict
) -> SyncResult:
    account = tx_type.managed_ledger_account
    warnings: list[str] = []

    code_changed = account.code != derived["code"]
    type_changed = account.account_type != derived["account_type"]
    normal_balance_changed = account.normal_balance != derived["normal_balance"]

    if code_changed:
        _check_code_collision(derived["code"], exclude_account_id=account.pk)

    structural_change = code_changed or type_changed or normal_balance_changed
    if structural_change and _account_has_postings(account):
        warnings.append(
            "The linked chart-of-accounts entry already has journal postings; "
            "structural changes (code, account type, or normal balance) will affect historical reports."
        )

    account.code = derived["code"]
    account.name = derived["name"]
    account.account_type = derived["account_type"]
    account.normal_balance = derived["normal_balance"]
    account.description = derived["description"]
    account.is_active = tx_type.is_active
    account.is_system_managed = True
    account.save(
        update_fields=[
            "code",
            "name",
            "account_type",
            "normal_balance",
            "description",
            "is_active",
            "is_system_managed",
            "updated_at",
        ]
    )

    return SyncResult(
        action="updated",
        account_id=account.pk,
        account_code=account.code,
        account_name=account.name,
        warnings=warnings,
    )


def _update_default_account(
    tx_type: AccountingTransactionType, derived: dict
) -> SyncResult:
    """Sync metadata onto the user-picked default ledger account.

    User-owned accounts keep their existing ``code`` (the chart numbering is
    the user's), and we never flip ``is_system_managed`` on them. Only
    descriptive / classification fields are pushed.
    """
    account = tx_type.default_ledger_account
    warnings: list[str] = []

    type_changed = account.account_type != derived["account_type"]
    normal_balance_changed = account.normal_balance != derived["normal_balance"]

    if (type_changed or normal_balance_changed) and _account_has_postings(account):
        warnings.append(
            "The linked default chart-of-accounts entry already has journal postings; "
            "changes to account type or normal balance will affect historical reports."
        )

    account.name = derived["name"]
    account.account_type = derived["account_type"]
    account.normal_balance = derived["normal_balance"]
    if derived["description"]:
        account.description = derived["description"]
    account.is_active = tx_type.is_active and account.is_active
    account.save(
        update_fields=[
            "name",
            "account_type",
            "normal_balance",
            "description",
            "is_active",
            "updated_at",
        ]
    )

    return SyncResult(
        action="updated",
        account_id=account.pk,
        account_code=account.code,
        account_name=account.name,
        warnings=warnings,
    )
