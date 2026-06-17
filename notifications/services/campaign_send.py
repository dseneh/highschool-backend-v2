from __future__ import annotations

import logging
from typing import Iterable

from django.db import transaction
from django.utils import timezone

from notifications.models import (
    Notification,
    NotificationCampaign,
    NotificationDelivery,
)
from notifications.services.audience import resolve_user_ids, user_wants_email
from notifications.tasks import send_campaign_emails_async

logger = logging.getLogger(__name__)


def create_and_send_campaign(
    *,
    title: str,
    body: str,
    category: str,
    channels: list,
    audience: dict,
    source: str,
    created_by,
    rule=None,
    is_pinned: bool = False,
    action_url: str = "",
    banner_variant: str = NotificationCampaign.BannerVariant.INFO,
    banner_dismissible: bool = True,
    banner_starts_at=None,
    banner_ends_at=None,
) -> NotificationCampaign:
    channels = list(channels or ["in_app"])
    valid_channels = {"in_app", "email", "banner"}
    channels = [c for c in channels if c in valid_channels]
    if not channels:
        channels = ["in_app"]
    deliver_banner = "banner" in channels
    # A banner without an in-app notification would have nothing to attach a
    # per-user dismissal to. Always materialize an in-app row alongside.
    if deliver_banner and "in_app" not in channels:
        channels.append("in_app")

    campaign = NotificationCampaign.objects.create(
        title=title,
        body=body,
        category=category,
        channels=channels,
        audience=audience or {},
        source=source,
        rule=rule,
        status=NotificationCampaign.Status.QUEUED,
        is_pinned=is_pinned,
        deliver_banner=deliver_banner,
        banner_variant=banner_variant or NotificationCampaign.BannerVariant.INFO,
        banner_dismissible=bool(banner_dismissible),
        banner_starts_at=banner_starts_at,
        banner_ends_at=banner_ends_at,
        created_by=created_by,
        updated_by=created_by,
    )

    recipient_ids = resolve_user_ids(audience, created_by, category=category)
    logger.info(
        "notifications.campaign_send resolved %d recipient(s) "
        "for campaign=%s audience=%s category=%s",
        len(recipient_ids),
        campaign.id,
        audience,
        category,
    )
    _materialize_recipients(
        campaign,
        recipient_ids,
        channels=channels,
        category=category,
        action_url=action_url,
    )

    materialized = Notification.objects.filter(campaign=campaign).count()
    logger.info(
        "notifications.campaign_send materialized %d Notification row(s) "
        "for campaign=%s (expected %d)",
        materialized,
        campaign.id,
        len(recipient_ids),
    )

    campaign.recipient_count = materialized
    campaign.status = NotificationCampaign.Status.SENT
    campaign.sent_at = timezone.now()
    campaign.save(update_fields=["recipient_count", "status", "sent_at", "updated_at"])

    if materialized == 0:
        logger.warning(
            "notifications.campaign_send produced zero inbox rows for campaign=%s audience=%s",
            campaign.id,
            audience,
        )

    if "email" in channels:
        send_campaign_emails_async(str(campaign.id))

    return campaign


def _materialize_recipients(
    campaign: NotificationCampaign,
    recipient_ids: Iterable,
    *,
    channels: list,
    category: str,
    action_url: str = "",
) -> None:
    recipient_ids = list(recipient_ids)
    if not recipient_ids:
        return

    notifications = [
        Notification(
            campaign=campaign,
            recipient_id=uid,
            action_url=action_url or "",
            created_by=campaign.created_by,
            updated_by=campaign.created_by,
        )
        for uid in recipient_ids
    ]

    deliveries = []
    if "email" in channels:
        for uid in recipient_ids:
            if user_wants_email(uid, category):
                deliveries.append(
                    NotificationDelivery(
                        campaign=campaign,
                        recipient_id=uid,
                        channel=NotificationDelivery.Channel.EMAIL,
                        status=NotificationDelivery.Status.PENDING,
                        created_by=campaign.created_by,
                        updated_by=campaign.created_by,
                    )
                )
            else:
                deliveries.append(
                    NotificationDelivery(
                        campaign=campaign,
                        recipient_id=uid,
                        channel=NotificationDelivery.Channel.EMAIL,
                        status=NotificationDelivery.Status.SKIPPED,
                        error="Email disabled by preference or missing address",
                        created_by=campaign.created_by,
                        updated_by=campaign.created_by,
                    )
                )

    with transaction.atomic():
        Notification.objects.bulk_create(notifications, ignore_conflicts=True)
        if deliveries:
            NotificationDelivery.objects.bulk_create(deliveries, ignore_conflicts=True)
