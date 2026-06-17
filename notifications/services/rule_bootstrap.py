"""Create or sync default notification automation rules."""

from __future__ import annotations

from notifications.management.commands.seed_notification_rules import (
    DEFAULT_RULES,
    TRANSCRIPT_RULE_SYNC_FIELDS,
)
from notifications.models import NotificationRule


def ensure_notification_rule(event_type: str) -> NotificationRule | None:
    """Ensure a default rule row exists (and transcript rules stay in sync)."""
    spec = next((item for item in DEFAULT_RULES if item["event_type"] == event_type), None)
    if not spec:
        return NotificationRule.objects.filter(event_type=event_type).first()

    defaults = {key: value for key, value in spec.items() if key != "event_type"}
    rule, created = NotificationRule.objects.get_or_create(
        event_type=event_type,
        defaults=defaults,
    )
    if created or not str(event_type).startswith("transcript_"):
        return rule

    updates = {}
    for field in TRANSCRIPT_RULE_SYNC_FIELDS:
        if field in defaults and getattr(rule, field) != defaults[field]:
            updates[field] = defaults[field]
    if updates:
        for field, value in updates.items():
            setattr(rule, field, value)
        rule.save(update_fields=[*updates.keys(), "updated_at"])
    return rule


def ensure_all_default_notification_rules() -> None:
    for spec in DEFAULT_RULES:
        ensure_notification_rule(spec["event_type"])
