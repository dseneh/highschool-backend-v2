"""Reusable email validation helpers for backend flows."""

from __future__ import annotations

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import validate_email


DEFAULT_REQUIRED_EMAIL_MESSAGE = (
    "A valid email is required on the source record before generating a user account."
)


def normalize_email(value) -> str:
    """Return a trimmed email string (or empty string)."""
    return str(value or "").strip()


def is_valid_email(value) -> bool:
    """Return True when the provided email passes Django validation."""
    email = normalize_email(value)
    if not email:
        return False
    try:
        validate_email(email)
    except DjangoValidationError:
        return False
    return True


def require_valid_email(value, *, message: str = DEFAULT_REQUIRED_EMAIL_MESSAGE) -> str:
    """Return normalized email or raise ValueError when missing/invalid."""
    email = normalize_email(value)
    if not email:
        raise ValueError(message)
    if not is_valid_email(email):
        raise ValueError(message)
    return email
