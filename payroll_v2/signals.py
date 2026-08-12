from __future__ import annotations

import logging

from django.db import transaction as db_transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from accounting.models import AccountingCashTransaction

from .services import apply_salary_advance_repayment_from_finance_transaction

logger = logging.getLogger(__name__)


@receiver(post_save, sender=AccountingCashTransaction)
def apply_completed_salary_advance_early_repayment(sender, instance, **kwargs):
    """Apply salary advance early repayment only after finance transaction completion."""

    if instance.status != AccountingCashTransaction.TransactionStatus.COMPLETED:
        return

    def _run():
        try:
            apply_salary_advance_repayment_from_finance_transaction(
                finance_transaction=instance,
                actor=getattr(instance, "updated_by", None),
            )
        except Exception as exc:  # pragma: no cover - defensive signal guard
            logger.warning(
                "Failed applying salary advance repayment from finance tx %s: %s",
                instance.pk,
                exc,
            )

    db_transaction.on_commit(_run)
