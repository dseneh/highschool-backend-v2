"""Canonical account email, replicated only over explicit identity references."""
from django.core.validators import validate_email
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction, connection
from django.db.models import Q
from django_tenants.utils import schema_context, get_public_schema_name
from rest_framework.exceptions import ValidationError, PermissionDenied


def normalize_email(value):
    email = str(value or "").strip().lower()
    try:
        validate_email(email)
    except DjangoValidationError:
        raise ValidationError({"email": "A valid account email is required."})
    return email


def linked_account(record):
    """Never infer ownership from names, email text, or matching record numbers."""
    from users.models import User, ParentProfile
    from students.models import StudentGuardian
    guardian_id = getattr(record, "portal_guardian_id", None)
    if guardian_id:
        guardian = StudentGuardian.objects.filter(pk=guardian_id).first()
        if guardian is None:
            raise ValidationError({"email": "This contact's guardian link needs school review."})
        return linked_account(guardian)
    reference = getattr(record, "user_account_id_number", None)
    profile_id = getattr(record, "parent_profile_id", None)
    user = User.objects.filter(id_number=reference).first() if reference else None
    profile = ParentProfile.objects.select_related("user").filter(pk=profile_id).first() if profile_id else None
    if (reference and not user) or (profile_id and not profile) or (user and profile and user.pk != profile.user_id):
        raise ValidationError({"email": "This record has an inconsistent account link. Review the link before changing email."})
    return profile.user if profile else user


def require_email_editor(request, user):
    from users.access_policies import UserAccessPolicy
    from users.tenant_access import is_global_superadmin
    if request is None:
        raise PermissionDenied("Changing a linked login email requires user-account update permission. Contact your administrator.")
    schema = getattr(getattr(request, "tenant", None), "schema_name", get_public_schema_name())
    with schema_context(schema):
        permitted = UserAccessPolicy().has_rbac_permission(request, None, "update", "users.update")
    if not permitted:
        raise PermissionDenied("Changing a linked login email requires user-account update permission. Contact your administrator.")
    if not is_global_superadmin(request.user):
        if schema == "public" or not user.tenants.filter(schema_name=schema).exists():
            raise PermissionDenied("This account is not linked to your school.")
    if user.is_platform_superuser and not is_global_superadmin(request.user):
        raise PermissionDenied("Only a platform administrator can change this account's email.")


def sync_record_email(record, data, request):
    if "email" not in data:
        return
    user = linked_account(record)
    if user is None:
        return
    email = normalize_email(data["email"])
    if email != user.email:
        require_email_editor(request, user)
        set_account_email(user, email)
    data["email"] = user.email


@transaction.atomic
def set_account_email(user, email):
    from users.models import User, ParentProfile, ParentStudentLink, ParentSchoolRegistration, VerifiedAccountEmail
    from core.models import Tenant
    from staff.models import Staff
    from hr.models import Employee
    from students.models import Student, StudentGuardian, StudentContact
    email = normalize_email(email)
    current_schema = connection.schema_name
    locked = User.objects.select_for_update().get(pk=user.pk)
    if User.objects.filter(email__iexact=email).exclude(pk=user.pk).exists():
        raise ValidationError({"email": "This email is already assigned to another account."})
    changed = locked.email != email
    if changed:
        locked.email = email
        locked.is_verified = False
        locked.save(update_fields=["email", "is_verified"])
        # An address change never carries verification to the replacement email.
        VerifiedAccountEmail.objects.filter(user=locked).delete()
    profile = ParentProfile.objects.filter(user=locked).first()
    school_ids = set(locked.tenants.values_list("pk", flat=True))
    if profile:
        school_ids.update(ParentStudentLink.objects.filter(profile=profile).values_list("tenant_id", flat=True))
        school_ids.update(ParentSchoolRegistration.objects.filter(profile=profile).values_list("tenant_id", flat=True))
    schools = Tenant.objects.filter(Q(pk__in=school_ids) | Q(schema_name=current_schema)).exclude(schema_name=get_public_schema_name())
    for school in schools:
        with schema_context(school.schema_name):
            for model in (Staff, Employee, Student):
                model.objects.filter(user_account_id_number=locked.id_number).exclude(email=email).update(email=email)
            links = Q(user_account_id_number=locked.id_number)
            if profile:
                links |= Q(parent_profile_id=profile.pk)
            guardians = StudentGuardian.objects.filter(links)
            # Contradictory identity references must not propagate a takeover.
            conflicting_profiles = guardians.exclude(parent_profile_id__isnull=True)
            if profile:
                conflicting_profiles = conflicting_profiles.exclude(parent_profile_id=profile.pk)
            if conflicting_profiles.exists():
                raise ValidationError({"email": "A guardian has conflicting account references. Review the link first."})
            if guardians.exclude(user_account_id_number__in=[locked.id_number, ""]).exclude(user_account_id_number__isnull=True).exists():
                raise ValidationError({"email": "A guardian has conflicting account references. Review the link first."})
            guardian_ids = list(guardians.values_list("pk", flat=True))
            guardians.exclude(email=email).update(email=email)
            StudentContact.objects.filter(portal_guardian_id__in=guardian_ids).exclude(email=email).update(email=email)
    user.email = email
    if changed:
        user.is_verified = False
    return user
