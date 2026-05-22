"""Background email delivery for notification campaigns."""

from __future__ import annotations

import logging
import threading

from django.utils import timezone
from django_tenants.utils import schema_context

logger = logging.getLogger(__name__)


def send_campaign_emails_async(campaign_id: str, schema_name: str | None = None) -> None:
    from django.db import connection

    schema = schema_name or connection.schema_name

    def _run():
        try:
            if schema and schema != "public":
                with schema_context(schema):
                    _send_campaign_emails(campaign_id)
            else:
                _send_campaign_emails(campaign_id)
        except Exception as exc:
            logger.exception("Campaign email send failed for %s: %s", campaign_id, exc)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()


def _send_campaign_emails(campaign_id: str) -> None:
    from common.email_service import send_notification_email
    from notifications.models import NotificationCampaign, NotificationDelivery
    from users.models import User

    try:
        campaign = NotificationCampaign.objects.get(id=campaign_id)
    except NotificationCampaign.DoesNotExist:
        return

    pending = NotificationDelivery.objects.filter(
        campaign=campaign,
        channel=NotificationDelivery.Channel.EMAIL,
        status=NotificationDelivery.Status.PENDING,
    ).select_related("recipient")

    for delivery in pending:
        with schema_context("public"):
            try:
                user = User.objects.get(id=delivery.recipient_id)
            except User.DoesNotExist:
                delivery.status = NotificationDelivery.Status.FAILED
                delivery.error = "User not found"
                delivery.save(update_fields=["status", "error", "updated_at"])
                continue

        ok = send_notification_email(
            user=user,
            subject=campaign.title,
            body=campaign.body,
            category=campaign.category,
        )
        delivery.sent_at = timezone.now()
        if ok:
            delivery.status = NotificationDelivery.Status.SENT
            delivery.error = ""
        else:
            delivery.status = NotificationDelivery.Status.FAILED
            delivery.error = "Email send failed"
        delivery.save(update_fields=["status", "error", "sent_at", "updated_at"])
