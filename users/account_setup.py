"""School-scoped account setup. Email lookup is eligibility, never proof of ownership."""
import secrets
from datetime import timedelta
from types import SimpleNamespace
from django.conf import settings
from django.contrib.auth.hashers import make_password, check_password
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from django_tenants.utils import schema_context
from rest_framework.exceptions import ValidationError, PermissionDenied, Throttled
from users.models import User, ParentProfile, AccountSetupChallenge, VerifiedAccountEmail, ParentSchoolRegistration
from users.parent_portal import school_available, token_hash, reconcile_parent, audit_link

PARENT_NAME_FIELDS = ("first_name", "middle_name", "last_name")
BIO_FIELDS = ("first_name", "last_name", "gender", "date_of_birth", "phone_number", "address")


def require_parent_setup_eligible(email):
    account = User.objects.filter(email__iexact=email).first()
    if account and (account.account_type == "parent" or ParentProfile.objects.filter(user=account).exists()):
        raise ValidationError("A parent account already exists for this email. Sign in, or use Forgot password to recover it.")
    if account and (not account.is_active or account.status != "active"):
        raise ValidationError("This account is unavailable. Contact your school.")


def reserve_setup_email(email):
    """One send per address per minute, shared by school and parent entry points."""
    from django.core.cache import cache
    if AccountSetupChallenge.objects.filter(email=email, created_at__gt=timezone.now()-timedelta(minutes=1)).exists():
        raise Throttled(wait=60, detail="Wait one minute before requesting another code.")
    if not cache.add(f"account-setup-email:{token_hash(email)}", True, timeout=60):
        raise Throttled(wait=60, detail="Wait one minute before requesting another code.")


def setup_source_details(record, kind):
    fields = PARENT_NAME_FIELDS if kind == "parent" else BIO_FIELDS
    return {key: getattr(record, key, None) for key in fields}


def validate_parent_identity_references(records, account):
    """Missing references may be rebound only by verified setup, never lookup alone."""
    owners = {r.user_account_id_number for r in records if getattr(r, "user_account_id_number", None)}
    profiles = {r.parent_profile_id for r in records if getattr(r, "parent_profile_id", None)}
    live_owners = User.objects.filter(id_number__in=owners)
    live_profiles = ParentProfile.objects.filter(pk__in=profiles)
    if account:
        live_owners = live_owners.exclude(pk=account.pk)
        live_profiles = live_profiles.exclude(user=account)
    if live_owners.exists() or live_profiles.exists():
        raise ValidationError("A school record is linked to another account. Contact the school.")


def source_records(tenant, kind, email, *, snapshot=None, lock=False):
    from hr.models import Employee
    from students.models import Student, StudentGuardian, StudentContact
    if not school_available(tenant):
        raise ValidationError("This school is unavailable.")
    from staff.models import Staff
    with schema_context(tenant.schema_name):
        staff_model = {"employee": Employee} if Employee.objects.filter(email__iexact=email).exists() else {"staff": Staff}
    models = staff_model if kind == "staff" else {"student": Student} if kind == "student" else {"guardian": StudentGuardian, "contact": StudentContact}
    result = {}
    with schema_context(tenant.schema_name):
        for key, model in models.items():
            query = model.objects.filter(email__iexact=email, active=True)
            if key == "student":
                query = query.exclude(status__in=["deleted", "withdrawn", "transferred", "graduated", "suspended"])
            elif key == "staff":
                query = query.filter(status="active")
            elif key == "employee":
                query = query.exclude(employment_status__in=["terminated", "suspended", "inactive", "retired"])
            else:
                query = query.filter(student__active=True).exclude(student__status="deleted")
                if key == "contact":
                    query = query.filter(relationship__in=["parent", "guardian"])
            if snapshot is not None:
                query = query.filter(pk__in=snapshot.get(key, []))
            if lock:
                query = query.select_for_update()
            result[key] = list(query.order_by("pk")[:101])
            if len(result[key]) > 100:
                raise ValidationError("These records need school review before account setup can continue.")
            if snapshot is not None and len(result[key]) != len(snapshot.get(key, [])):
                raise ValidationError("The school record has changed. Start account setup again.")
    records = [record for rows in result.values() for record in rows]
    if not records:
        raise ValidationError("No eligible school record matches this email and account type. Contact the school.")
    if kind != "parent" and len(records) != 1:
        raise ValidationError("Multiple school records match this email. Contact the school to resolve them.")
    if kind == "parent" and len({(r.first_name.strip().casefold(), r.last_name.strip().casefold()) for r in records}) > 1:
        raise ValidationError("The parent records need school review before account setup can continue.")
    owners = {r.user_account_id_number for r in records if getattr(r, "user_account_id_number", None)}
    account = User.objects.filter(email__iexact=email).first()
    if kind == "parent":
        validate_parent_identity_references(records, account)
        return result
    profile_ids = {r.parent_profile_id for r in records if getattr(r, "parent_profile_id", None)}
    if profile_ids and (not account or ParentProfile.objects.filter(pk__in=profile_ids).exclude(user=account).exists()):
        raise ValidationError("A guardian record belongs to another account. Contact the school.")
    if owners and (not account or owners != {account.id_number}):
        raise ValidationError("A school record is linked to another account. Contact the school.")
    return result


def begin_setup(tenant, kind, email):
    if not getattr(settings, "ACCOUNT_SETUP_EMAIL_ENABLED", True):
        raise ValidationError("Account setup email delivery is disabled in this environment. Contact your school.")
    email = email.strip().lower()
    if kind == "parent":
        require_parent_setup_eligible(email)
    records = source_records(tenant, kind, email)
    reserve_setup_email(email)
    code = f"{secrets.randbelow(1000000):06d}"
    challenge = AccountSetupChallenge.objects.create(tenant=tenant, email=email, account_type=kind,
        code_hash=make_password(code), source_ids={key: [str(r.pk) for r in rows] for key, rows in records.items()},
        expires_at=timezone.now()+timedelta(minutes=15))
    from common.email_service import send_notification_email
    sent = send_notification_email(SimpleNamespace(email=email, first_name="", pk=challenge.pk),
        "Your EzySchool account setup code", f"Your verification code is {code}. It expires in 15 minutes. Do not share this code.", school=tenant)
    if not sent:
        challenge.delete()
        raise ValidationError("The verification email could not be sent. Please try again later.")
    return challenge


def verify_setup(tenant, challenge_id, code):
    error = None
    with transaction.atomic():
        challenge = AccountSetupChallenge.objects.select_for_update().filter(pk=challenge_id, tenant=tenant).first()
        if not challenge or challenge.used_at or challenge.verified_at or challenge.expires_at <= timezone.now() or challenge.attempts >= 5:
            error = "This code is expired or unavailable. Start again."
        elif not check_password(code, challenge.code_hash):
            challenge.attempts += 1
            challenge.save(update_fields=["attempts"])
            error = "Incorrect verification code."
        else:
            records = source_records(tenant, challenge.account_type, challenge.email, snapshot=challenge.source_ids)
            record = next(r for rows in records.values() for r in rows)
            proof = secrets.token_urlsafe(32)
            challenge.proof_hash = token_hash(proof)
            challenge.verified_at = timezone.now()
            challenge.save(update_fields=["proof_hash", "verified_at"])
            details = setup_source_details(record, challenge.account_type)
    if error:
        raise ValidationError(error)
    return {"proof": proof, "details": details, "account_type": challenge.account_type,
            "email": challenge.email, "existing_account": User.objects.filter(email__iexact=challenge.email).exists()}


def record_email_proof(user):
    return VerifiedAccountEmail.objects.get_or_create(user=user, email=user.email.strip().lower())[0]


def has_email_proof(user):
    return VerifiedAccountEmail.objects.filter(user=user, email=user.email.strip().lower()).exists()


def activate_guardian(guardian, user, tenant):
    """Call only with verified email and a school-approved give_access flag."""
    if not guardian.give_access or (guardian.email or "").strip().lower() != user.email.strip().lower() or not has_email_proof(user):
        return False
    if not guardian.active or not guardian.student.active or guardian.student.status == "deleted":
        return False
    if guardian.portal_state in {"suspended", "disconnected"}:
        return False
    validate_parent_identity_references([guardian], user)
    profile, _ = ParentProfile.objects.get_or_create(user=user)
    guardian.parent_profile_id = profile.pk
    guardian.user_account_id_number = user.id_number
    guardian.email = user.email
    guardian.portal_state = "active"
    guardian.portal_verified_at = timezone.now()
    guardian.portal_ended_at = None
    guardian.save()
    audit_link(guardian, user, "email_verified_link")
    reconcile_parent(profile, tenant)
    return True


@transaction.atomic
def complete_setup(tenant, challenge_id, proof, details, password, actor=None):
    challenge = AccountSetupChallenge.objects.select_for_update().filter(pk=challenge_id, tenant=tenant).first()
    if not challenge or not challenge.verified_at or challenge.used_at or challenge.expires_at <= timezone.now() or not secrets.compare_digest(challenge.proof_hash, token_hash(proof)):
        raise ValidationError("Account setup has expired or was already completed. Start again.")
    if challenge.account_type == "parent" and details.get("terms_accepted") is not True:
        raise ValidationError({"terms_accepted": "Accept the Terms and Conditions to continue."})
    records = source_records(tenant, challenge.account_type, challenge.email, snapshot=challenge.source_ids, lock=True)
    source = next(r for rows in records.values() for r in rows)
    user = User.objects.select_for_update().filter(email__iexact=challenge.email).first()
    if user and (not actor or not actor.is_authenticated or actor.pk != user.pk) and not user.check_password(password):
        raise ValidationError("This email already has an account. Enter its current password to connect it.")
    if user and (not user.is_active or user.status != "active"):
        raise PermissionDenied("This account is unavailable. Contact the school.")
    if user:
        from authorization.models import TenantMembership, TenantRoleAssignment
        with schema_context(tenant.schema_name):
            membership = TenantMembership.objects.select_for_update().filter(user=user).first()
            if membership and (not membership.is_active or TenantRoleAssignment.objects.filter(
                    membership=membership, role_key=f"system:{challenge.account_type}", is_active=False).exists()):
                raise PermissionDenied("School access was withdrawn. Contact the school to restore it.")
    bio = {key: details[key] for key in PARENT_NAME_FIELDS if key in details} if challenge.account_type == "parent" else {key: getattr(source, key, None) for key in BIO_FIELDS}
    if challenge.account_type == "parent" and not bio.get("gender"):
        bio.pop("gender", None)
    if bio.get("date_of_birth") and bio["date_of_birth"] > timezone.localdate():
        raise ValidationError({"date_of_birth": "Date of birth cannot be in the future."})
    created = user is None
    if created:
        from common.utils import generate_entity_id_number, ID_ENTITY_PARENT, ID_ENTITY_EMPLOYEE, ID_ENTITY_STUDENT
        prefix = {"parent": ID_ENTITY_PARENT, "staff": ID_ENTITY_EMPLOYEE, "student": ID_ENTITY_STUDENT}[challenge.account_type]
        user = User(email=challenge.email, account_type=challenge.account_type,
                    id_number=generate_entity_id_number(User, prefix),
                    **{key: bio.get(key) or (None if key == "date_of_birth" else "") for key in ["first_name", "middle_name", "last_name", "gender", "date_of_birth"]})
        try:
            validate_password(password, user)
        except DjangoValidationError as exc:
            raise ValidationError({"password": exc.messages})
        user.set_password(password)
        user.save()
    record_email_proof(user)
    with schema_context(tenant.schema_name):
        if challenge.account_type == "parent":
            from students.models import StudentGuardian
            profile, _ = ParentProfile.objects.get_or_create(user=user)
            ParentSchoolRegistration.objects.get_or_create(profile=profile, tenant=tenant)
            for rows in records.values():
                for record in rows:
                    updated_fields = [key for key in PARENT_NAME_FIELDS if key in bio]
                    for key in updated_fields:
                        setattr(record, key, bio.get(key) or (None if key == "date_of_birth" else ""))
                    record.save(update_fields=updated_fields)
            for guardian in StudentGuardian.objects.select_for_update().filter(email__iexact=challenge.email, active=True, give_access=True):
                activate_guardian(guardian, user, tenant)
            reconcile_parent(profile, tenant)
        else:
            source.user_account_id_number = user.id_number
            source.save(update_fields=["user_account_id_number"])
            if not user.tenants.filter(pk=tenant.pk).exists():
                tenant.add_user(user, is_staff=False, is_superuser=False)
            from authorization.models import Role
            from authorization.multiple_roles import add_role
            role = Role.objects.filter(system_key=challenge.account_type, is_active=True).first()
            if not role:
                raise ValidationError("The school must configure the account's self-service role first.")
            add_role(user=user, role=role)
    challenge.used_at = timezone.now()
    if challenge.account_type == "parent":
        challenge.source_ids = {**challenge.source_ids, "terms_acceptance": {
            "accepted_at": challenge.used_at.isoformat(), "terms_version": "2025-05-01",
            "terms_path": "/terms", "user_id": str(user.pk),
        }}
    challenge.save(update_fields=["used_at", "source_ids"])
    return user, created


@transaction.atomic
def set_guardian_access(tenant, guardian, actor, enabled):
    from students.models import StudentGuardian
    from users.parent_portal import end_link
    guardian = StudentGuardian.objects.select_for_update().get(pk=guardian.pk)
    if not enabled:
        end_link(tenant=tenant, guardian_id=guardian.pk, actor=actor)
        return guardian
    from django.core.validators import validate_email
    try:
        validate_email(guardian.email or "")
    except DjangoValidationError:
        raise ValidationError("Add a valid guardian email before giving access.")
    if not school_available(tenant) or not guardian.active or not guardian.student.active or guardian.student.status == "deleted":
        raise ValidationError("This relationship is unavailable.")
    guardian.give_access = True
    guardian.portal_approved_at = timezone.now()
    guardian.portal_approved_by = actor.pk
    guardian.portal_ended_at = None
    guardian.portal_state = "unverified"
    guardian.save()
    audit_link(guardian, actor, "access_approved")
    user = User.objects.filter(email__iexact=guardian.email, is_active=True).first()
    if user:
        activate_guardian(guardian, user, tenant)
    return guardian
