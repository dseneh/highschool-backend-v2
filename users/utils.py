"""
Utility functions for the users app.

Covers:
- Password-reset URL construction
- Frontend URL building
"""

from urllib.parse import urljoin, urlparse

from django.conf import settings


def build_frontend_url(school_workspace: str | None = None, path: str | None = None) -> str:
    """
    Construct a frontend URL based on environment configuration.

    Preferred mode    → https://<workspace>.domain.com<path>
    Dev path mode     → http://localhost:3000/s/<workspace><path> (optional fallback)

    Settings consulted:
        FRONTEND_DOMAIN             Base URL of the frontend (default: http://localhost:3000)
        FRONTEND_USE_SUBDOMAIN      True = tenant subdomain URL when workspace is present
        FRONTEND_DEV_MODE           True = dev path fallback when subdomain mode is disabled
        FRONTEND_PASSWORD_RESET_PATH  Path used when *path* is None
    """
    frontend_domain: str = getattr(settings, "FRONTEND_DOMAIN", "http://localhost:3000")
    use_subdomain: bool = getattr(settings, "FRONTEND_USE_SUBDOMAIN", True)
    is_dev_mode: bool = getattr(settings, "FRONTEND_DEV_MODE", True)
    default_path: str = getattr(settings, "FRONTEND_PASSWORD_RESET_PATH", "/reset-password")

    effective_path = path or default_path

    # Preferred behavior: tenant subdomain URL (works for localhost too: tenant.localhost)
    if school_workspace and use_subdomain:
        parsed = urlparse(frontend_domain)
        scheme = parsed.scheme or "http"
        hostname = parsed.hostname or ""

        if hostname and not hostname.startswith(f"{school_workspace}."):
            workspace_domain = f"{school_workspace}.{hostname}"
        else:
            workspace_domain = hostname

        base = f"{scheme}://{workspace_domain}" if workspace_domain else frontend_domain
        if parsed.port:
            base += f":{parsed.port}"

        return urljoin(base, effective_path.lstrip("/"))

    # Optional fallback: dev path-style routing
    if is_dev_mode:
        if school_workspace:
            combined = f"/s/{school_workspace}{effective_path}"
        else:
            combined = effective_path
        return urljoin(frontend_domain, combined.lstrip("/"))

    # Production: subdomain routing
    if school_workspace:
        parsed = urlparse(frontend_domain)
        hostname = parsed.hostname or ""
        workspace_domain = f"{school_workspace}.{hostname}" if hostname else hostname
        base = f"{parsed.scheme}://{workspace_domain}"
        if parsed.port:
            base += f":{parsed.port}"
    else:
        base = frontend_domain

    return urljoin(base, effective_path.lstrip("/"))


def build_password_reset_url(school_workspace: str | None, uid: str, token: str) -> str:
    """
    Build the full password-reset URL including UID and token query parameters.

    The frontend is expected to parse ?uid=…&token=…&workspace=… and POST them
    back to /api/v1/auth/password/reset/.
    """
    reset_path = getattr(settings, "FRONTEND_PASSWORD_RESET_PATH", "/reset-password")
    base_url = build_frontend_url(school_workspace, reset_path)

    query_params = f"?uid={uid}&token={token}"
    if school_workspace:
        query_params += f"&workspace={school_workspace}"

    return base_url + query_params
