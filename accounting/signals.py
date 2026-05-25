"""
Signal handlers for the accounting app.
"""

from __future__ import annotations

import logging
import threading

from django.core.exceptions import ValidationError
from django.db import transaction as db_transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from accounting.models import AccountingCashTransaction, AccountingTransactionType
from accounting.services.transaction_type_sync import sync_ledger_account_for_type


logger = logging.getLogger(__name__)


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


# Recursion guard: ``recompute_student_year_payments`` only writes to
# ``AccountingStudentBill``, so it never re-fires this signal — but keep
# a thread-local in case someone later calls it from inside a bill save.
_recompute_guard = threading.local()

# Bulk upload sets this so we don't queue one on_commit recompute per row;
# the upload service batches recompute once per (student, year) afterward.
_bulk_upload_guard = threading.local()


class suppress_cash_tx_recompute:
    """Skip per-row bill recompute during bulk cash-transaction ingestion."""

    def __enter__(self):
        _bulk_upload_guard.active = True
        return self

    def __exit__(self, exc_type, exc, tb):
        _bulk_upload_guard.active = False
        return False


@receiver(post_save, sender=AccountingCashTransaction)
def refresh_student_bill_paid_amount(sender, instance, **kwargs):
    """Keep ``AccountingStudentBill.paid_amount`` in sync with the cash ledger.

    Whenever a cash transaction tied to a student is created or updated
    (status change, amount edit, void, etc.), recompute the student's bill
    paid_amount cache for the academic year that covers the transaction
    date. Runs after commit so the recompute observes the persisted state.
    """
    if getattr(_bulk_upload_guard, "active", False):
        return

    student = getattr(instance, "student", None)
    transaction_date = getattr(instance, "transaction_date", None)
    if not student or not transaction_date:
        return

    if getattr(_recompute_guard, "active", False):
        return

    def _run():
        # Imported lazily to avoid circular imports at app startup.
        from academics.models import AcademicYear
        from accounting.services.payment_allocation import (
            recompute_student_year_payments,
        )

        academic_year = AcademicYear.objects.filter(
            start_date__lte=transaction_date,
            end_date__gte=transaction_date,
        ).first()
        if not academic_year:
            return

        _recompute_guard.active = True
        try:
            recompute_student_year_payments(student, academic_year)
        except Exception as exc:
            # Surface in logs; don't propagate, signals shouldn't break
            # the originating write.
            logger.warning(
                "post_save recompute failed for cash_tx=%s student=%s: %s",
                instance.pk,
                getattr(student, "id", None),
                exc,
            )
        finally:
            _recompute_guard.active = False

    db_transaction.on_commit(_run)
