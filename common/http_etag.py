"""Small helpers for private, per-user HTTP caching with ETags."""

from __future__ import annotations

from hashlib import sha1
from typing import Any

from rest_framework import status
from rest_framework.response import Response


def _normalize_etag_part(value: Any) -> str:
    if value is None:
        return "0"
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def build_etag(*parts: Any) -> str:
    """Build a stable weak etag fingerprint from ordered parts."""
    payload = "|".join(_normalize_etag_part(part) for part in parts)
    return sha1(payload.encode("utf-8")).hexdigest()


def maybe_not_modified(request, etag: str) -> Response | None:
    """Return 304 when the client's ``If-None-Match`` matches ``etag``."""
    if_none_match = (request.headers.get("If-None-Match") or "").strip()
    if if_none_match and if_none_match.strip('"') == etag:
        response = Response(status=status.HTTP_304_NOT_MODIFIED)
        attach_etag(response, etag)
        return response
    return None


def attach_etag(response: Response, etag: str) -> Response:
    response["ETag"] = f'"{etag}"'
    response["Cache-Control"] = "private, max-age=0, must-revalidate"
    return response
