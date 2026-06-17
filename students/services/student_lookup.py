"""Resolve students by UUID primary key or human-facing identifiers."""

from __future__ import annotations

import uuid
from typing import Any

from students.models import Student


def get_student_by_identifier(value: Any) -> Student:
    """
    Look up a student by UUID pk, id_number, or prev_id_number.

    Raises Student.DoesNotExist when no match is found.
    """
    student = get_student_by_identifier_or_none(value)
    if student is None:
        candidate = _normalize_lookup_value(value)
        raise Student.DoesNotExist(
            f"Student matching query does not exist for identifier '{candidate}'."
        )
    return student


def get_student_by_identifier_or_none(value: Any) -> Student | None:
    """Look up a student by UUID pk, id_number, or prev_id_number."""
    candidate = _normalize_lookup_value(value)
    if not candidate:
        return None

    parsed_uuid: uuid.UUID | None = None
    try:
        parsed_uuid = uuid.UUID(candidate)
    except (ValueError, AttributeError, TypeError):
        parsed_uuid = None

    if parsed_uuid is not None:
        student = Student.objects.filter(pk=parsed_uuid).first()
        if student is not None:
            return student

    return (
        Student.objects.filter(id_number=candidate).first()
        or Student.objects.filter(prev_id_number=candidate).first()
    )


def _normalize_lookup_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        value = value.get("id") or value.get("id_number")
    return str(value).strip()
