"""Global setup reuses email challenges and school lifecycle after email proof."""
import secrets
from datetime import timedelta
from types import SimpleNamespace
from django.conf import settings
from django.contrib.auth.hashers import make_password, check_password
from django.db import transaction
from django.utils import timezone
from django_tenants.utils import schema_context
from rest_framework.exceptions import ValidationError
from users.models import AccountSetupChallenge, User
from users.account_setup import source_records, complete_setup, setup_source_details, require_parent_setup_eligible, reserve_setup_email
from users.parent_portal import token_hash


def begin(tenant, kind, email):
    if kind != "parent":
        raise ValidationError("Use your school login to set up an employee or student account.")
    if not getattr(settings, "ACCOUNT_SETUP_EMAIL_ENABLED", True):
        raise ValidationError("Account setup email delivery is disabled in this environment.")
    email = email.strip().lower()
    require_parent_setup_eligible(email)
    discover(email)
    reserve_setup_email(email)
    code = f"{secrets.randbelow(1000000):06d}"
    challenge = AccountSetupChallenge.objects.create(tenant=tenant, email=email, account_type="parent", code_hash=make_password(code), source_ids={"global_parent": True}, expires_at=timezone.now()+timedelta(minutes=15))
    from common.email_service import send_notification_email
    if not send_notification_email(SimpleNamespace(email=email, first_name="", pk=challenge.pk), "Your EzySchool account setup code", f"Your verification code is {code}. It expires in 15 minutes. Do not share this code.", school=tenant):
        challenge.delete()
        raise ValidationError("The verification email could not be sent.")
    return challenge


def discover(email):
    from core.models import Tenant
    from students.models import StudentGuardian, StudentContact
    schools, records = {}, []
    for tenant in Tenant.objects.filter(active=True, status="active", maintenance_mode=False, restoration_in_progress=False).exclude(schema_name="public"):
        with schema_context(tenant.schema_name):
            if not (StudentGuardian.objects.filter(email__iexact=email, active=True, student__active=True).exists() or StudentContact.objects.filter(email__iexact=email, active=True, relationship__in=["parent", "guardian"], student__active=True).exists()):
                continue
            found = source_records(tenant, "parent", email)
            schools[tenant.schema_name] = {key: [str(row.pk) for row in rows] for key, rows in found.items()}
            records.extend(row for rows in found.values() for row in rows)
    if not records:
        raise ValidationError("No eligible parent or guardian record was found. Contact your school.")
    if len({(r.first_name.strip().casefold(), r.last_name.strip().casefold()) for r in records}) != 1:
        raise ValidationError("Your school records need review before account setup can continue.")
    return schools, records[0]


def verify(tenant, challenge_id, code):
    error = None
    with transaction.atomic():
        challenge = AccountSetupChallenge.objects.select_for_update().filter(pk=challenge_id, tenant=tenant).first()
        if not challenge or not challenge.source_ids.get("global_parent") or challenge.used_at or challenge.verified_at or challenge.expires_at <= timezone.now() or challenge.attempts >= 5:
            error = "This code is expired or unavailable. Start again."
        elif not check_password(code, challenge.code_hash):
            challenge.attempts += 1
            challenge.save(update_fields=["attempts"])
            error = "Incorrect verification code."
        else:
            schools, source = discover(challenge.email)
            proof = secrets.token_urlsafe(32)
            challenge.source_ids = {"global_parent": True, "schools": schools}
            challenge.verified_at = timezone.now()
            challenge.proof_hash = token_hash(proof)
            challenge.save(update_fields=["source_ids", "verified_at", "proof_hash"])
    if error:
        raise ValidationError(error)
    return {"proof": proof, "details": setup_source_details(source, "parent"), "account_type": "parent", "email": challenge.email, "existing_account": User.objects.filter(email__iexact=challenge.email).exists()}


@transaction.atomic
def complete(tenant, challenge_id, proof, details, password, actor=None):
    from core.models import Tenant
    challenge = AccountSetupChallenge.objects.select_for_update().filter(pk=challenge_id, tenant=tenant).first()
    if not challenge or not challenge.verified_at or challenge.used_at or challenge.expires_at <= timezone.now() or not secrets.compare_digest(challenge.proof_hash, token_hash(proof)):
        raise ValidationError("Account setup has expired or was already completed.")
    schools = challenge.source_ids.get("schools", {})
    if not schools:
        raise ValidationError("Verify your parent records first.")
    created = False
    for schema, snapshot in schools.items():
        school = Tenant.objects.get(schema_name=schema)
        child = AccountSetupChallenge.objects.create(tenant=school, email=challenge.email, account_type="parent", code_hash=challenge.code_hash, proof_hash=challenge.proof_hash, verified_at=challenge.verified_at, expires_at=challenge.expires_at, source_ids=snapshot)
        user, was_created = complete_setup(school, child.pk, proof, details, password, actor)
        created = created or was_created
        actor = user
    challenge.used_at = timezone.now()
    challenge.save(update_fields=["used_at"])
    return user, created
