from __future__ import annotations

import logging
from dataclasses import dataclass, field

from django.db import connection, transaction
from django_tenants.utils import get_public_schema_name, schema_context
from rest_framework.exceptions import PermissionDenied

from authorization.cache import (
    AuthorizationCache,
    CachedAuthorizationBundle,
    CachedMembership,
    CachedRolePermissions,
    CachedRolePointer,
)
from authorization.models import RolePermission, TenantMembership
from authorization.constants import SUPERADMIN_ROLE_KEYS
from authorization.registry import get_permission_registry
from users.tenant_access import is_global_superadmin


logger = logging.getLogger(__name__)


def _has_outer_transaction() -> bool:
    return connection.in_atomic_block


@dataclass(frozen=True)
class AuthorizationContext:
    schema_name: str
    user_id: str
    membership_id: str = ""
    membership_version: int = 0
    role_id: str = ""
    permission_version: int = 0
    permissions: dict[str, str] = field(default_factory=dict)
    active: bool = False
    unrestricted: bool = False
    cache_hit: bool = False

    def permission_scope(self, permission_code: str) -> str | None:
        if not self.active or get_permission_registry().get(permission_code) is None:
            return None
        if self.unrestricted:
            return "all"
        return self.permissions.get(permission_code)

    def can(self, permission_code: str) -> bool:
        return self.permission_scope(permission_code) is not None


def _denied_context(schema_name: str, user_id) -> AuthorizationContext:
    return AuthorizationContext(schema_name=schema_name, user_id=str(user_id or ""))


def _context_from_bundle(
    schema_name: str,
    user_id,
    bundle: CachedAuthorizationBundle,
) -> AuthorizationContext:
    membership = bundle.membership
    role = bundle.role
    role_permissions = bundle.role_permissions
    active = bool(
        membership.exists
        and membership.active
        and role is not None
        and role.active
        and role_permissions is not None
    )
    return AuthorizationContext(
        schema_name=schema_name,
        user_id=str(user_id),
        membership_id=membership.membership_id,
        membership_version=membership.membership_version,
        role_id=membership.role_id,
        permission_version=role.permission_version if role else 0,
        permissions=role_permissions.permissions if active else {},
        active=active,
        unrestricted=bool(active and role.system_key in SUPERADMIN_ROLE_KEYS),
        cache_hit=True,
    )


def resolve_authorization_context(user, *, schema_name: str | None = None):
    schema_name = schema_name or getattr(connection, "schema_name", "")
    user_id = getattr(user, "pk", None)
    if (
        not schema_name
        or schema_name == get_public_schema_name()
        or not user_id
        or not getattr(user, "is_authenticated", False)
        or not getattr(user, "is_active", False)
    ):
        return _denied_context(schema_name, user_id)

    # Platform superadmins are intentionally not assigned tenant role grants.
    # They have unrestricted access in every tenant workspace.
    if is_global_superadmin(user):
        return AuthorizationContext(
            schema_name=schema_name,
            user_id=str(user_id),
            active=True,
            unrestricted=True,
        )

    try:
        cached_bundle = AuthorizationCache.get_bundle(schema_name, user_id)
        if cached_bundle is not None:
            return _context_from_bundle(schema_name, user_id, cached_bundle)

        has_outer_transaction = _has_outer_transaction()
        # Lock the membership and role until the cache snapshot is written. A
        # concurrent revocation then commits after this transaction and deletes
        # the snapshot, preventing stale access from being resurrected.
        with transaction.atomic(savepoint=False):
            membership = (
                TenantMembership.objects.select_for_update()
                .filter(user_id=user_id)
                .first()
            )
            if membership is None:
                return _denied_context(schema_name, user_id)

            if membership.shared_role_id:
                from core.models import SharedRole

                with schema_context(get_public_schema_name()):
                    shared_role = SharedRole.objects.filter(
                        pk=membership.shared_role_id,
                        is_active=True,
                        scope__in=["TENANT", "GLOBAL"],
                    ).first()
                if shared_role is None or not membership.is_active:
                    return AuthorizationContext(
                        schema_name=schema_name,
                        user_id=str(user_id),
                        membership_id=str(membership.pk),
                        membership_version=membership.membership_version,
                        role_id=str(membership.shared_role_id),
                    )
                registry = get_permission_registry()
                permissions = {
                    grant.get("code"): grant.get("scope")
                    for grant in shared_role.permissions
                    if registry.get(grant.get("code")) is not None
                }
                return AuthorizationContext(
                    schema_name=schema_name,
                    user_id=str(user_id),
                    membership_id=str(membership.pk),
                    membership_version=membership.membership_version,
                    role_id=str(shared_role.pk),
                    permission_version=shared_role.permission_version,
                    permissions=permissions,
                    active=True,
                    unrestricted=False,
                )

            cached_membership = CachedMembership(
                exists=True,
                membership_id=str(membership.pk),
                membership_version=membership.membership_version,
                role_id=str(membership.role_id),
                active=membership.is_active,
            )
            role = membership.role
            cached_role = CachedRolePointer(
                role_id=str(role.pk),
                permission_version=role.permission_version,
                active=role.is_active,
                system_key=(role.system_key or "").strip().lower(),
            )

            if not membership.is_active or not role.is_active:
                if not has_outer_transaction:
                    AuthorizationCache.set_authorization(
                        schema_name,
                        user_id,
                        cached_membership,
                        cached_role,
                    )
                return AuthorizationContext(
                    schema_name=schema_name,
                    user_id=str(user_id),
                    membership_id=str(membership.pk),
                    membership_version=membership.membership_version,
                    role_id=str(role.pk),
                )

            registry = get_permission_registry()
            permissions = {
                code: scope
                for code, scope in RolePermission.objects.filter(role=role).values_list(
                    "permission_code", "scope"
                )
                if registry.get(code) is not None
            }
            cached_permissions = CachedRolePermissions(
                role_id=str(role.pk),
                permission_version=role.permission_version,
                permissions=permissions,
            )
            if not has_outer_transaction:
                AuthorizationCache.set_authorization(
                    schema_name,
                    user_id,
                    cached_membership,
                    cached_role,
                    cached_permissions,
                )
            return AuthorizationContext(
                schema_name=schema_name,
                user_id=str(user_id),
                membership_id=str(membership.pk),
                membership_version=membership.membership_version,
                role_id=str(role.pk),
                permission_version=role.permission_version,
                permissions=permissions,
                active=True,
                unrestricted=(
                    (role.system_key or "").strip().lower()
                    in SUPERADMIN_ROLE_KEYS
                ),
            )
    except Exception:
        logger.exception(
            "Authorization resolution failed for user %s in schema %s",
            user_id,
            schema_name,
        )
        return _denied_context(schema_name, user_id)


def user_has_permission(user, permission_code: str, *, scope: str = "all") -> bool:
    """Evaluate an RBAC permission outside a DRF request lifecycle."""
    permission_scope = resolve_authorization_context(user).permission_scope(
        permission_code
    )
    return permission_scope == "all" or permission_scope == scope


class AuthorizationBindingError(RuntimeError):
    pass


class RequestAuthorization:
    def __init__(self, request, user, schema_name: str):
        self.request = request
        self.user = user
        self.user_id = str(getattr(user, "pk", ""))
        self.schema_name = schema_name
        self._context: AuthorizationContext | None = None

    @property
    def context(self) -> AuthorizationContext:
        if self._context is None:
            current_schema = getattr(connection, "schema_name", "")
            tenant_schema = getattr(
                getattr(self.request, "tenant", None),
                "schema_name",
                current_schema,
            )
            if current_schema != self.schema_name or tenant_schema != self.schema_name:
                self._context = _denied_context(self.schema_name, self.user_id)
            else:
                self._context = resolve_authorization_context(
                    self.user,
                    schema_name=self.schema_name,
                )
            self.request.membership_id = self._context.membership_id or None
            self.request.role_id = self._context.role_id or None
            self.request.permissions = self._context.permissions
        return self._context

    def can(self, permission_code: str) -> bool:
        return self.context.can(permission_code)

    def can_any(self, *permission_codes: str) -> bool:
        return any(self.can(code) for code in permission_codes)

    def permission_scope(self, permission_code: str) -> str | None:
        return self.context.permission_scope(permission_code)

    def require_permission(self, permission_code: str) -> None:
        if not self.can(permission_code):
            raise PermissionDenied("You do not have permission to perform this action.")


def initialize_request_authorization(request, user=None) -> RequestAuthorization:
    user = user or getattr(request, "user", None)
    schema_name = getattr(connection, "schema_name", "")
    user_id = str(getattr(user, "pk", ""))
    existing = getattr(request, "authorization", None)
    if existing is not None:
        if existing.user_id != user_id or existing.schema_name != schema_name:
            raise AuthorizationBindingError(
                "Authorization request context is already bound to another identity."
            )
        return existing

    facade = RequestAuthorization(request, user, schema_name)
    request.authorization = facade
    request.can = facade.can
    request.can_any = facade.can_any
    request.permission_scope = facade.permission_scope
    request.require_permission = facade.require_permission
    return facade
