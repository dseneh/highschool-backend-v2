"""Central throttles for security-sensitive public API endpoints."""

import hashlib
import hmac

from django.conf import settings
from django.core.cache import cache

from rest_framework.throttling import SimpleRateThrottle


class SensitiveEndpointRateThrottle(SimpleRateThrottle):
    """Apply tighter IP-based limits to authentication and public discovery routes."""

    ROUTE_SCOPES = {
        "/api/v1/auth/login/": "login",
        "/api/v1/auth/password/forgot/": "password_reset",
        "/api/v1/auth/account-activation/verify-code/": "activation",
        "/api/v1/auth/account-activation/resend-code/": "activation",
        "/api/v1/auth/mfa/verify/": "mfa_verify",
        "/api/v1/auth/mfa/resend/": "mfa_resend",
        "/api/v1/auth/security/mfa-recovery/": "mfa_recovery",
        "/api/v1/auth/security/mfa-recovery/verify/": "mfa_recovery",
        "/api/v1/auth/security/step-up/": "step_up_start",
        "/api/v1/auth/security/step-up/verify/": "step_up_verify",
        "/api/v1/public/schools/": "public_search",
    }

    def __init__(self):
        # The scope is selected from the request path, so it is not available
        # when SimpleRateThrottle.__init__ normally resolves the rate.
        self.scope = None
        self.rate = None
        self.num_requests = None
        self.duration = None

    def get_scope(self, request):
        path = request.path if request.path.endswith("/") else f"{request.path}/"
        return self.ROUTE_SCOPES.get(path)

    def allow_request(self, request, view):
        self.scope = self.get_scope(request)
        if not self.scope:
            return True
        self.rate = self.get_rate()
        self.num_requests, self.duration = self.parse_rate(self.rate)
        return super().allow_request(request, view)

    def get_cache_key(self, request, view):
        if not self.scope:
            return None

        user = getattr(request, "user", None)
        if (
            self.scope in {"step_up_start", "step_up_verify"}
            and user is not None
            and getattr(user, "is_authenticated", False)
        ):
            tenant = request.headers.get("X-Tenant", "")
            subject = f"user:{user.pk}:tenant:{tenant}"
            ident = opaque_rate_limit_subject(subject)
        else:
            ident = self.get_ident(request)

        return self.cache_format % {"scope": self.scope, "ident": ident}


def opaque_rate_limit_subject(value):
    """Return a stable cache-safe digest without retaining account identifiers."""
    normalized = str(value or "").strip().casefold().encode("utf-8")
    secret = settings.SECRET_KEY.encode("utf-8")
    return hmac.new(secret, normalized, hashlib.sha256).hexdigest()


def claim_fixed_window_rate_limit(*, namespace, subject, limit, window_seconds):
    """Atomically claim one request in a cache-backed fixed window.

    ``cache.add`` and ``cache.incr`` are atomic in Redis, which is the production
    cache backend. The local-memory backend keeps the same behavior for tests and
    development. Subject values are hashed before being included in cache keys.
    """
    limit = max(1, int(limit))
    window_seconds = max(1, int(window_seconds))
    digest = opaque_rate_limit_subject(subject)
    key = f"security-rate-limit:{namespace}:{digest}"

    if cache.add(key, 1, timeout=window_seconds):
        return True

    try:
        count = cache.incr(key)
    except ValueError:
        # The entry may expire between add() and incr(); retry as a new window.
        return cache.add(key, 1, timeout=window_seconds)
    return count <= limit
