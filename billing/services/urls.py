from __future__ import annotations

from urllib.parse import urlparse

from users.utils import build_frontend_url

BILLING_SETTINGS_PATH = "/settings?tab=billing"


def build_billing_settings_url(tenant) -> str:
    """Tenant-scoped billing settings URL, e.g. https://ldtc.ezyschool.app/settings?tab=billing."""
    return build_frontend_url(tenant.schema_name, BILLING_SETTINGS_PATH)


def build_billing_checkout_urls(tenant) -> tuple[str, str]:
    base = build_billing_settings_url(tenant)
    return f"{base}&checkout=success", f"{base}&checkout=cancel"


def resolve_checkout_urls(tenant, *, success_url: str | None, cancel_url: str | None) -> tuple[str, str]:
    default_success, default_cancel = build_billing_checkout_urls(tenant)
    success = (success_url or default_success).strip()
    cancel = (cancel_url or default_cancel).strip()
    if not _url_allowed_for_tenant(success, tenant) or not _url_allowed_for_tenant(cancel, tenant):
        return default_success, default_cancel
    return success, cancel


def resolve_portal_return_url(tenant, *, return_url: str | None) -> str:
    default = build_billing_settings_url(tenant)
    candidate = (return_url or default).strip()
    if not _url_allowed_for_tenant(candidate, tenant):
        return default
    return candidate


def _url_allowed_for_tenant(url: str, tenant) -> bool:
    """Only allow redirects back to this tenant's frontend host."""
    if not url:
        return False

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False

    hostname = (parsed.hostname or "").lower()
    workspace = (tenant.schema_name or "").lower()
    if not workspace:
        return False

    allowed_hosts = _allowed_frontend_hosts(workspace)
    return hostname in allowed_hosts


def _allowed_frontend_hosts(workspace: str) -> set[str]:
    from django.conf import settings

    hosts: set[str] = set()
    frontend_domain = getattr(settings, "FRONTEND_DOMAIN", "http://localhost:3000")
    parsed = urlparse(frontend_domain)
    base_host = (parsed.hostname or "").lower()

    if base_host:
        hosts.add(base_host)
        hosts.add(f"{workspace}.{base_host}")

    # Local dev: tenant.localhost
    if base_host in {"localhost", "127.0.0.1"}:
        hosts.add("localhost")
        hosts.add("127.0.0.1")
        hosts.add(f"{workspace}.localhost")

    return hosts
