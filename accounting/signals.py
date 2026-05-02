"""
Signal handlers for the accounting app.
"""

from __future__ import annotations

import threading

from django.core.exceptions import ValidationError
from django.db import transaction as db_transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from accounting.models import AccountingTransactionType
from accounting.services.transaction_type_sync import sync_ledger_account_for_type


# Thread-local guard to avoid recursion when the sync service writes back to
# the same `AccountingTransactionType` row to link the managed account.
_sync_guard = threading.local()


def _is_in_sync(tx_type_pk: int) -> bool:
    return getattr(_sync_guard, "active_pk", None) == tx_type_pk


@receiver(post_save, sender=AccountingTransactionType)
def auto_sync_managed_ledger_account(sender, instance, created, update_fields, **kwargs):
    """Auto-create or update the managed chart-of-accounts entry on save."""

    if not instance.auto_manage_ledger_account:
        return
    if _is_in_sync(instance.pk):
        return
    # If only the FK link was updated by the sync service itself, skip.
    if update_fields is not None and set(update_fields) <= {"managed_ledger_account"}:
        return

    def _run():
        _sync_guard.active_pk = instance.pk
        try:
            sync_ledger_account_for_type(instance)
        except ValidationError:
            # Surface validation errors only via explicit serializer/endpoint
            # calls; swallow here so model saves from admin/shell don't crash.
            pass
        finally:
            _sync_guard.active_pk = None

    db_transaction.on_commit(_run)
