"""Provider-neutral primitives for future payment integrations.

These helpers deliberately do not encode any provider-specific signature format.
Adapters should normalize provider headers, then call these primitives.
"""

import hashlib
import hmac
import time
from dataclasses import dataclass

from django.core.cache import cache


@dataclass(frozen=True)
class WebhookVerificationResult:
    valid: bool
    reason: str = ""


def constant_time_equal(left: str, right: str) -> bool:
    return hmac.compare_digest(str(left or ""), str(right or ""))


def verify_hmac_sha256(payload: bytes, signature: str, secret: str, *, prefix: str = "") -> WebhookVerificationResult:
    """Verify a hex HMAC-SHA256 signature in constant time."""
    if not secret:
        return WebhookVerificationResult(False, "missing_secret")
    supplied = str(signature or "").strip()
    if prefix and supplied.startswith(prefix):
        supplied = supplied[len(prefix):]
    expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return WebhookVerificationResult(constant_time_equal(expected, supplied), "" if constant_time_equal(expected, supplied) else "signature_mismatch")


def timestamp_is_fresh(timestamp: int | str, *, tolerance_seconds: int = 300) -> bool:
    try:
        value = int(timestamp)
    except (TypeError, ValueError):
        return False
    return abs(int(time.time()) - value) <= tolerance_seconds


def build_idempotency_key(*parts) -> str:
    material = ":".join(str(part) for part in parts if part is not None)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def claim_webhook_event(provider: str, event_id: str, *, ttl_seconds: int = 86400) -> bool:
    """Atomically claim an event id. False means it was already processed/claimed.

    Production must use shared Redis for this to protect all replicas.
    """
    digest = hashlib.sha256(f"{provider}:{event_id}".encode("utf-8")).hexdigest()
    return bool(cache.add(f"payment:webhook:{digest}", "claimed", timeout=ttl_seconds))
