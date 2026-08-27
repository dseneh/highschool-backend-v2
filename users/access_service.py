"""Centralized user identity, platform-access, and employment operations.

A User is a single public-schema identity. Platform authorization is represented
by SharedRoleAssignment, tenant authorization by TenantMembership, and
employment by domain profile records. account_scope summarizes the active
workspace categories; it never grants permission by itself.
"""

from __future__ import annotations

from collections.abc import Iterable

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django_tenants.utils import get_public_schema_name, schema_context

from common.status import UserAccountScope

MANAGE_PLATFORM_ACCESS_PERMISSION = "users.manage_platform_access"


def _permission_codes(values: Iterable) -> set[str]:
    codes: set[str] = set()
    for value in values or []:
        if isinstance(value, str):
            codes.add(value)
        elif isinstance(value, dict) and value.get("code"):
            codes.add(str(value["code"]))
    return codes


def can_manage_platform_access(actor) -> bool:
    if not actor or not getattr(actor, "is_authenticated", False):
        return False
    if getattr(actor, "is_platform_superuser", False):
        return True

    from core.models import SharedRoleAssignment

    actor_id = getattr(actor, "pk", None)
    if not actor_id:
        return False
    with schema_context(get_public_schema_name()):
        assignment = (
            SharedRoleAssignment.objects.select_related("role")
            .filter(
                user_id=actor_id,
                is_active=True,
                role__is_active=True,
                role__scope__in=["PUBLIC", "GLOBAL"],
            )
            .first()
        )
        if assignment is None:
            return False
        return MANAGE_PLATFORM_ACCESS_PERMISSION in _permission_codes(
            assignment.role.permissions
        )


def require_platform_access_manager(actor) -> None:
    if not can_manage_platform_access(actor):
        raise PermissionDenied("You are not allowed to manage platform access.")


def has_platform_role(user) -> bool:
    if not user:
        return False
    if getattr(user, "is_platform_superuser", False):
        return True

    from core.models import SharedRoleAssignment

    user_id = getattr(user, "pk", None)
    if not user_id:
        return False
    with schema_context(get_public_schema_name()):
        return SharedRoleAssignment.objects.filter(
            user_id=user_id,
            is_active=True,
            role__is_active=True,
            role__scope__in=["PUBLIC", "GLOBAL"],
        ).exists()


def has_any_tenant_role(user) -> bool:
    """Check whether user has an active RBAC role in at least one tenant."""
    if not user:
        return False

    from core.models import Tenant
    from users.models import User
    from authorization.services import get_assigned_role

    user_id = getattr(user, "pk", None)
    if not user_id:
        return False

    public_schema = get_public_schema_name()
    with schema_context(public_schema):
        try:
            db_user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return False
        tenant_schemas = list(
            db_user.tenants.filter(active=True)
            .exclude(schema_name=public_schema)
            .values_list("schema_name", flat=True)
        )
        existing_schemas = set(
            Tenant.objects.filter(schema_name__in=tenant_schemas)
            .exclude(status=Tenant.STATUS_DELETED)
            .values_list("schema_name", flat=True)
        )

    for schema_name in tenant_schemas:
        if schema_name not in existing_schemas:
            continue
        try:
            with schema_context(schema_name):
                if get_assigned_role(db_user) is not None:
                    return True
        except Exception:
            continue
    return False


def has_any_assigned_role(user) -> bool:
    """Central login guard for either platform or tenant authorization."""
    return has_platform_role(user) or has_any_tenant_role(user)


def calculate_account_scope(user) -> str:
    platform = has_platform_role(user)
    tenant = has_any_tenant_role(user)
    if platform and tenant:
        return UserAccountScope.PLATFORM_AND_TENANT.value
    if platform:
        return UserAccountScope.PLATFORM.value
    return UserAccountScope.TENANT.value


def sync_account_scope(user):
    from users.models import User

    user_id = getattr(user, "pk", None)
    if not user_id:
        raise ValidationError("A persisted user is required.")

    public_schema = get_public_schema_name()
    with schema_context(public_schema):
        db_user = User.objects.get(pk=user_id)
    desired = calculate_account_scope(db_user)
    with schema_context(public_schema):
        if db_user.account_scope != desired:
            db_user.account_scope = desired
            db_user.save(update_fields=["account_scope"])
    return db_user


def _get_platform_role(role_identifier):
    from core.models import SharedRole

    lookup = str(role_identifier or "").strip()
    if not lookup:
        raise ValidationError("A platform role is required.")

    filters = {"is_active": True, "scope__in": ["PUBLIC", "GLOBAL"]}
    role = SharedRole.objects.filter(system_key=lookup, **filters).first()
    if role is None:
        try:
            role = SharedRole.objects.get(pk=lookup, **filters)
        except (SharedRole.DoesNotExist, ValueError, ValidationError):
            role = None
    if role is None:
        raise ValidationError("The selected role cannot be used for platform access.")
    return role


@transaction.atomic
def enable_platform_access(*, user, role, actor):
    require_platform_access_manager(actor)

    from core.models import SharedRoleAssignment
    from users.models import User

    public_schema = get_public_schema_name()
    with schema_context(public_schema):
        db_user = User.objects.select_for_update().get(pk=user.pk)
        platform_role = _get_platform_role(role)
        assignment, _ = SharedRoleAssignment.objects.update_or_create(
            user=db_user,
            defaults={"role": platform_role, "is_active": True},
        )

    sync_account_scope(db_user)
    return assignment


@transaction.atomic
def disable_platform_access(*, user, actor):
    require_platform_access_manager(actor)

    from core.models import SharedRoleAssignment
    from users.models import User

    public_schema = get_public_schema_name()
    with schema_context(public_schema):
        db_user = User.objects.select_for_update().get(pk=user.pk)
        SharedRoleAssignment.objects.filter(user=db_user, is_active=True).update(is_active=False)

    sync_account_scope(db_user)
    return db_user


@transaction.atomic
def hire_platform_employee(
    *, user, actor, employee_number=None, position="", department="",
    hire_date=None, platform_role=None,
):
    require_platform_access_manager(actor)

    from users.models import PlatformEmployee, User

    public_schema = get_public_schema_name()
    with schema_context(public_schema):
        db_user = User.objects.select_for_update().get(pk=user.pk)
        employment, _ = PlatformEmployee.objects.update_or_create(
            user=db_user,
            defaults={
                "employee_number": employee_number,
                "position": position or "",
                "department": department or "",
                "hire_date": hire_date,
                "termination_date": None,
                "status": PlatformEmployee.EmploymentStatus.ACTIVE,
            },
        )

    if platform_role is not None:
        enable_platform_access(user=db_user, role=platform_role, actor=actor)
    return employment


@transaction.atomic
def terminate_platform_employee(*, user, actor, termination_date, revoke_access=False):
    require_platform_access_manager(actor)

    from users.models import PlatformEmployee

    public_schema = get_public_schema_name()
    with schema_context(public_schema):
        try:
            employment = PlatformEmployee.objects.select_for_update().get(user_id=user.pk)
        except PlatformEmployee.DoesNotExist as exc:
            raise ValidationError("This user has no platform employment record.") from exc
        employment.status = PlatformEmployee.EmploymentStatus.TERMINATED
        employment.termination_date = termination_date
        employment.save(update_fields=["status", "termination_date", "updated_at"])

    if revoke_access:
        disable_platform_access(user=user, actor=actor)
    return employment
