from __future__ import annotations

from collections.abc import Mapping

from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.db.models import F

from authorization.models import AuthorizationAuditLog, Role, RolePermission
from authorization.registry import get_permission_registry
from authorization.system_roles import get_system_roles
from users.tenant_access import is_global_superadmin


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
    if is_global_superadmin(actor) or getattr(actor, "is_superuser", False):
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
    if Role.objects.filter(name__iexact=name).exists():
        raise ValidationError("A role with this name already exists.")
    role = Role.objects.create(
        name=name.strip(),
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
    name = str(changes.get("name", locked_role.name)).strip()
    if Role.objects.filter(name__iexact=name).exclude(pk=locked_role.pk).exists():
        raise ValidationError("A role with this name already exists.")
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


@transaction.atomic
def assign_user_role(*, user, role: Role, actor=None, metadata=None):
    from authorization.models import TenantMembership

    if not role.is_active:
        raise ValidationError("Inactive roles cannot be assigned.")
    membership = (
        TenantMembership.objects.select_for_update().filter(user=user).first()
    )
    if membership and actor and membership.user_id == actor.pk and membership.role_id != role.pk:
        raise ValidationError("You cannot change your own role.")
    if (
        membership
        and membership.role.system_key == "admin"
        and role.system_key != "admin"
        and TenantMembership.objects.filter(
            role__system_key="admin", is_active=True
        ).count()
        <= 1
    ):
        raise ValidationError("The tenant must retain at least one administrator.")
    before = (
        {"role_id": str(membership.role_id), "active": membership.is_active}
        if membership
        else None
    )
    if membership is None:
        membership = TenantMembership(user=user, role=role, is_active=True)
    else:
        membership.role = role
        membership.is_active = True
    membership.save()
    AuthorizationAuditLog.objects.create(
        actor=actor,
        action="membership.role_changed",
        target_type="membership",
        target_id=str(membership.pk),
        before=before,
        after={"user_id": str(user.pk), "role_id": str(role.pk), "active": True},
        **_audit_metadata(metadata),
    )
    return membership


def ensure_tenant_owner_membership(owner) -> None:
    if not owner:
        return
    from authorization.models import TenantMembership

    admin_role = Role.objects.get(system_key="admin")
    TenantMembership.objects.get_or_create(
        user=owner,
        defaults={"role": admin_role, "is_active": True},
    )


@transaction.atomic
def sync_system_roles() -> None:
    from authorization.cache import schedule_role_invalidation

    for role_spec in get_system_roles():
        role = Role.objects.filter(system_key=role_spec.key).first()
        if role is None:
            conflicting_role = Role.objects.filter(
                name__iexact=role_spec.name
            ).first()
            if conflicting_role is not None:
                raise ValidationError(
                    f"Custom role {conflicting_role.name!r} conflicts with "
                    f"system role {role_spec.name!r}."
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

        desired_grants = {
            grant.permission: grant.scope for grant in role_spec.grants
        }
        current_grants = dict(
            RolePermission.objects.filter(role=role).values_list(
                "permission_code", "scope"
            )
        )
        if current_grants == desired_grants:
            continue

        RolePermission.objects.filter(role=role).application_delete()
        RolePermission.objects.application_bulk_create(
            [
                RolePermission(
                    role=role,
                    permission_code=permission_code,
                    scope=scope,
                )
                for permission_code, scope in desired_grants.items()
            ]
        )
        Role.objects.filter(pk=role.pk).application_update(
            permission_version=F("permission_version") + 1
        )
