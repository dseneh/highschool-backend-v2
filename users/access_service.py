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

MANAGE_PLATFORM_ACCESS_PERMISSION = "platform.users.manage_access"


def _permission_codes(values: Iterable) -> set[str]:
    codes: set[str] = set()
    for value in values or []:
        if isinstance(value, str):
            codes.add(value)
        elif isinstance(value, dict) and value.get("code"):
            codes.add(str(value["code"]))
    return codes


def _audit_platform_event(*, event_type: str, target_user, actor=None, before=None, after=None):
    """Write security-sensitive platform mutations to the shared auth audit log."""
    from users.sso_models import AuthenticationAuditEvent

    actor_id = str(getattr(actor, "pk", "") or "")
    actor_identifier = (
        getattr(actor, "id_number", None)
        or getattr(actor, "email", None)
        or getattr(actor, "username", None)
    )
    AuthenticationAuditEvent.objects.create(
        event_type=event_type,
        user=target_user,
        metadata={
            "actor_id": actor_id or None,
            "actor": actor_identifier,
            "before": before or {},
            "after": after or {},
        },
    )


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


def discover_linked_profile_types(user) -> list[str]:
    """Discover historical/current domain personas across tenant schemas for detail views."""
    from core.models import Tenant
    from users.models import PlatformEmployee

    user_id = getattr(user, "pk", None)
    id_number = str(getattr(user, "id_number", "") or "").strip()
    email = str(getattr(user, "email", "") or "").strip()
    if not user_id:
        return []

    profiles: set[str] = set()
    public_schema = get_public_schema_name()
    with schema_context(public_schema):
        if PlatformEmployee.objects.filter(user_id=user_id).exists():
            profiles.add("platform_employee")
        schemas = list(
            Tenant.objects.exclude(schema_name=public_schema)
            .exclude(status=Tenant.STATUS_DELETED)
            .values_list("schema_name", flat=True)
        )

    for schema_name in schemas:
        try:
            with schema_context(schema_name):
                try:
                    from staff.models import Staff
                    if id_number and Staff.objects.filter(user_account_id_number=id_number).exists():
                        profiles.add("staff")
                except Exception:
                    pass

                try:
                    from hr.models import Employee
                    if id_number and Employee.objects.filter(user_account_id_number=id_number).exists():
                        profiles.add("staff")
                except Exception:
                    pass

                try:
                    from students.models import Student, StudentGuardian
                    if id_number and Student.objects.filter(user_account_id_number=id_number).exists():
                        profiles.add("student")
                    guardian_exists = False
                    if id_number:
                        guardian_exists = StudentGuardian.objects.filter(
                            user_account_id_number=id_number
                        ).exists()
                    if not guardian_exists and email:
                        guardian_exists = StudentGuardian.objects.filter(email__iexact=email).exists()
                    if guardian_exists:
                        profiles.add("parent")
                except Exception:
                    pass
        except Exception:
            continue

    order = ["staff", "student", "parent", "platform_employee"]
    return [profile for profile in order if profile in profiles]


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
        previous = SharedRoleAssignment.objects.select_related("role").filter(user=db_user).first()
        before = {
            "enabled": bool(previous and previous.is_active),
            "role_id": str(previous.role_id) if previous else None,
            "role_name": previous.role.name if previous else None,
        }
        platform_role = _get_platform_role(role)
        assignment, _ = SharedRoleAssignment.objects.update_or_create(
            user=db_user,
            defaults={"role": platform_role, "is_active": True},
        )
        _audit_platform_event(
            event_type="platform_access_enabled",
            target_user=db_user,
            actor=actor,
            before=before,
            after={"enabled": True, "role_id": str(platform_role.pk), "role_name": platform_role.name},
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
        previous = SharedRoleAssignment.objects.select_related("role").filter(user=db_user).first()
        before = {
            "enabled": bool(previous and previous.is_active),
            "role_id": str(previous.role_id) if previous else None,
            "role_name": previous.role.name if previous else None,
        }
        SharedRoleAssignment.objects.filter(user=db_user, is_active=True).update(is_active=False)
        _audit_platform_event(
            event_type="platform_access_disabled",
            target_user=db_user,
            actor=actor,
            before=before,
            after={"enabled": False},
        )

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
        previous = PlatformEmployee.objects.filter(user=db_user).values(
            "employee_number", "position", "department", "status", "hire_date", "termination_date"
        ).first()
        employment, created = PlatformEmployee.objects.update_or_create(
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
        _audit_platform_event(
            event_type="platform_employment_created" if created else "platform_employment_reactivated",
            target_user=db_user,
            actor=actor,
            before=previous,
            after={
                "employee_number": employment.employee_number,
                "position": employment.position,
                "department": employment.department,
                "status": employment.status,
                "hire_date": str(employment.hire_date) if employment.hire_date else None,
            },
        )

    if platform_role is not None:
        enable_platform_access(user=db_user, role=platform_role, actor=actor)
    return employment


@transaction.atomic
def terminate_platform_employee(*, user, actor, termination_date, revoke_access=False):
    require_platform_access_manager(actor)

    from users.models import PlatformEmployee, User

    public_schema = get_public_schema_name()
    with schema_context(public_schema):
        db_user = User.objects.get(pk=user.pk)
        try:
            employment = PlatformEmployee.objects.select_for_update().get(user_id=db_user.pk)
        except PlatformEmployee.DoesNotExist as exc:
            raise ValidationError("This user has no platform employment record.") from exc
        before = {
            "status": employment.status,
            "termination_date": str(employment.termination_date) if employment.termination_date else None,
        }
        employment.status = PlatformEmployee.EmploymentStatus.TERMINATED
        employment.termination_date = termination_date
        employment.save(update_fields=["status", "termination_date", "updated_at"])
        _audit_platform_event(
            event_type="platform_employment_terminated",
            target_user=db_user,
            actor=actor,
            before=before,
            after={
                "status": employment.status,
                "termination_date": str(employment.termination_date),
                "revoke_access": bool(revoke_access),
            },
        )

    if revoke_access:
        disable_platform_access(user=db_user, actor=actor)
    return employment
