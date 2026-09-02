"""Central throttles for security-sensitive public API endpoints."""

from rest_framework.throttling import SimpleRateThrottle


class SensitiveEndpointRateThrottle(SimpleRateThrottle):
    """Apply tighter IP-based limits to authentication and public discovery routes."""

    ROUTE_SCOPES = {
        "/api/v1/auth/login/": "login",
        "/api/v1/auth/password/forgot/": "password_reset",
        "/api/v1/auth/account-activation/verify-code/": "activation",
        "/api/v1/auth/account-activation/resend-code/": "activation",
        "/api/v1/auth/security/mfa/challenge/": "mfa_challenge",
        "/api/v1/public/schools/": "public_search",
    }

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
        ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}
