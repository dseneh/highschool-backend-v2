"""School-admin initiated account creation and explicit staff identity linking."""
from uuid import uuid4

from django.db import transaction
from django_tenants.utils import get_public_schema_name, schema_context
from rest_framework.exceptions import ValidationError

from authorization.models import TenantMembership
from authorization.services import assign_user_role
from common.email_validation import require_valid_email
from common.status import UserAccountType
from users.models import User
from users.serializers import UserCreateSerializer


def resolve_existing_account(record, email, account_type):
    """Called only by authorized provisioning, never public email discovery."""
    reference = getattr(record, "user_account_id_number", None)
    linked = User.objects.select_for_update().filter(id_number=reference).first() if reference else None
    matches = list(User.objects.select_for_update().filter(email__iexact=email)[:2])
    if len(matches) > 1:
        raise ValidationError({"email": "Multiple accounts use this email. Contact the platform administrator."})
    matching = matches[0] if matches else None
    if linked and (linked.email or "").strip().casefold() != email.casefold():
        raise ValidationError({"email": "This school record is linked to a different account. Correct the identity link before generating access."})
    if linked and matching and linked.pk != matching.pk:
        raise ValidationError({"email": "The account reference and email identify different users."})
    # Staff email matching is an explicit school-admin linking action. Student
    # email may belong to a parent, so it cannot automatically establish a link.
    if account_type != UserAccountType.STAFF and matching and not linked and matching.id_number != record.id_number:
        raise ValidationError({"email": "This email belongs to an existing account. Verify the student's account link before continuing."})
    user = linked or matching
    if user and (not user.is_active or user.status != "active"):
        raise ValidationError({"email": "This account is disabled. An authorized administrator must restore it before linking school access."})
    return user


@transaction.atomic
def provision_source_account(*, source_record, account_type, role, tenant, actor, username=None):
    # Lock and re-read so email/link edits cannot race against provisioning.
    source = type(source_record).objects.select_for_update().get(pk=source_record.pk)
    try:
        email = require_valid_email(source.email).lower()
    except ValueError as exc:
        raise ValidationError({"email": str(exc)})
    with schema_context(get_public_schema_name()):
        user = resolve_existing_account(source, email, account_type)
        created = user is None
        if created:
            # School IDs can repeat across schools; they are not identity keys.
            account_number = source.id_number
            if User.objects.filter(id_number=account_number).exists():
                account_number = f"U-{uuid4().hex}"
            base = username or str(account_number)
            candidate = base
            suffix = 1
            if not username:
                while User.objects.filter(username=candidate).exists():
                    candidate = f"{base}_{suffix}"
                    suffix += 1
            serializer = UserCreateSerializer(data={
                "username": candidate, "id_number": account_number, "email": email,
                "first_name": source.first_name, "last_name": source.last_name,
                "gender": source.gender or "male", "account_type": account_type,
                "is_active": True,
            })
            serializer.is_valid(raise_exception=True)
            user = serializer.save()
        if not tenant.user_set.filter(pk=user.pk).exists():
            tenant.add_user(user, is_staff=account_type == UserAccountType.STAFF, is_superuser=False)
    with schema_context(tenant.schema_name):
        if TenantMembership.objects.filter(user=user, is_active=False).exists():
            raise ValidationError({"detail": "School access for this account is disabled. Restore its membership explicitly before assigning a role."})
        assign_user_role(user=user, role=role, actor=actor)
        source.user_account_id_number = user.id_number
        source.email = user.email
        source.save(update_fields=["user_account_id_number", "email"])
    return user, created
