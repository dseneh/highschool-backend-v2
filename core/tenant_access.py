"""Tenant workspace access restriction helpers (single active restriction)."""

from __future__ import annotations

from dataclasses import dataclass

from rest_framework.exceptions import ValidationError

RESTRICTION_NONE = "none"
RESTRICTION_WORKSPACE_DISABLED = "workspace_disabled"
RESTRICTION_SIGN_IN_DISABLED = "sign_in_disabled"
RESTRICTION_ADMIN_LOGIN_ONLY = "admin_login_only"
RESTRICTION_MAINTENANCE = "maintenance"
RESTRICTION_STATUS_ON_HOLD = "status_on_hold"
RESTRICTION_STATUS_CLOSED = "status_closed"
RESTRICTION_STATUS_INACTIVE = "status_inactive"

RESTRICTION_PRIORITY = (
    RESTRICTION_WORKSPACE_DISABLED,
    RESTRICTION_SIGN_IN_DISABLED,
    RESTRICTION_ADMIN_LOGIN_ONLY,
    RESTRICTION_MAINTENANCE,
    RESTRICTION_STATUS_ON_HOLD,
    RESTRICTION_STATUS_CLOSED,
    RESTRICTION_STATUS_INACTIVE,
)

STATUS_BY_RESTRICTION = {
    RESTRICTION_STATUS_ON_HOLD: "on_hold",
    RESTRICTION_STATUS_CLOSED: "closed",
    RESTRICTION_STATUS_INACTIVE: "inactive",
}

RESTRICTION_ERROR_CODES = {
    RESTRICTION_WORKSPACE_DISABLED: "TENANT_DISABLED",
    RESTRICTION_SIGN_IN_DISABLED: "TENANT_LOGIN_DISABLED",
    RESTRICTION_ADMIN_LOGIN_ONLY: "TENANT_ADMIN_ONLY_LOGIN",
    RESTRICTION_MAINTENANCE: "TENANT_MAINTENANCE_MODE",
    RESTRICTION_STATUS_ON_HOLD: "TENANT_STATUS_BLOCKED",
    RESTRICTION_STATUS_CLOSED: "TENANT_STATUS_BLOCKED",
    RESTRICTION_STATUS_INACTIVE: "TENANT_STATUS_BLOCKED",
}

SIGN_IN_RESTRICTIONS = frozenset(
    {RESTRICTION_SIGN_IN_DISABLED, RESTRICTION_ADMIN_LOGIN_ONLY}
)


@dataclass(frozen=True)
class TenantAccessDecision:
    allowed: bool
    error_code: str | None = None
    detail: str | None = None
    status_code: int = 423
    restriction: str = RESTRICTION_NONE


def _tenant_active(tenant) -> bool:
    return bool(getattr(tenant, "active", True))


def normalize_frontend_path(path: str) -> str:
    value = str(path or "").strip()
    if not value:
        return ""
    if not value.startswith("/"):
        value = f"/{value}"
    return value if value == "/" else value.rstrip("/")


def is_path_allowed_by_prefix(path: str, allowed_prefixes) -> bool:
    normalized_path = normalize_frontend_path(path)
    if not normalized_path:
        return False

    for prefix in allowed_prefixes or []:
        normalized_prefix = normalize_frontend_path(prefix)
        if not normalized_prefix:
            continue
        if normalized_prefix == "/":
            if normalized_path == "/":
                return True
            continue
        if normalized_prefix.endswith("-"):
            if normalized_path.startswith(normalized_prefix):
                return True
            continue
        if normalized_path == normalized_prefix or normalized_path.startswith(
            f"{normalized_prefix}/"
        ):
            return True

    return False


def is_user_in_override_list(user, identifiers) -> bool:
    if user is None:
        return False

    normalized_allowed = {
        str(value or "").strip().lower()
        for value in (identifiers or [])
        if str(value or "").strip()
    }
    if not normalized_allowed:
        return False

    candidates = {
        str(getattr(user, "id", "") or "").strip().lower(),
        str(getattr(user, "id_number", "") or "").strip().lower(),
        str(getattr(user, "username", "") or "").strip().lower(),
        str(getattr(user, "email", "") or "").strip().lower(),
    }
    candidates.discard("")
    return bool(normalized_allowed.intersection(candidates))


def is_tenant_admin_user(user) -> bool:
    from users.tenant_access import is_global_superadmin

    if user is None:
        return False

    role = str(getattr(user, "role", "") or "").lower()
    return (
        is_global_superadmin(user)
        or bool(getattr(user, "is_superuser", False))
        or role in {"admin", "superadmin"}
    )


def is_access_override_allowed(tenant, user, frontend_path: str) -> bool:
    if user is None or tenant is None:
        return False

    allowed_paths = getattr(tenant, "disabled_access_allowed_paths", []) or []
    if not is_path_allowed_by_prefix(frontend_path, allowed_paths):
        return False

    allow_tenant_admins = bool(getattr(tenant, "disabled_access_allow_tenant_admins", True))
    allowed_users = getattr(tenant, "disabled_access_allowed_users", []) or []
    selected_user_allowed = is_user_in_override_list(user, allowed_users)
    return (allow_tenant_admins and is_tenant_admin_user(user)) or selected_user_allowed


def derive_access_restriction(tenant) -> str:
    if tenant is None:
        return RESTRICTION_NONE

    if not _tenant_active(tenant):
        return RESTRICTION_WORKSPACE_DISABLED

    login_policy = str(getattr(tenant, "login_access_policy", "all_users") or "all_users")
    if login_policy == "disabled":
        return RESTRICTION_SIGN_IN_DISABLED
    if login_policy == "tenant_admin_only":
        return RESTRICTION_ADMIN_LOGIN_ONLY

    if bool(getattr(tenant, "maintenance_mode", False)):
        return RESTRICTION_MAINTENANCE

    status = str(getattr(tenant, "status", "active") or "active").lower()
    if status == "deleted":
        return RESTRICTION_WORKSPACE_DISABLED
    if status == "on_hold":
        return RESTRICTION_STATUS_ON_HOLD
    if status == "closed":
        return RESTRICTION_STATUS_CLOSED
    if status == "inactive":
        return RESTRICTION_STATUS_INACTIVE

    return RESTRICTION_NONE


def restriction_to_fields(restriction: str) -> dict:
    base = {
        "active": True,
        "status": "active",
        "maintenance_mode": False,
        "login_access_policy": "all_users",
    }

    if restriction == RESTRICTION_NONE:
        return base
    if restriction == RESTRICTION_WORKSPACE_DISABLED:
        return {**base, "active": False}
    if restriction == RESTRICTION_SIGN_IN_DISABLED:
        return {**base, "login_access_policy": "disabled"}
    if restriction == RESTRICTION_ADMIN_LOGIN_ONLY:
        return {**base, "login_access_policy": "tenant_admin_only"}
    if restriction == RESTRICTION_MAINTENANCE:
        return {**base, "maintenance_mode": True}
    if restriction in STATUS_BY_RESTRICTION:
        return {**base, "status": STATUS_BY_RESTRICTION[restriction]}

    raise ValidationError({"access_restriction": f"Unknown restriction '{restriction}'."})


def _active_restrictions_from_values(
    *,
    active: bool | None,
    status: str | None,
    maintenance_mode: bool | None,
    login_access_policy: str | None,
) -> list[str]:
    active_restrictions: list[str] = []

    if active is False:
        active_restrictions.append(RESTRICTION_WORKSPACE_DISABLED)

    policy = str(login_access_policy or "all_users")
    if policy == "disabled":
        active_restrictions.append(RESTRICTION_SIGN_IN_DISABLED)
    elif policy == "tenant_admin_only":
        active_restrictions.append(RESTRICTION_ADMIN_LOGIN_ONLY)

    if maintenance_mode is True:
        active_restrictions.append(RESTRICTION_MAINTENANCE)

    normalized_status = str(status or "active").lower()
    if normalized_status == "on_hold":
        active_restrictions.append(RESTRICTION_STATUS_ON_HOLD)
    elif normalized_status == "closed":
        active_restrictions.append(RESTRICTION_STATUS_CLOSED)
    elif normalized_status == "inactive":
        active_restrictions.append(RESTRICTION_STATUS_INACTIVE)

    return active_restrictions


def validate_single_access_restriction(
    *,
    active: bool | None = None,
    status: str | None = None,
    maintenance_mode: bool | None = None,
    login_access_policy: str | None = None,
) -> None:
    active_restrictions = _active_restrictions_from_values(
        active=active,
        status=status,
        maintenance_mode=maintenance_mode,
        login_access_policy=login_access_policy,
    )
    if len(active_restrictions) > 1:
        labels = ", ".join(active_restrictions)
        raise ValidationError(
            {
                "access_restriction": (
                    "Only one workspace access restriction may be active at a time. "
                    f"Conflicting restrictions: {labels}."
                )
            }
        )


def normalize_access_control_patch(instance, data: dict) -> dict:
    """Coerce mutually exclusive access controls to a single restriction."""
    control_keys = {
        "active",
        "status",
        "maintenance_mode",
        "login_access_policy",
    }
    if not control_keys.intersection(data.keys()):
        return data

    merged = {
        "active": data.get("active", getattr(instance, "active", True)),
        "status": data.get("status", getattr(instance, "status", "active")),
        "maintenance_mode": data.get(
            "maintenance_mode", getattr(instance, "maintenance_mode", False)
        ),
        "login_access_policy": data.get(
            "login_access_policy", getattr(instance, "login_access_policy", "all_users")
        ),
    }

    validate_single_access_restriction(**merged)

    restriction = derive_access_restriction(type("TenantSnapshot", (), merged)())
    normalized = restriction_to_fields(restriction)

    patched = dict(data)
    for key, value in normalized.items():
        patched[key] = value
    return patched


def restriction_detail(restriction: str, tenant=None) -> str:
    messages = {
        RESTRICTION_WORKSPACE_DISABLED: (
            "This workspace is disabled. Tenant operations are currently blocked."
        ),
        RESTRICTION_SIGN_IN_DISABLED: (
            "Login is currently disabled for this workspace."
        ),
        RESTRICTION_ADMIN_LOGIN_ONLY: (
            "Only tenant administrators can access this workspace right now."
        ),
        RESTRICTION_MAINTENANCE: (
            "This workspace is currently in maintenance mode. Tenant operations are temporarily paused."
        ),
        RESTRICTION_STATUS_ON_HOLD: "This workspace is currently on hold. Tenant operations are blocked.",
        RESTRICTION_STATUS_CLOSED: "This workspace is currently closed. Tenant operations are blocked.",
        RESTRICTION_STATUS_INACTIVE: "This workspace is currently inactive. Tenant operations are blocked.",
    }
    if tenant is not None and restriction in {
        RESTRICTION_STATUS_ON_HOLD,
        RESTRICTION_STATUS_CLOSED,
        RESTRICTION_STATUS_INACTIVE,
    }:
        status = getattr(tenant, "status", restriction)
        return f"This workspace is currently {status}. Tenant operations are blocked."
    return messages.get(restriction, "Workspace access is restricted.")


def _blocked_decision(
    restriction: str,
    tenant=None,
    *,
    status_code: int = 423,
) -> TenantAccessDecision:
    return TenantAccessDecision(
        allowed=False,
        error_code=RESTRICTION_ERROR_CODES.get(restriction, "TENANT_ACCESS_DENIED"),
        detail=restriction_detail(restriction, tenant),
        status_code=status_code,
        restriction=restriction,
    )


def evaluate_tenant_api_access(
    tenant,
    user,
    *,
    frontend_path: str = "",
) -> TenantAccessDecision:
    """Central access shield for tenant-scoped API/data requests."""
    if tenant is None:
        return TenantAccessDecision(allowed=True)

    deletion_status = str(getattr(tenant, "deletion_status", "none") or "none").lower()
    if deletion_status in ("queued", "running"):
        return TenantAccessDecision(
            allowed=False,
            error_code="TENANT_DELETING",
            detail="This workspace is being deleted. Access is temporarily unavailable.",
            status_code=410,
            restriction=RESTRICTION_WORKSPACE_DISABLED,
        )

    status = str(getattr(tenant, "status", "active") or "active").lower()
    if status == "deleted":
        return TenantAccessDecision(
            allowed=False,
            error_code="TENANT_DELETED",
            detail="This workspace has been deleted. Tenant operations are no longer available.",
            status_code=410,
            restriction=RESTRICTION_WORKSPACE_DISABLED,
        )

    restriction = derive_access_restriction(tenant)
    if restriction == RESTRICTION_NONE:
        return TenantAccessDecision(allowed=True)

    if user is not None and is_global_superadmin(user):
        return TenantAccessDecision(allowed=True)

    if restriction not in SIGN_IN_RESTRICTIONS and is_access_override_allowed(
        tenant, user, frontend_path
    ):
        return TenantAccessDecision(allowed=True)

    if restriction == RESTRICTION_SIGN_IN_DISABLED:
        return _blocked_decision(restriction, tenant)

    if restriction == RESTRICTION_ADMIN_LOGIN_ONLY:
        if user is None or not is_tenant_admin_user(user):
            return _blocked_decision(restriction, tenant)
        return TenantAccessDecision(allowed=True)

    if restriction == RESTRICTION_MAINTENANCE:
        if user is not None and is_tenant_admin_user(user):
            return TenantAccessDecision(allowed=True)
        return _blocked_decision(restriction, tenant)

    if user is None:
        return _blocked_decision(restriction, tenant)

    return _blocked_decision(restriction, tenant)


def is_global_superadmin(user) -> bool:
    from users.tenant_access import is_global_superadmin as _is_global_superadmin

    return bool(user is not None and _is_global_superadmin(user))