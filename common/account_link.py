"""Shared helpers for records that can be linked to a login account.

Students, staff, and employees all track their account via the
``user_account_id_number`` column, so the "already has an account" filter is
defined once and reused by every list endpoint that feeds an account-creation
picker.
"""

from __future__ import annotations

from django.db.models import Q

TRUE_VALUES = {"true", "1", "yes"}
FALSE_VALUES = {"false", "0", "no"}

LINKED_TO_ACCOUNT = Q(user_account_id_number__isnull=False) & ~Q(user_account_id_number="")


def normalize_flag(value) -> str:
    """Accept raw query-param values, including QueryDict list values."""
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    return str(value).strip().lower() if value is not None else ""


def filter_by_user_account(queryset, value):
    """Keep only linked (``true``) or unlinked (``false``) records."""
    normalized = normalize_flag(value)
    if normalized in TRUE_VALUES:
        return queryset.filter(LINKED_TO_ACCOUNT)
    if normalized in FALSE_VALUES:
        return queryset.exclude(LINKED_TO_ACCOUNT)
    return queryset
