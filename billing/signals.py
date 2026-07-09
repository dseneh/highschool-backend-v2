from __future__ import annotations

from django.db import connection
from django.db.models.signals import post_save, pre_delete
from django.dispatch import receiver
from django.utils import timezone
from django_tenants.utils import get_public_schema_name

from billing.services.seats import create_billing_seat, void_billing_seat_if_within_grace
from common.status import EnrollmentStatus


def _tenant_for_current_schema():
    from core.models import Tenant

    schema = connection.schema_name
    if not schema or schema == get_public_schema_name():
        return None
    return Tenant.objects.filter(schema_name=schema).first()


def connect_enrollment_signals():
    from students.models.enrollment import Enrollment

    post_save.connect(enrollment_saved_billing_seat, sender=Enrollment, dispatch_uid="billing_enrollment_save")
    pre_delete.connect(enrollment_deleted_billing_seat, sender=Enrollment, dispatch_uid="billing_enrollment_delete")


def enrollment_saved_billing_seat(sender, instance, **kwargs):
    if (instance.status or "").lower() != EnrollmentStatus.ENROLLED:
        return
    tenant = _tenant_for_current_schema()
    if not tenant:
        return
    create_billing_seat(
        tenant,
        enrollment_id=instance.id,
        student_id=instance.student_id,
        academic_year_id=instance.academic_year_id,
        activated_at=timezone.now(),
    )


def enrollment_deleted_billing_seat(sender, instance, **kwargs):
    tenant = _tenant_for_current_schema()
    if not tenant:
        return
    void_billing_seat_if_within_grace(
        tenant,
        enrollment_id=instance.id,
        academic_year_id=instance.academic_year_id,
        reason="enrollment_deleted",
    )
