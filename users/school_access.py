"""Explicit school approval for people without employee/student records."""
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction, connection, IntegrityError
from django.utils import timezone
from django_tenants.utils import schema_context
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied, ValidationError
from authorization.runtime import resolve_authorization_context
from authorization.services import resolve_assignable_role, validate_permission_delegation
from users.models import SchoolUserAccess, User
from users.parent_portal import school_available


class SchoolUserAccessSerializer(serializers.Serializer):
    email = serializers.EmailField()
    first_name = serializers.CharField(max_length=100)
    last_name = serializers.CharField(max_length=100)
    role = serializers.CharField()


def require_manager(actor, tenant):
    if connection.schema_name != tenant.schema_name or not school_available(tenant):
        raise PermissionDenied("Open an active school workspace to manage school access.")
    context = resolve_authorization_context(actor)
    if any(context.permission_scope(code) != "all" for code in ("users.create", "roles.assign_users")):
        raise PermissionDenied("School-wide user creation and role assignment permissions are required.")


def access_role(identifier):
    try:
        role = resolve_assignable_role(identifier)
    except DjangoValidationError as exc:
        raise ValidationError({"role": exc.messages})
    if role.system_key in {"parent", "student", "staff", "teacher"}:
        raise ValidationError({"role": "Use the linked employee, student, or guardian workflow for this role."})
    return role


def role_grants(role):
    return dict(role.permission_grants.values_list("permission_code", "scope"))


@transaction.atomic
def approve_access(tenant, actor, data, *, existing_record=None):
    require_manager(actor, tenant)
    serializer = SchoolUserAccessSerializer(data=data)
    serializer.is_valid(raise_exception=True)
    values = serializer.validated_data
    role = access_role(values.pop("role"))
    grants = role_grants(role)
    try:
        validate_permission_delegation(actor, grants)
    except DjangoValidationError as exc:
        raise PermissionDenied(exc.messages[0])
    email = values.pop("email").strip().lower()
    existing = User.objects.filter(email__iexact=email).first()
    if existing and existing.pk == actor.pk:
        raise PermissionDenied("You cannot approve your own school access.")
    if existing and (not existing.is_active or existing.status != "active"):
        raise ValidationError("This account is unavailable. Contact the platform administrator.")
    if existing:
        from authorization.models import TenantMembership, TenantRoleAssignment
        from authorization.multiple_roles import role_key
        if TenantMembership.objects.filter(user=existing, is_active=False).exists():
            raise ValidationError("School access is suspended. Restore the membership before adding access.")
        if TenantRoleAssignment.objects.filter(
            membership__user=existing, membership__is_active=True,
            role_key=role_key(role), is_active=True,
        ).exists():
            raise ValidationError("This account already has this role in this school.")
    if SchoolUserAccess.objects.filter(tenant=tenant, email__iexact=email, role_id=role.pk, status="pending").exclude(pk=getattr(existing_record, "pk", None)).exists():
        raise ValidationError("Pending access already exists for this email and role.")
    try:
        with transaction.atomic():
            record = existing_record or SchoolUserAccess(tenant=tenant)
            for key, value in {**values, "email": email, "role_id": role.pk, "role_name": role.name,
                    "permission_version": role.permission_version, "approved_grants": grants,
                    "approved_by": actor, "instructions_sent_at": None, "instructions_failed": False}.items():
                setattr(record, key, value)
            record.save()
    except IntegrityError:
        raise ValidationError("Access approval changed during this request. Refresh and try again.")
    from authorization.models import AuthorizationAuditLog
    AuthorizationAuditLog.objects.create(actor=actor, action="school_access.edited" if existing_record else "school_access.approved", target_type="school_access", target_id=str(record.pk), after={"role_id": str(role.pk), "email": email})
    return record


def eligible_access(tenant, email, snapshot=None, lock=False):
    query = SchoolUserAccess.objects.filter(tenant=tenant, email__iexact=email, status="pending")
    if snapshot is not None:
        query = query.filter(pk__in=snapshot.get("school_access", []))
    if lock:
        query = query.select_for_update()
    records = list(query.order_by("created_at"))
    if not records or (snapshot is not None and len(records) != len(snapshot.get("school_access", []))):
        raise ValidationError("No pending school access matches this email. Contact the school.")
    if snapshot is not None and snapshot.get("school_access_versions") != access_versions(records):
        raise ValidationError("The school approval has changed. Start account setup again.")
    with schema_context(tenant.schema_name):
        for record in records:
            role = access_role(str(record.role_id))
            if role.permission_version != record.permission_version or role_grants(role) != record.approved_grants:
                raise ValidationError("The approved role has changed. Ask the school to approve access again.")
    accounts = list(User.objects.filter(email__iexact=email)[:2])
    if len(accounts) > 1:
        raise ValidationError("Multiple accounts match this email. Contact the school.")
    account = accounts[0] if accounts else None
    if account and (not account.is_active or account.status != "active"):
        raise ValidationError("This account is unavailable. Contact the school.")
    return {"school_access": records}


def activate_access(records, user, tenant):
    from authorization.models import TenantRoleAssignment, Role
    from authorization.multiple_roles import add_role, role_key
    if not user.tenants.filter(pk=tenant.pk).exists():
        tenant.add_user(user, is_staff=False, is_superuser=False)
    for record in records:
        role = Role.objects.select_for_update().get(pk=record.role_id)
        access_role(str(role.pk))
        if role.permission_version != record.permission_version or role_grants(role) != record.approved_grants:
            raise ValidationError("The approved role has changed. Ask the school to approve access again.")
        key = role_key(role)
        if TenantRoleAssignment.objects.filter(membership__user=user, role_key=key, is_active=False).exists():
            raise PermissionDenied("This role was withdrawn. Ask the school to restore access.")
        add_role(user=user, role=role, metadata={})
        record.status = "accepted"
        record.user = user
        record.accepted_at = timezone.now()
        record.save(update_fields=["status", "user", "accepted_at"])


def access_versions(records):
    """Bind email proof to the exact approved identity and role details."""
    import hashlib
    import json
    return {str(record.pk): hashlib.sha256(json.dumps({
        "email": record.email, "first_name": record.first_name, "last_name": record.last_name,
        "role": str(record.role_id), "version": record.permission_version,
        "grants": record.approved_grants,
    }, sort_keys=True).encode()).hexdigest() for record in records}


def send_setup_instructions(record):
    from types import SimpleNamespace
    from common.email_service import send_notification_email
    from users.utils import build_frontend_url
    import logging
    url = build_frontend_url(record.tenant.schema_name, "/account-setup")
    try:
        sent = bool(send_notification_email(
            SimpleNamespace(email=record.email, first_name=record.first_name, pk=record.pk),
            f"Your access to {record.tenant.name}",
            f"{record.tenant.name} has approved your school access as {record.role_name}. "
            "Open the link below, choose School user, and enter this email address. "
            "We will email you a six-digit verification code. After verification, confirm your details and accept the terms. "
            "If you already have an EzySchool account, use your existing password; otherwise choose a new password. "
            "You can use Forgot password if needed. No employee record is required.",
            school=record.tenant, action_url=url, category="School access"))
    except Exception:
        logging.getLogger(__name__).exception("School access instructions could not be delivered")
        sent = False
    record.instructions_failed = not sent
    if sent:
        record.instructions_sent_at = timezone.now()
    SchoolUserAccess.objects.filter(pk=record.pk, status="pending", email=record.email).update(instructions_failed=record.instructions_failed, instructions_sent_at=record.instructions_sent_at)
    return sent
