"""Recipient-only, in-app notices for school contact records; never grants access."""
from uuid import NAMESPACE_URL, uuid5
from django.db import connection, transaction
from django.utils import timezone
from django_tenants.utils import schema_context

EVENT = "student_contact_added"


def schedule_contact_notice(contact_id):
    schema = connection.schema_name
    if schema == "public":
        return
    transaction.on_commit(lambda: send_contact_notice(schema, contact_id), robust=True)


@transaction.atomic
def send_contact_notice(schema, contact_id):
    from core.models import Tenant
    from students.models import StudentContact, StudentGuardian
    from users.models import User
    from users.account_setup import has_email_proof
    from notifications.models import Notification, NotificationCampaign

    with schema_context(schema):
        contact = StudentContact.objects.select_for_update().filter(pk=contact_id, active=True).select_related("student").first()
        tenant = Tenant.objects.filter(schema_name=schema, active=True, status="active").first()
        if not contact or not tenant or not contact.student.active or contact.student.status == "deleted":
            return
        guardian = StudentGuardian.objects.filter(pk=contact.portal_guardian_id, student=contact.student).first() if contact.portal_guardian_id else None
        reference = guardian.user_account_id_number if guardian else None
        users = User.objects.filter(is_active=True, status="active")
        if reference:
            candidates = list(users.filter(id_number=reference)[:2])
        elif contact.email:
            candidates = list(users.filter(email__iexact=contact.email.strip())[:2])
        else:
            return
        if len(candidates) != 1:
            return
        user = candidates[0]
        kind = "parent" if contact.relationship == "parent" else "guardian" if guardian or contact.relationship == "guardian" else "contact"
        # An email match may receive a generic notice, never student details or access.
        student_text = f" for {contact.student.get_full_name()}" if reference or has_email_proof(user) else ""
        title = f"Added as a {kind}"
        campaign_id = uuid5(NAMESPACE_URL, f"ezy:{schema}:{EVENT}:{contact.pk}:{user.pk}")
        campaign, _ = NotificationCampaign.objects.get_or_create(pk=campaign_id, defaults={
            "title": title, "body": f"{tenant.name} added you as a {kind}{student_text}. This notification does not grant portal access. Contact the school if this is unexpected.",
            "category": "system", "source": "system", "channels": ["in_app"],
            "audience": {"scope": "user_ids", "user_ids": [str(user.pk)], "event": EVENT},
            "status": "sent", "sent_at": timezone.now(), "recipient_count": 1,
        })
        Notification.objects.get_or_create(campaign=campaign, recipient=user)
