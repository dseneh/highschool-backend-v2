from __future__ import annotations

from collections.abc import Mapping

from django.core.exceptions import ValidationError
from django.db import connection, models, transaction
from django.db.models import Count, F, Prefetch
from django_tenants.utils import get_public_schema_name, schema_context

from authorization.constants import PLATFORM_SUPERADMIN_ROLE_KEY, SUPERADMIN_ROLE_KEYS
from authorization.models import AuthorizationAuditLog, Role, RolePermission, TenantMembership
from authorization.registry import get_permission_registry
from authorization.system_roles import get_system_roles
from common.status import UserAccountType
from users.tenant_access import is_global_superadmin


FIXED_ACCOUNT_TYPE_ROLES = {
    UserAccountType.STUDENT: "student",
    UserAccountType.PARENT: "parent",
}

NO_ASSIGNED_ROLE_CODE = "NO_ASSIGNED_ROLE"
NO_ASSIGNED_ROLE_DETAIL = (
    "This account has no assigned role. An administrator must assign a role "
    "before it can be used to sign in."
)


def _normalize_role_name(name: str) -> str:
    return " ".join(str(name or "").strip().split())


def _role_name_key(name: str) -> str:
    return _normalize_role_name(name).casefold()


def serialize_shared_role(role) -> dict:
    return {
        "id": str(role.id),
        "name": role.name,
        "description": role.description,
        "system_key": role.system_key,
        "is_system_role": role.role_type == "SYSTEM",
        "is_default": False,
        "role_type": role.role_type,
        "source": "shared",
        "scope": role.scope,
        "is_active": role.is_active,
        "permission_version": role.permission_version,
        "user_count": 0,
        "permissions": role.permissions,
        "created_at": role.created_at,
        "updated_at": role.updated_at,
    }


def serialize_tenant_role(role) -> dict:
    return {
        "id": str(role.id),
        "name": role.name,
        "description": role.description,
        "system_key": role.system_key,
        "is_system_role": role.is_system_role,
        "is_default": role.is_default,
        "role_type": "SYSTEM" if role.is_system_role else "CUSTOM",
        "source": "tenant",
        "scope": "TENANT",
        "is_active": role.is_active,
        "permission_version": role.permission_version,
        "user_count": getattr(role, "user_count", 0),
        "permissions": [
            {"code": grant.permission_code, "scope": grant.scope}
            for grant in role.permission_grants.all()
        ],
        "created_at": role.created_at,
        "updated_at": role.updated_at,
    }


def get_unified_role_payloads(*, schema_name: str | None = None) -> list[dict]:
    """Return the role catalog for the active workspace without cross-tenant leakage."""
    from core.models import SharedRole

    schema = schema_name or connection.schema_name
    public_schema = get_public_schema_name()
    if schema == public_schema:
        with schema_context(public_schema):
            shared_roles = list(
                SharedRole.objects.filter(
                    scope__in=["PUBLIC", "GLOBAL"],
                    is_active=True,
                ).order_by("name")
            )
        return _dedupe_role_payloads(serialize_shared_role(role) for role in shared_roles)

    with schema_context(public_schema):
        shared_roles = list(
            SharedRole.objects.filter(
                scope__in=["TENANT", "GLOBAL"],
                is_active=True,
            ).order_by("name")
        )
    shared_name_keys = {_role_name_key(role.name) for role in shared_roles}
    tenant_roles = list(
        Role.objects.filter(is_system_role=False, system_key__isnull=True)
        .annotate(user_count=Count("memberships"))
        .prefetch_related(
            Prefetch(
                "permission_grants",
                queryset=RolePermission.objects.order_by("permission_code"),
            )
        )
        .order_by("name")
    )
    tenant_roles = [
        role for role in tenant_roles if _role_name_key(role.name) not in shared_name_keys
    ]
    return _dedupe_role_payloads(
        [serialize_shared_role(role) for role in shared_roles]
        + [serialize_tenant_role(role) for role in tenant_roles]
    )


def _dedupe_role_payloads(payloads) -> list[dict]:
    seen_identity: set[tuple[str, str]] = set()
    seen_names: set[str] = set()
    results: list[dict] = []
    for payload in payloads:
        source = str(payload.get("source") or "")
        role_id = str(payload.get("id") or "")
        identity = (source, role_id)
        name_key = _role_name_key(str(payload.get("name") or ""))
        if identity in seen_identity or name_key in seen_names:
            continue
        seen_identity.add(identity)
        seen_names.add(name_key)
        results.append(payload)
    return results


def _shared_role_name_exists(name: str) -> bool:
    from core.models import SharedRole

    name_key = _role_name_key(name)
    with schema_context(get_public_schema_name()):
        return any(
            _role_name_key(candidate) == name_key
            for candidate in SharedRole.objects.values_list("name", flat=True)
        )


def _validate_tenant_role_name_available(name: str, *, exclude_role_id=None) -> None:
    name_key = _role_name_key(name)
    if not name_key:
        raise ValidationError("Role name is required.")
    local_names = Role.objects.all()
    if exclude_role_id:
        local_names = local_names.exclude(pk=exclude_role_id)
    if any(
        _role_name_key(candidate) == name_key
        for candidate in local_names.values_list("name", flat=True)
    ):
        raise ValidationError("A role with this name already exists in this tenant.")
    if _shared_role_name_exists(name):
        raise ValidationError("A shared/system role with this name already exists.")


def get_applicable_shared_role(identifier, *, scopes=("TENANT", "GLOBAL")):
    from core.models import SharedRole

    lookup = str(identifier or "").strip()
    if not lookup:
        raise ValidationError("A role is required.")
    with schema_context(get_public_schema_name()):
        role = SharedRole.objects.filter(system_key=lookup, is_active=True, scope__in=scopes).first()
        if role is None:
            try:
                role = SharedRole.objects.get(pk=lookup, is_active=True, scope__in=scopes)
            except (SharedRole.DoesNotExist, ValueError, ValidationError):
                role = None
        if role is None:
            raise ValidationError("Role not found.")
        return role


def _shared_role_ids_for_system_keys(system_keys) -> set:
    from core.models import SharedRole

    keys = {str(key or "").strip().lower() for key in system_keys if str(key or "").strip()}
    if not keys:
        return set()
    with schema_context(get_public_schema_name()):
        return set(
            SharedRole.objects.filter(system_key__in=keys).values_list("pk", flat=True)
        )


def _membership_system_key(membership) -> str | None:
    if not membership:
        return None
    if membership.role_id:
        return membership.role.system_key
    if membership.shared_role_id:
        from core.models import SharedRole

        with schema_context(get_public_schema_name()):
            return SharedRole.objects.filter(pk=membership.shared_role_id).values_list("system_key", flat=True).first()
    return None


def _active_admin_membership_count() -> int:
    admin_shared_role_ids = _shared_role_ids_for_system_keys({"admin"})
    return TenantMembership.objects.filter(is_active=True).filter(
        models.Q(role__system_key="admin") | models.Q(shared_role_id__in=admin_shared_role_ids)
    ).count()


def get_assigned_role(user) -> Role | None:
    """Return the role explicitly assigned to the user in the current schema.

    Returns ``None`` when no usable assignment exists. There is deliberately no
    fallback role: an unassigned account has no role at all.
    """
    from authorization.models import TenantMembership

    user_id = getattr(user, "pk", None)
    if not user_id:
        return None
    membership = (
        TenantMembership.objects.select_related("role")
        .filter(user_id=user_id, is_active=True, role__is_active=True)
        .first()
    )
    if membership:
        return membership.role
    shared_membership = (
        TenantMembership.objects.filter(user_id=user_id, is_active=True, shared_role_id__isnull=False)
        .first()
    )
    if not shared_membership:
        return None
    try:
        return get_applicable_shared_role(shared_membership.shared_role_id)
    except ValidationError:
        return None


def has_assigned_role(user) -> bool:
    """Whether the account holds an explicit role grant it can sign in with.

    Platform superadmins are granted platform-wide authority by an explicit
    account flag rather than a tenant role, which is why they resolve here
    without a membership.
    """
    from django_tenants.utils import get_public_schema_name, schema_context

    if not getattr(user, "pk", None):
        return False
    if is_global_superadmin(user):
        return True

    public_schema = get_public_schema_name()
    if connection.schema_name != public_schema:
        return get_assigned_role(user) is not None

    # Central sign-in resolves no single workspace, so require a role in at
    # least one workspace the account belongs to.
    workspaces = (
        user.tenants.filter(active=True)
        .exclude(schema_name=public_schema)
        .values_list("schema_name", flat=True)
    )
    for schema_name in workspaces:
        try:
            with schema_context(schema_name):
                if get_assigned_role(user) is not None:
                    return True
        except Exception:
            continue
    return False


def validate_role_for_account_type(*, user, role: Role) -> None:
    account_type = str(getattr(user, "account_type", "") or "").strip().lower()
    required_role = FIXED_ACCOUNT_TYPE_ROLES.get(account_type)
    if required_role and role.system_key != required_role:
        raise ValidationError(
            f"{account_type.capitalize()} accounts must use the {required_role} role."
        )


def validate_role_grants(grants: Mapping[str, str]) -> None:
    registry = get_permission_registry()
    for permission_code, scope in grants.items():
        permission = registry.require(permission_code)
        if not permission.assignable:
            raise ValidationError(
                f"Permission {permission_code} cannot be assigned to tenant roles."
            )
        if scope not in permission.scopes:
            raise ValidationError(
                f"Scope {scope!r} is not allowed for {permission_code}."
            )
        missing_dependencies = set(permission.requires) - grants.keys()
        if missing_dependencies:
            raise ValidationError(
                f"Permission {permission_code} requires: "
                f"{', '.join(sorted(missing_dependencies))}."
            )


def validate_permission_delegation(actor, grants: Mapping[str, str]) -> None:
    if actor is None:
        return
    if is_global_superadmin(actor):
        return
    from authorization.models import TenantMembership

    membership = TenantMembership.objects.select_related("role").filter(
        user=actor,
        is_active=True,
        role__is_active=True,
    ).first()
    if membership is None:
        raise ValidationError("The actor has no active tenant role.")
    actor_grants = dict(
        RolePermission.objects.filter(role=membership.role).values_list(
            "permission_code", "scope"
        )
    )
    prohibited = set(grants) - actor_grants.keys()
    if prohibited:
        raise ValidationError(
            "You cannot grant permissions outside your own role: "
            f"{', '.join(sorted(prohibited))}."
        )
    broader_scopes = [
        code
        for code, scope in grants.items()
        if actor_grants[code] != "all" and actor_grants[code] != scope
    ]
    if broader_scopes:
        raise ValidationError(
            "You cannot delegate a different scope than your own for: "
            f"{', '.join(sorted(broader_scopes))}."
        )


def _audit_metadata(metadata: Mapping | None) -> dict:
    metadata = metadata or {}
    return {
        "ip_address": metadata.get("ip_address") or None,
        "user_agent": metadata.get("user_agent") or "",
    }


@transaction.atomic
def create_role(*, name: str, description: str = "", actor=None, metadata=None) -> Role:
    name = _normalize_role_name(name)
    _validate_tenant_role_name_available(name)
    role = Role.objects.create(
        name=name,
        description=description.strip(),
        created_by=actor,
    )
    AuthorizationAuditLog.objects.create(
        actor=actor,
        action="role.created",
        target_type="role",
        target_id=str(role.pk),
        after={"name": role.name, "description": role.description},
        **_audit_metadata(metadata),
    )
    return role


@transaction.atomic
def update_role(*, role: Role, changes: Mapping, actor=None, metadata=None) -> Role:
    locked_role = Role.objects.select_for_update().get(pk=role.pk)
    if locked_role.is_system_role:
        raise ValidationError("System roles cannot be modified.")
    name = _normalize_role_name(str(changes.get("name", locked_role.name)))
    _validate_tenant_role_name_available(name, exclude_role_id=locked_role.pk)
    before = {
        "name": locked_role.name,
        "description": locked_role.description,
        "is_active": locked_role.is_active,
    }
    for field in ("name", "description", "is_active"):
        if field in changes:
            setattr(locked_role, field, changes[field])
    locked_role.save()
    AuthorizationAuditLog.objects.create(
        actor=actor,
        action="role.updated",
        target_type="role",
        target_id=str(locked_role.pk),
        before=before,
        after={
            "name": locked_role.name,
            "description": locked_role.description,
            "is_active": locked_role.is_active,
        },
        **_audit_metadata(metadata),
    )
    return locked_role


@transaction.atomic
def delete_role(*, role: Role, actor=None, metadata=None) -> None:
    locked_role = Role.objects.select_for_update().get(pk=role.pk)
    if locked_role.is_system_role:
        raise ValidationError("System roles cannot be deleted.")
    if locked_role.memberships.exists():
        raise ValidationError("Reassign users before deleting this role.")
    before = {"name": locked_role.name, "description": locked_role.description}
    role_id = str(locked_role.pk)
    locked_role.delete()
    AuthorizationAuditLog.objects.create(
        actor=actor,
        action="role.deleted",
        target_type="role",
        target_id=role_id,
        before=before,
        **_audit_metadata(metadata),
    )


@transaction.atomic
def clone_role(
    *,
    source: Role,
    name: str,
    description: str | None = None,
    actor=None,
    metadata=None,
) -> Role:
    source = Role.objects.prefetch_related("permission_grants").get(pk=source.pk)
    cloned = create_role(
        name=name,
        description=source.description if description is None else description,
        actor=actor,
        metadata=metadata,
    )
    grants = {
        grant.permission_code: grant.scope for grant in source.permission_grants.all()
    }
    if grants:
        cloned = replace_role_permissions(
            cloned,
            grants,
            actor=actor,
            metadata=metadata,
        )
    AuthorizationAuditLog.objects.create(
        actor=actor,
        action="role.cloned",
        target_type="role",
        target_id=str(cloned.pk),
        after={"source_role_id": str(source.pk), "name": cloned.name},
        **_audit_metadata(metadata),
    )
    return cloned


@transaction.atomic
def replace_role_permissions(
    role: Role,
    grants: Mapping[str, str],
    *,
    actor=None,
    metadata=None,
) -> Role:
    validate_role_grants(grants)
    validate_permission_delegation(actor, grants)
    locked_role = Role.objects.select_for_update().get(pk=role.pk)
    if locked_role.is_system_role:
        raise ValidationError(
            "System role permissions are application-owned and cannot be modified."
        )

    current_grants = dict(
        RolePermission.objects.filter(role=locked_role).values_list(
            "permission_code", "scope"
        )
    )
    desired_grants = dict(grants)
    if current_grants == desired_grants:
        return locked_role

    RolePermission.objects.filter(role=locked_role).application_delete()
    RolePermission.objects.application_bulk_create(
        [
            RolePermission(
                role=locked_role,
                permission_code=permission_code,
                scope=scope,
                granted_by=actor,
            )
            for permission_code, scope in desired_grants.items()
        ]
    )
    Role.objects.filter(pk=locked_role.pk).application_update(
        permission_version=F("permission_version") + 1
    )
    AuthorizationAuditLog.objects.create(
        actor=actor,
        action="role.permissions_replaced",
        target_type="role",
        target_id=str(locked_role.pk),
        before=current_grants,
        after=desired_grants,
        **_audit_metadata(metadata),
    )
    from authorization.cache import schedule_role_invalidation

    schedule_role_invalidation(connection.schema_name, locked_role.pk)
    locked_role.refresh_from_db(fields=("permission_version",))
    return locked_role


def resolve_assignable_role(identifier, *, account_type=None) -> Role:
    """Resolve a role from a system key or id, refusing reserved roles.

    Student and parent accounts have a fixed role, so their identifier is
    derived from the account type rather than supplied by the caller.
    """
    fixed_key = FIXED_ACCOUNT_TYPE_ROLES.get(
        str(getattr(account_type, "value", account_type) or "").strip().lower()
    )
    if fixed_key:
        return Role.objects.get(system_key=fixed_key)

    lookup = str(identifier or "").strip()
    if not lookup:
        raise ValidationError("A role is required.")
    if lookup.lower() in SUPERADMIN_ROLE_KEYS:
        raise ValidationError(
            "The superadmin role is reserved for platform superusers and cannot be assigned."
        )

    role = Role.objects.filter(system_key=lookup, is_active=True).first()
    if role is None:
        try:
            role = Role.objects.filter(pk=lookup, is_active=True).first()
        except (ValueError, ValidationError):
            role = None
    if role is None:
        raise ValidationError(f"Unknown or inactive role: {lookup}")
    if role.system_key in SUPERADMIN_ROLE_KEYS:
        raise ValidationError(
            "The superadmin role is reserved for platform superusers and cannot be assigned."
        )
    return role


@transaction.atomic
def assign_user_role(*, user, role: Role, actor=None, metadata=None):
    if not role.is_active:
        raise ValidationError("Inactive roles cannot be assigned.")
    if role.system_key in SUPERADMIN_ROLE_KEYS:
        raise ValidationError(
            "The superadmin role is reserved for platform superusers and cannot be assigned."
        )
    validate_role_for_account_type(user=user, role=role)
    membership = (
        TenantMembership.objects.select_for_update().filter(user=user).first()
    )
    if membership and actor and membership.user_id == actor.pk and membership.role_id != role.pk:
        raise ValidationError("You cannot change your own role.")
    if (
        membership
        and _membership_system_key(membership) == "admin"
        and role.system_key != "admin"
        and _active_admin_membership_count() <= 1
    ):
        raise ValidationError("The tenant must retain at least one administrator.")
    before = (
        {
            "role_id": str(membership.role_id) if membership.role_id else None,
            "shared_role_id": str(membership.shared_role_id) if membership.shared_role_id else None,
            "active": membership.is_active,
        }
        if membership
        else None
    )
    if membership is None:
        membership = TenantMembership(user=user, role=role, is_active=True)
    else:
        membership.role = role
        membership.shared_role_id = None
        membership.is_active = True
    membership.save()
    AuthorizationAuditLog.objects.create(
        actor=actor,
        action="membership.role_changed",
        target_type="membership",
        target_id=str(membership.pk),
        before=before,
        after={"user_id": str(user.pk), "role_id": str(role.pk), "shared_role_id": None, "active": True},
        **_audit_metadata(metadata),
    )
    return membership


@transaction.atomic
def assign_user_shared_role(*, user, role, actor=None, metadata=None):
    if not role.is_active:
        raise ValidationError("Inactive roles cannot be assigned.")
    if role.scope not in {"TENANT", "GLOBAL"}:
        raise ValidationError("This shared role is not available in tenant workspaces.")
    validate_role_for_account_type(user=user, role=role)
    membership = TenantMembership.objects.select_for_update().filter(user=user).first()
    if membership and actor and membership.user_id == actor.pk and membership.shared_role_id != role.pk:
        raise ValidationError("You cannot change your own role.")
    if (
        membership
        and _membership_system_key(membership) == "admin"
        and role.system_key != "admin"
        and _active_admin_membership_count() <= 1
    ):
        raise ValidationError("The tenant must retain at least one administrator.")
    before = (
        {
            "role_id": str(membership.role_id) if membership.role_id else None,
            "shared_role_id": str(membership.shared_role_id) if membership.shared_role_id else None,
            "active": membership.is_active,
        }
        if membership
        else None
    )
    if membership is None:
        membership = TenantMembership(user=user, shared_role_id=role.pk, is_active=True)
    else:
        membership.role = None
        membership.shared_role_id = role.pk
        membership.is_active = True
    membership.save()
    AuthorizationAuditLog.objects.create(
        actor=actor,
        action="membership.role_changed",
        target_type="membership",
        target_id=str(membership.pk),
        before=before,
        after={"user_id": str(user.pk), "role_id": None, "shared_role_id": str(role.pk), "active": True},
        **_audit_metadata(metadata),
    )
    return membership


def ensure_tenant_owner_membership(owner) -> None:
    if not owner:
        return
    from authorization.models import TenantMembership

    admin_role = Role.objects.get(system_key="admin")
    membership, created = TenantMembership.objects.get_or_create(
        user=owner,
        defaults={"role": admin_role, "is_active": True},
    )
    if created:
        return
    # The owner is often granted tenant permissions first, which seeds the
    # default viewer role. Only that auto-assigned role may be upgraded.
    if not membership.role_id or membership.role.system_key == "viewer" or not membership.is_active:
        membership.role = admin_role
        membership.shared_role_id = None
        membership.is_active = True
        membership.save(update_fields=("role", "shared_role_id", "is_active"))


def ensure_tenant_user_membership(user) -> None:
    """Seed the RBAC membership a user is entitled to when joining a tenant.

    Platform superusers get the unrestricted superadmin role, which mirrors the
    platform grant they already hold. Everyone else must be assigned a role
    explicitly by an administrator — there is no default role.
    """
    if not user:
        return
    from authorization.models import TenantMembership

    if not is_global_superadmin(user):
        return

    role = Role.objects.get(system_key=PLATFORM_SUPERADMIN_ROLE_KEY)
    membership, created = TenantMembership.objects.get_or_create(
        user=user,
        defaults={"role": role, "is_active": True},
    )
    if created or (membership.role_id == role.pk and not membership.shared_role_id):
        return
    membership.role = role
    membership.shared_role_id = None
    membership.is_active = True
    membership.save(update_fields=("role", "shared_role_id", "is_active"))


@transaction.atomic
def sync_system_roles() -> None:
    from authorization.cache import schedule_role_invalidation
    from core.models import SharedRole

    if connection.schema_name == "public":
        public_scopes = {
            "superadmin": "PUBLIC",
            "admin": "GLOBAL",
            "viewer": "GLOBAL",
        }
        for role_spec in get_system_roles():
            SharedRole.objects.update_or_create(
                system_key=role_spec.key,
                defaults={
                    "role_type": "SYSTEM",
                    "scope": public_scopes.get(role_spec.key, "TENANT"),
                    "name": role_spec.name,
                    "description": role_spec.description,
                    "permissions": [
                        {"code": grant.permission, "scope": grant.scope}
                        for grant in role_spec.grants
                    ],
                    "is_active": True,
                },
            )
        return

    for role_spec in get_system_roles():
        role = Role.objects.filter(system_key=role_spec.key).first()
        if role is None:
            conflicting_role = Role.objects.filter(name__iexact=role_spec.name).first()
            if conflicting_role is not None:
                raise ValidationError(
                    f"Custom role {conflicting_role.name!r} conflicts with system role {role_spec.name!r}."
                )
            role = Role(
                name=role_spec.name,
                description=role_spec.description,
                system_key=role_spec.key,
                is_system_role=True,
            )
            role._application_owned = True
            role.save(force_insert=True)
        else:
            Role.objects.filter(pk=role.pk).application_update(
                name=role_spec.name,
                description=role_spec.description,
                is_system_role=True,
                is_active=True,
            )
        schedule_role_invalidation(connection.schema_name, role.pk)

        desired_grants = {grant.permission: grant.scope for grant in role_spec.grants}
        current_grants = dict(RolePermission.objects.filter(role=role).values_list("permission_code", "scope"))
        if current_grants == desired_grants:
            continue
        RolePermission.objects.filter(role=role).application_delete()
        RolePermission.objects.application_bulk_create(
            [RolePermission(role=role, permission_code=code, scope=scope) for code, scope in desired_grants.items()]
        )
        Role.objects.filter(pk=role.pk).application_update(
            permission_version=F("permission_version") + 1
        )
