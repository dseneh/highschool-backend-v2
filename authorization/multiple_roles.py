"""School-scoped role assignments. Selection never changes a user's grants."""
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django_tenants.utils import get_public_schema_name, schema_context

from authorization.constants import SUPERADMIN_ROLE_KEYS
from authorization.models import AuthorizationAuditLog, TenantMembership, TenantRoleAssignment


def assignment_role(assignment):
    if assignment.role_id:
        return assignment.role
    from core.models import SharedRole
    with schema_context(get_public_schema_name()):
        return SharedRole.objects.filter(pk=assignment.shared_role_id, scope__in=["TENANT", "GLOBAL"]).first()


def role_key(role):
    return f"system:{role.system_key}" if role.system_key else f"{role._meta.label_lower}:{role.pk}"


def seed_default_assignment(membership):
    """Bridge existing account provisioning to the new assignment table."""
    role = assignment_role(membership)
    if role is not None:
        TenantRoleAssignment.objects.get_or_create(
            membership=membership, role_key=role_key(role),
            defaults={"role_id": membership.role_id, "shared_role_id": membership.shared_role_id,
                      "is_active": membership.is_active},
        )


def selected_assignment(user, selection=None):
    selection = selection if selection is not None else getattr(user, "_active_role_selection", None)
    membership = TenantMembership.objects.filter(user=user, is_active=True).first()
    if not membership:
        return None
    assignments = membership.role_assignments.select_related("role")
    if selection:
        try:
            assignment = assignments.filter(pk=selection, is_active=True).first()
        except (ValueError, ValidationError):
            return None
    else:
        filters = {"role_id": membership.role_id} if membership.role_id else {"shared_role_id": membership.shared_role_id}
        assignment = assignments.filter(is_active=True, **filters).first()
    role = assignment_role(assignment) if assignment else None
    if role and role.is_active:
        return assignment
    # Only an unselected/new session may choose another usable assignment.
    # An explicitly selected revoked/disabled role must fail closed.
    if not selection:
        for candidate in assignments.filter(is_active=True):
            candidate_role = assignment_role(candidate)
            if candidate_role and candidate_role.is_active:
                return candidate
    return None


def parent_removal_reason(user):
    from students.models import StudentGuardian
    if StudentGuardian.objects.filter(user_account_id_number=user.id_number, active=True).exists():
        return "Parent access is required by active guardian links in this school. Manage those links before revoking this role."
    # Legacy parent accounts may predate reliable guardian linking. Preserve their
    # fixed role until the guardian migration can establish their eligibility.
    if str(user.account_type).lower() == "parent":
        return "This parent account's base role is protected. Resolve its guardian access before revoking Parent."
    return None


def assignment_payload(assignment):
    from authorization.services import serialize_shared_role, serialize_tenant_role
    role = assignment_role(assignment)
    if not role:
        return None
    reason = parent_removal_reason(assignment.membership.user) if role.system_key == "parent" else None
    if role.system_key in SUPERADMIN_ROLE_KEYS:
        reason = "Platform administrator access is managed separately."
    if role.system_key == "student" and str(assignment.membership.user.account_type).lower() == "student":
        reason = "The Student base role is protected."
    return {
        "id": str(assignment.pk),
        "role": serialize_tenant_role(role) if assignment.role_id else serialize_shared_role(role),
        "is_active": assignment.is_active and role.is_active and assignment.membership.is_active,
        "can_revoke": reason is None,
        "revocation_blocked_reason": reason,
    }


def user_assignments_payload(user, *, selection=None):
    membership = TenantMembership.objects.filter(user=user).first()
    selected = selected_assignment(user, selection)
    assignments = []
    if membership:
        for assignment in membership.role_assignments.filter(is_active=True).select_related("role", "membership__user"):
            payload = assignment_payload(assignment)
            if payload:
                assignments.append(payload)
    active = next((item for item in assignments if selected and item["id"] == str(selected.pk)), None)
    return {
        "user_id": str(user.pk), "id_number": user.id_number,
        "membership_id": str(membership.pk) if membership else None,
        "role": active["role"] if active else None,
        "active_assignment_id": active["id"] if active else None,
        "assignments": assignments,
        "is_active": active is not None,
    }


def _audit(action, assignment, actor, metadata):
    from authorization.services import _audit_metadata
    AuthorizationAuditLog.objects.create(
        actor=actor, action=action, target_type="role_assignment", target_id=str(assignment.pk),
        after={"user_id": str(assignment.membership.user_id), "role_key": assignment.role_key,
               "active": assignment.is_active}, **_audit_metadata(metadata),
    )


@transaction.atomic
def add_role(*, user, role, actor=None, metadata=None):
    from authorization.services import validate_role_for_account_type
    if not role.is_active or role.system_key in SUPERADMIN_ROLE_KEYS:
        raise ValidationError("Inactive or platform superadmin roles cannot be assigned.")
    shared = role._meta.label_lower == "core.sharedrole"
    if shared and role.scope not in {"TENANT", "GLOBAL"}:
        raise ValidationError("This role is not available in school workspaces.")
    validate_role_for_account_type(user=user, role=role)
    if actor and actor.pk == user.pk:
        raise ValidationError("You cannot change your own role assignments.")
    # Serialize grants for this identity, including concurrent first assignment.
    from users.models import User
    User.objects.select_for_update().get(pk=user.pk)
    membership = TenantMembership.objects.select_for_update().filter(user=user).first()
    if membership is None:
        membership = TenantMembership(user=user, role=None if shared else role,
                                      shared_role_id=role.pk if shared else None)
        membership.save()
    assignment, _ = TenantRoleAssignment.objects.get_or_create(
        membership=membership, role_key=role_key(role),
        defaults={"role": None if shared else role, "shared_role_id": role.pk if shared else None},
    )
    if not assignment.is_active:
        assignment.is_active = True
        assignment.save(update_fields=["is_active", "updated_at"])
    if not membership.is_active:
        membership.is_active = True
        membership.role_id = assignment.role_id
        membership.shared_role_id = assignment.shared_role_id
        membership.save()
    _audit("role_assignment.granted", assignment, actor, metadata)
    return membership


@transaction.atomic
def revoke_role(*, user, assignment_id, actor, metadata=None):
    # Lock all memberships in a stable order to serialize last-admin checks.
    list(TenantMembership.objects.select_for_update().order_by("pk").values_list("pk", flat=True))
    assignment = TenantRoleAssignment.objects.select_related("membership__user", "role").filter(
        pk=assignment_id, membership__user=user, is_active=True,
    ).first()
    if assignment is None:
        raise ValidationError("Active role assignment not found.")
    if actor and user.pk == actor.pk:
        raise ValidationError("You cannot revoke your own role assignments.")
    payload = assignment_payload(assignment)
    if payload and not payload["can_revoke"]:
        raise ValidationError(payload["revocation_blocked_reason"])
    role = assignment_role(assignment)
    if role and role.system_key == "admin":
        other_admin = TenantRoleAssignment.objects.filter(
            role_key="system:admin", is_active=True, membership__is_active=True,
            membership__user__is_active=True,
        ).exclude(pk=assignment.pk).exists()
        if not other_admin:
            raise ValidationError("The school must retain at least one administrator.")
    assignment.is_active = False
    assignment.save(update_fields=["is_active", "updated_at"])
    membership = assignment.membership
    if membership.role_id == assignment.role_id and membership.shared_role_id == assignment.shared_role_id:
        replacement = next((item for item in membership.role_assignments.filter(is_active=True).select_related("role")
                            if (candidate := assignment_role(item)) and candidate.is_active), None)
        if replacement:
            membership.role_id, membership.shared_role_id = replacement.role_id, replacement.shared_role_id
        else:
            membership.is_active = False
        membership.save()
    from authorization.cache import schedule_membership_invalidation
    schedule_membership_invalidation(connection.schema_name, user.pk)
    _audit("role_assignment.revoked", assignment, actor, metadata)
    return assignment
