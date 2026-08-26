"""Consistent API error responses."""

from __future__ import annotations

from collections.abc import Mapping

from rest_framework.response import Response


def detail_from_error(data) -> str:
    """Flatten DRF/Django validation details into one client-facing message."""
    if isinstance(data, Mapping):
        for field, value in data.items():
            message = detail_from_error(value)
            if message:
                return message if field in {"detail", "non_field_errors"} else f"{field}: {message}"
        return "An error occurred."
    if isinstance(data, (list, tuple)):
        for item in data:
            message = detail_from_error(item)
            if message:
                return message
        return "An error occurred."
    return str(data) if data else "An error occurred."


def error_response(error, *, status_code: int = 400, error_code: str | None = None) -> Response:
    """Build the standard ``{"detail": ...}`` response for an API error."""
    payload = {"detail": detail_from_error(getattr(error, "detail", error))}
    if error_code:
        payload["error_code"] = error_code
    return Response(payload, status=status_code)
