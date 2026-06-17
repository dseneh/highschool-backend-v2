"""Resolve students from UUIDs or human-facing id numbers."""

from __future__ import annotations

from students.models import Student
from students.services.student_lookup import get_student_by_identifier_or_none


def resolve_student_from_identifier(value) -> Student | None:
    """Look up a student by UUID pk, ``id_number``, or ``prev_id_number``."""
    return get_student_by_identifier_or_none(value)


def resolve_student_pk_from_identifier(value) -> str | None:
    student = resolve_student_from_identifier(value)
    return str(student.pk) if student is not None else None
