"""Verified parent lifecycle; tenant guardian rows, never the index, authorize access."""
import hashlib
import secrets
from datetime import timedelta
from django.db import connection, transaction
from django.utils import timezone
from django_tenants.utils import schema_context, get_public_schema_name
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from users.models import ParentProfile, ParentStudentLink, ParentInvitation, User


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def school_available(tenant):
    return bool(tenant.active and tenant.status == "active" and not tenant.maintenance_mode
                and not tenant.restoration_in_progress and tenant.schema_name != get_public_schema_name())


def verified_guardians(user):
    from students.models import StudentGuardian
    if connection.schema_name == get_public_schema_name():
        return StudentGuardian.objects.none()
    profile = ParentProfile.objects.filter(user=user).first()
    return StudentGuardian.objects.filter(parent_profile_id=profile.pk,
        portal_state="active", give_access=True, portal_approved_at__isnull=False,
        portal_verified_at__isnull=False, portal_ended_at__isnull=True,
        active=True, student__active=True,
    ).exclude(student__status="deleted") if profile else StudentGuardian.objects.none()


def parent_assignment(user):
    from authorization.models import TenantRoleAssignment
    from authorization.multiple_roles import assignment_role
    assignment = TenantRoleAssignment.objects.filter(membership__user=user, membership__is_active=True,
        role_key="system:parent", is_active=True).select_related("role").first()
    role = assignment_role(assignment) if assignment else None
    return assignment if role and role.is_active else None


@transaction.atomic
def reconcile_parent(profile, tenant):
    """Idempotent index and role repair, including ending the final eligible link."""
    from authorization.models import Role, TenantMembership
    from authorization.multiple_roles import add_role, assignment_role
    from authorization.cache import schedule_membership_invalidation
    from students.models import StudentGuardian
    user = User.objects.select_for_update().get(pk=profile.user_id)
    with schema_context(tenant.schema_name):
        guardians = list(verified_guardians(user))
        ParentStudentLink.objects.filter(profile=profile, tenant=tenant).exclude(guardian_id__in=[g.pk for g in guardians]).update(active=False)
        for guardian in guardians:
            ParentStudentLink.objects.update_or_create(profile=profile, tenant=tenant, guardian_id=guardian.pk, defaults={"active": True})
        from users.models import ParentSchoolRegistration
        if guardians or ParentSchoolRegistration.objects.filter(profile=profile, tenant=tenant).exists():
            if not user.tenants.filter(pk=tenant.pk).exists():
                tenant.add_user(user, is_staff=False, is_superuser=False)
            role = Role.objects.filter(system_key="parent", is_active=True).first()
            if role is None:
                from core.models import SharedRole
                role = SharedRole.objects.filter(system_key="parent", is_active=True, scope__in=["TENANT", "GLOBAL"]).first()
            if role is None:
                raise ValidationError("The school must configure its Parent role first.")
            add_role(user=user, role=role)
        elif not (user.account_type == "parent" and StudentGuardian.objects.filter(
            user_account_id_number=user.id_number, active=True, portal_state="unverified").exists()):
            membership = TenantMembership.objects.select_for_update().filter(user=user).first()
            if membership:
                membership.role_assignments.filter(role_key="system:parent").update(is_active=False)
                remaining = next((a for a in membership.role_assignments.filter(is_active=True).select_related("role")
                                  if (r := assignment_role(a)) and r.is_active), None)
                current = assignment_role(membership)
                if not remaining:
                    membership.is_active = False
                elif current and current.system_key == "parent":
                    membership.role_id, membership.shared_role_id = remaining.role_id, remaining.shared_role_id
                membership.save()
        schedule_membership_invalidation(tenant.schema_name, user.pk)


@transaction.atomic
def issue_invitation(*, tenant, guardian_id, actor):
    """Authorized staff approve the relationship by issuing. Delivery is separate."""
    from students.models import StudentGuardian
    from django.core.validators import validate_email
    if not school_available(tenant):
        raise ValidationError("School is unavailable.")
    with schema_context(tenant.schema_name):
        guardian = StudentGuardian.objects.select_for_update().get(pk=guardian_id)
        if not guardian.active or not guardian.student.active or guardian.student.status == "deleted":
            raise ValidationError("This guardian relationship is inactive.")
        if guardian.portal_state == "active":
            raise ValidationError("Disconnect the existing portal link before inviting another account.")
        email = (guardian.email or "").strip().lower()
        try:
            validate_email(email)
        except Exception:
            raise ValidationError("A valid guardian email is required.")
        now = timezone.now()
        if ParentInvitation.objects.filter(tenant=tenant, guardian_id=guardian.pk, created_at__gt=now-timedelta(minutes=1)).exists():
            raise ValidationError("Please wait one minute before resending.")
        ParentInvitation.objects.filter(tenant=tenant, guardian_id=guardian.pk, accepted_at=None, revoked_at=None).update(revoked_at=now)
        token = secrets.token_urlsafe(32)
        invitation = ParentInvitation.objects.create(tenant=tenant, guardian_id=guardian.pk, email=email,
            token_hash=token_hash(token), issued_by=actor, expires_at=now+timedelta(hours=48))
        guardian.portal_state = "invited"
        guardian.portal_approved_at, guardian.portal_approved_by = now, actor.pk
        guardian.save(update_fields=["portal_state", "portal_approved_at", "portal_approved_by", "updated_at"])
        audit_link(guardian, actor, "invited")
        return invitation, token


@transaction.atomic
def accept_invitation(*, token, user=None, password=None, first_name="", last_name=""):
    from students.models import StudentGuardian
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError as DjangoValidationError
    from common.utils import ID_ENTITY_PARENT, generate_entity_id_number
    if not isinstance(token, str) or not 20 <= len(token) <= 200:
        raise ValidationError("Invalid or unavailable invitation.")
    invitation = ParentInvitation.objects.select_for_update().select_related("tenant").filter(token_hash=token_hash(token)).first()
    now = timezone.now()
    if not invitation or invitation.accepted_at or invitation.revoked_at or not invitation.delivered_at or invitation.expires_at <= now or not school_available(invitation.tenant):
        raise ValidationError("Invalid or unavailable invitation.")
    if user is not None:
        user = User.objects.select_for_update().get(pk=user.pk)
        if not user.is_active or user.email.strip().lower() != invitation.email:
            raise ValidationError("Invalid or unavailable invitation.")
    else:
        if User.objects.filter(email__iexact=invitation.email).exists() or not password:
            raise ValidationError("Unable to register. Sign in to your existing account or request school assistance.")
        user = User(email=invitation.email, first_name=first_name, last_name=last_name, account_type="parent",
                    id_number=generate_entity_id_number(User, ID_ENTITY_PARENT))
        try:
            validate_password(password, user)
        except DjangoValidationError as exc:
            raise ValidationError({"password": exc.messages})
        user.set_password(password)
        user.save()
    from users.account_setup import record_email_proof
    record_email_proof(user)
    with schema_context(invitation.tenant.schema_name):
        guardian = StudentGuardian.objects.select_for_update().filter(pk=invitation.guardian_id, active=True,
            portal_state="invited", portal_approved_at__isnull=False, student__active=True).exclude(student__status="deleted").first()
        if not guardian or (guardian.email or "").strip().lower() != invitation.email:
            raise ValidationError("Invalid or unavailable invitation.")
        profile, _ = ParentProfile.objects.get_or_create(user=user)
        if guardian.parent_profile_id and guardian.parent_profile_id != profile.pk:
            raise ValidationError("School review is required to change the linked identity.")
        guardian.parent_profile_id = profile.pk
        guardian.user_account_id_number = user.id_number
        guardian.give_access = True
        guardian.portal_state = "active"
        guardian.portal_verified_at, guardian.portal_ended_at = now, None
        guardian.save()
        reconcile_parent(profile, invitation.tenant)
        audit_link(guardian, user, "accepted")
    invitation.accepted_at, invitation.accepted_by = now, user
    invitation.save(update_fields=["accepted_at", "accepted_by"])
    return profile


@transaction.atomic
def end_link(*, tenant, guardian_id, actor, state="disconnected"):
    if connection.schema_name != tenant.schema_name:
        raise PermissionDenied("Select the guardian's school first.")
    from students.models import StudentGuardian
    guardian = StudentGuardian.objects.get(pk=guardian_id)
    profile = ParentProfile.objects.filter(pk=guardian.parent_profile_id).first()
    if profile:
        User.objects.select_for_update().get(pk=profile.user_id)
    guardian = StudentGuardian.objects.select_for_update().get(pk=guardian_id)
    guardian.give_access = False
    guardian.portal_state, guardian.portal_ended_at = state, timezone.now()
    guardian.updated_by = actor
    guardian.save(update_fields=["give_access", "portal_state", "portal_ended_at", "updated_by", "updated_at"])
    ParentInvitation.objects.filter(tenant=tenant, guardian_id=guardian.pk, accepted_at=None, revoked_at=None).update(revoked_at=timezone.now())
    audit_link(guardian, actor, state)
    if profile:
        reconcile_parent(profile, tenant)


def link_payload(link, guardian, request=None):
    student = guardian.student
    # Storage derives its prefix from the schema; resolve URLs before leaving it.
    with schema_context(link.tenant.schema_name):
        photo = student.photo.url if student.photo else None
        grade_level = student.enrollments.filter(active=True, academic_year__current=True).values_list("grade_level__name", flat=True).first()
    if request and photo:
        photo = request.build_absolute_uri(photo)
    return {"link_id": str(link.pk), "student": {"id": str(student.pk), "id_number": student.id_number,
        "display_name": student.get_full_name(), "photo": photo, "grade_level": grade_level},
        "school": {"id": str(link.tenant_id), "schema_name": link.tenant.schema_name, "name": link.tenant.name},
        "relationship": guardian.relationship, "is_primary": guardian.is_primary}


def resolve_link(user, link_id, *, require_context=False):
    link = ParentStudentLink.objects.select_related("tenant", "profile").filter(pk=link_id, profile__user=user, active=True).first()
    if not link or not school_available(link.tenant):
        raise NotFound("Student link unavailable.")
    if require_context and connection.schema_name != link.tenant.schema_name:
        raise PermissionDenied("Select the student's school first.")
    with schema_context(link.tenant.schema_name):
        assignment = parent_assignment(user)
        guardian = verified_guardians(user).select_related("student").filter(pk=link.guardian_id).first()
        if not guardian or not assignment:
            raise NotFound("Student link unavailable.")
        from copy import copy
        from authorization.runtime import resolve_authorization_context
        parent_user = copy(user)
        parent_user._active_role_selection = str(assignment.pk)
        if not resolve_authorization_context(parent_user).permission_scope("students.view"):
            raise NotFound("Student link unavailable.")
        if require_context:
            from authorization.multiple_roles import selected_assignment
            selected = selected_assignment(user)
            if not selected or selected.pk != assignment.pk:
                raise PermissionDenied("Switch to Parent to view this student.")
        return link, guardian, assignment


@transaction.atomic
def attach_approved_relationship(*, tenant, guardian_id, profile_id, actor):
    """Staff explicitly select an identity already verified by this school; no text matching."""
    if connection.schema_name != tenant.schema_name:
        raise PermissionDenied("Select the guardian's school first.")
    from students.models import StudentGuardian
    profile = ParentProfile.objects.select_related("user").get(pk=profile_id)
    User.objects.select_for_update().get(pk=profile.user_id)
    if not school_available(tenant) or not verified_guardians(profile.user).exists():
        raise ValidationError("This identity needs a verified invitation in this school first.")
    guardian = StudentGuardian.objects.select_for_update().get(pk=guardian_id, active=True)
    if not guardian.student.active or guardian.student.status == "deleted":
        raise ValidationError("This student is inactive.")
    if guardian.parent_profile_id and guardian.parent_profile_id != profile.pk:
        raise ValidationError("School review is required to change the linked identity.")
    if guardian.portal_state in {"suspended", "disconnected"}:
        raise ValidationError("A new invitation is required to restore ended access.")
    guardian.parent_profile_id = profile.pk
    guardian.user_account_id_number = profile.user.id_number
    guardian.email = profile.user.email
    guardian.give_access = True
    guardian.portal_state = "active"
    guardian.portal_approved_by = actor.pk
    guardian.portal_approved_at = guardian.portal_verified_at = timezone.now()
    guardian.portal_ended_at = None
    guardian.updated_by = actor
    guardian.save()
    reconcile_parent(profile, tenant)
    audit_link(guardian, actor, "approved_existing_identity")


def audit_link(guardian, actor, action):
    from authorization.models import AuthorizationAuditLog
    AuthorizationAuditLog.objects.create(actor=actor, action=f"parent_link.{action}", target_type="guardian",
        target_id=str(guardian.pk), after={"profile_id": str(guardian.parent_profile_id or ""),
        "state": guardian.portal_state, "student_id": str(guardian.student_id)})


def parent_communications(user, student):
    """Only delivered school/parent messages whose audience includes this student."""
    from notifications.models import Notification
    enrollments = student.enrollments.filter(active=True)
    section_ids = {str(value) for value in enrollments.values_list("section_id", flat=True)}
    grade_ids = {str(value) for value in enrollments.values_list("grade_level_id", flat=True)}
    result = []
    for message in Notification.objects.filter(recipient=user, active=True, archived_at=None,
            campaign__status="sent", campaign__category__in=["announcement", "alert"]).select_related("campaign").order_by("-created_at")[:100]:
        campaign = message.campaign
        audience = campaign.audience or {}
        scope = audience.get("scope")
        included = scope == "all"
        if scope in {"parents_of_students", "grade_sections"}:
            students = {str(value) for value in audience.get("student_ids", [])}
            sections = {str(value) for value in audience.get("section_ids", [])}
            grades = {str(value) for value in audience.get("grade_level_ids", [])}
            included = str(student.pk) in students if students else bool(section_ids & sections) if sections else bool(grade_ids & grades)
        if included:
            result.append({"id": str(message.pk), "title": campaign.title, "body": campaign.body, "sent_at": campaign.sent_at})
    return result[:30]


def validate_invitation_email(*, token, email, tenant=None, lock=False):
    """Validate a delivered invitation and its authoritative relationship without granting access."""
    from students.models import StudentGuardian
    if not isinstance(token, str) or not 20 <= len(token) <= 200:
        raise ValidationError("This invitation is invalid or unavailable. Ask the school for a new invitation.")
    query = ParentInvitation.objects.select_related("tenant")
    if lock:
        query = query.select_for_update()
    invitation = query.filter(token_hash=token_hash(token)).first()
    if (not invitation or invitation.accepted_at or invitation.revoked_at or not invitation.delivered_at
        or invitation.expires_at <= timezone.now() or not school_available(invitation.tenant)
        or (tenant is not None and invitation.tenant_id != tenant.pk)):
        raise ValidationError("This invitation is invalid or unavailable. Ask the school for a new invitation.")
    if (email or "").strip().lower() != invitation.email:
        raise ValidationError("Use the email address the school invited. Contact the school if it needs correcting.")
    with schema_context(invitation.tenant.schema_name):
        guardian = StudentGuardian.objects.filter(pk=invitation.guardian_id, active=True,
            portal_state="invited", portal_approved_at__isnull=False, student__active=True).exclude(student__status="deleted").first()
        if not guardian or (guardian.email or "").strip().lower() != invitation.email:
            raise ValidationError("This invitation is invalid or unavailable. Ask the school for a new invitation.")
    return invitation


def invitation_staff_details(invitation, *, lock=False):
    """Minimal bio from the inviting school's canonical HR record, after token verification.

    This is prefill only: never create employee links or grant employee roles.
    Refuse ambiguity and pre-existing account references rather than merging people.
    """
    from hr.models import Employee
    with schema_context(invitation.tenant.schema_name):
        query = Employee.objects.filter(email__iexact=invitation.email, active=True)
        if lock:
            query = query.select_for_update()
        matches = list(query[:2])
        if len(matches) > 1:
            raise ValidationError("More than one staff record uses this email. Contact the school to correct the records.")
        if not matches:
            return None
        employee = matches[0]
        if employee.user_account_id_number:
            raise ValidationError("This staff record is already linked to an account. Sign in or contact the school.")
        return {"first_name": employee.first_name, "last_name": employee.last_name,
                "gender": employee.gender, "date_of_birth": employee.date_of_birth}


@transaction.atomic
def register_invited_parent(*, token, email, password, first_name, last_name, gender="", date_of_birth=None):
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError as DjangoValidationError
    from common.utils import ID_ENTITY_PARENT, generate_entity_id_number
    invitation = validate_invitation_email(token=token, email=email, lock=True)
    if User.objects.filter(email__iexact=invitation.email).exists():
        raise ValidationError("An account already exists for this email. Sign in to continue.")
    # Re-read locked source values at submission: disabled inputs are not a security boundary.
    details = invitation_staff_details(invitation, lock=True) or {
        "first_name": first_name, "last_name": last_name, "gender": gender, "date_of_birth": date_of_birth}
    if details["date_of_birth"] and details["date_of_birth"] > timezone.localdate():
        raise ValidationError({"date_of_birth": "Date of birth cannot be in the future."})
    user = User(email=invitation.email, **details, account_type="parent",
                id_number=generate_entity_id_number(User, ID_ENTITY_PARENT))
    try:
        validate_password(password, user)
    except DjangoValidationError as exc:
        raise ValidationError({"password": exc.messages})
    user.set_password(password)
    user.save()
    # Registration alone does not activate the invitation or grant any school role.
    return user, invitation
