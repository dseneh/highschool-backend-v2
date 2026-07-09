"""Background billing reminder delivery."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def send_billing_reminders_async() -> None:
    """Run billing reminders in a background thread (cron-friendly)."""
    import threading

    def _run():
        try:
            from billing.services.reminders import send_all_billing_reminders

            totals = send_all_billing_reminders()
            logger.info(
                "Billing reminders finished: checked=%s sent=%s",
                totals["tenants_checked"],
                totals["emails_sent"],
            )
        except Exception:
            logger.exception("Billing reminder job failed")

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()


try:
    from celery import shared_task

    @shared_task(name="billing.send_billing_reminders")
    def send_billing_reminders_celery():
        from billing.services.reminders import send_all_billing_reminders

        return send_all_billing_reminders()
except ImportError:  # pragma: no cover - celery optional
    send_billing_reminders_celery = None
