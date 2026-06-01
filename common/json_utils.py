"""JSON helpers for Django JSONField persistence."""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, time
from decimal import Decimal

from django.db.models.query import QuerySet


def make_json_safe(value):
    """Return a structure safe for Django JSONField / json.dumps."""
    if isinstance(value, dict):
        return {str(key): make_json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, QuerySet)):
        return [make_json_safe(item) for item in value]
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.isoformat()
    if hasattr(value, "items") and callable(value.items) and not isinstance(value, (str, bytes)):
        try:
            return make_json_safe(dict(value))
        except TypeError:
            pass
    return value


def dumps_json_safe(value) -> str:
    return json.dumps(make_json_safe(value))
