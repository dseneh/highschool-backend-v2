"""Resolve students from UUIDs or human-facing id numbers."""

from __future__ import annotations

import uuid

from students.models import Student


def resolve_student_from_identifier(value) -> Student | None:
    """Look up a student by UUID pk, ``id_number``, or ``prev_id_number``."""
    if value is None:
        return None
    if isinstance(value, dict):
        value = value.get("id")
    candidate = str(value).strip()
    if not candidate:
        return None

    try:
        parsed = uuid.UUID(candidate)
    except (ValueError, AttributeError, TypeError):
        parsed = None

    if parsed is not None:
        student = Student.objects.filter(pk=parsed).first()
        if student is not None:
            return student

    return (
        Student.objects.filter(id_number=candidate).first()
        or Student.objects.filter(prev_id_number=candidate).first()
    )


def resolve_student_pk_from_identifier(value) -> str | None:
    student = resolve_student_from_identifier(value)
    return str(student.pk) if student is not None else None
