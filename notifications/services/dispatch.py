from __future__ import annotations

import logging

from notifications.models import NotificationCampaign, NotificationRule, TenantNotificationSettings
from notifications.services.campaign_send import create_and_send_campaign
from notifications.services.rule_bootstrap import ensure_notification_rule

logger = logging.getLogger(__name__)


def dispatch_from_rule(event_type: str, context: dict | None = None) -> NotificationCampaign | None:
    context = context or {}
    ensure_notification_rule(event_type)
    rule = NotificationRule.objects.filter(event_type=event_type, enabled=True).first()
    if not rule:
        logger.warning("Notification rule missing or disabled: %s", event_type)
        return None

    settings = TenantNotificationSettings.get_solo()
    if event_type == NotificationRule.EventType.GRADE_PUBLISHED and not settings.grade_publish_enabled:
        return None

    title = _render_template(rule.title_template or _default_title(event_type), context)
    body = _render_template(rule.body_template or _default_body(event_type), context)
    audience = rule.audience_override if rule.audience_override else context.get("audience", {})
    channels = rule.channels or ["in_app", "email"]

    return create_and_send_campaign(
        title=title,
        body=body,
        category=rule.category,
        channels=channels,
        audience=audience,
        source=NotificationCampaign.Source.RULE,
        created_by=context.get("created_by"),
        rule=rule,
        action_url=context.get("action_url", ""),
    )


def _render_template(template: str, context: dict) -> str:
    try:
        return template.format(**context)
    except (KeyError, ValueError):
        return template


def _default_title(event_type: str) -> str:
    defaults = {
        NotificationRule.EventType.GRADE_PUBLISHED: "Grades published for {student_name}",
        NotificationRule.EventType.PAYMENT_DUE_REMINDER: "Payment reminder: due {due_date}",
        NotificationRule.EventType.ATTENDANCE_ABSENT: "Absence recorded for {student_name}",
        NotificationRule.EventType.TRANSCRIPT_REQUESTED: "New transcript request from {student_name}",
        NotificationRule.EventType.TRANSCRIPT_APPROVED: "Transcript access approved",
        NotificationRule.EventType.TRANSCRIPT_DENIED: "Transcript request update",
    }
    return defaults.get(event_type, "School notification")


def _default_body(event_type: str) -> str:
    defaults = {
        NotificationRule.EventType.GRADE_PUBLISHED: (
            "Grades have been published for {student_name}. "
            "Please sign in to view the latest results."
        ),
        NotificationRule.EventType.PAYMENT_DUE_REMINDER: (
            "A payment of {amount_due} is due on {due_date} for {student_name}. "
            "Please review your account balance."
        ),
        NotificationRule.EventType.ATTENDANCE_ABSENT: (
            "{student_name} was marked absent on {date}. "
            "Contact the school if you have questions."
        ),
        NotificationRule.EventType.TRANSCRIPT_REQUESTED: (
            "{student_name} submitted an official transcript request."
        ),
        NotificationRule.EventType.TRANSCRIPT_APPROVED: (
            "Your official transcript request has been approved."
        ),
        NotificationRule.EventType.TRANSCRIPT_DENIED: (
            "Your official transcript request was not approved."
        ),
    }
    return defaults.get(event_type, "You have a new notification from your school.")
