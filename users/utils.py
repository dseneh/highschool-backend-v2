"""
Utility functions for the users app.

Covers:
- Password-reset URL construction
- Frontend URL building
"""

from ipaddress import ip_address
from urllib.parse import urljoin, urlparse

from django.conf import settings


def _host_uses_path_based_tenants(hostname: str) -> bool:
    """Match frontend routing for localhost/bare-IP tenant resolution."""
    host = (hostname or "").strip().lower()
    if not host:
        return False
    if host in {"localhost", "127.0.0.1"}:
        return True
    try:
        ip_address(host)
        return True
    except ValueError:
        return False


def build_frontend_url(school_workspace: str | None = None, path: str | None = None) -> str:
    """
    Construct a frontend URL based on environment configuration.

    Preferred mode    → https://<workspace>.domain.com<path>
    Dev path mode     → http://localhost:3000/<workspace><path> (optional fallback)

    Settings consulted:
        FRONTEND_DOMAIN             Base URL of the frontend (default: http://localhost:3000)
        FRONTEND_USE_SUBDOMAIN      True = tenant subdomain URL when workspace is present
        FRONTEND_DEV_MODE           True = dev path fallback when subdomain mode is disabled
        FRONTEND_PASSWORD_RESET_PATH  Path used when *path* is None
    """
    frontend_domain: str = getattr(settings, "FRONTEND_DOMAIN", "http://localhost:3000")
    frontend_subdomain_base: str = getattr(settings, "FRONTEND_SUBDOMAIN_BASE", "")
    use_subdomain: bool = getattr(settings, "FRONTEND_USE_SUBDOMAIN", True)
    is_dev_mode: bool = getattr(settings, "FRONTEND_DEV_MODE", True)
    default_path: str = getattr(settings, "FRONTEND_PASSWORD_RESET_PATH", "/reset-password")

    effective_path = path or default_path

    parsed = urlparse(frontend_domain)
    hostname = parsed.hostname or ""

    # On localhost/bare-IP environments, the frontend uses path-based tenants:
    # /<workspace>/<path>. Keep URL generation aligned with that routing mode.
    if school_workspace and _host_uses_path_based_tenants(hostname):
        path_with_workspace = f"/{school_workspace}{effective_path if effective_path.startswith('/') else f'/{effective_path}'}"
        return urljoin(frontend_domain, path_with_workspace.lstrip("/"))

    # Preferred behavior: tenant subdomain URL (DNS-based environments)
    if school_workspace and use_subdomain:
        subdomain_base = str(frontend_subdomain_base or "").strip()
        if subdomain_base:
            if "://" not in subdomain_base:
                subdomain_base = f"{parsed.scheme or 'https'}://{subdomain_base}"
            parsed_base = urlparse(subdomain_base)
            scheme = parsed_base.scheme or parsed.scheme or "https"
            hostname = parsed_base.hostname or hostname
            port = parsed_base.port
        else:
            scheme = parsed.scheme or "http"
            port = parsed.port

        if hostname and not hostname.startswith(f"{school_workspace}."):
            workspace_domain = f"{school_workspace}.{hostname}"
        else:
            workspace_domain = hostname

        base = f"{scheme}://{workspace_domain}" if workspace_domain else frontend_domain
        if port:
            base += f":{port}"

        return urljoin(base, effective_path.lstrip("/"))

    # Optional fallback: explicit path-style routing when subdomain mode is disabled.
    if is_dev_mode:
        if school_workspace:
            combined = f"/{school_workspace}{effective_path}"
        else:
            combined = effective_path
        return urljoin(frontend_domain, combined.lstrip("/"))

    # Production: subdomain routing
    if school_workspace:
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
    # if school_workspace:
    #     query_params += f"&workspace={school_workspace}"

    return base_url + query_params


def build_activation_url(school_workspace: str | None) -> str:
    """Build the tenant-aware activate-account URL."""
    return build_frontend_url(school_workspace, "/activate-account")


def send_welcome_email(user, temporary_password: str, tenant=None) -> bool:
    """Send the account-created welcome email for any newly created account."""
    import logging

    from common.email_service import send_account_created_email

    workspace = getattr(tenant, "schema_name", None)
    sent = send_account_created_email(
        user=user,
        temporary_password=temporary_password,
        login_url=build_frontend_url(workspace, "/login"),
        school=tenant,
    )
    if not sent:
        logging.getLogger(__name__).warning(
            "Account-created email could not be sent to user %s",
            getattr(user, "username", None) or getattr(user, "id_number", None),
        )
    return sent
