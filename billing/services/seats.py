from __future__ import annotations

from django.conf import settings
from django.utils import timezone

from billing.models import BillingSeat


def billable_seat_count(tenant, academic_year_id) -> int:
    return BillingSeat.objects.filter(
        tenant=tenant,
        academic_year_id=academic_year_id,
        voided_at__isnull=True,
    ).count()


def create_billing_seat(
    tenant,
    *,
    enrollment_id,
    student_id,
    academic_year_id,
    activated_at=None,
) -> BillingSeat:
    activated_at = activated_at or timezone.now()
    seat, created = BillingSeat.objects.get_or_create(
        tenant=tenant,
        enrollment_id=enrollment_id,
        academic_year_id=academic_year_id,
        defaults={
            "student_id": student_id,
            "activated_at": activated_at,
        },
    )
    if not created and seat.voided_at:
        seat.voided_at = None
        seat.void_reason = ""
        seat.student_id = student_id
        seat.activated_at = activated_at
        seat.save(
            update_fields=["voided_at", "void_reason", "student_id", "activated_at", "updated_at"]
        )
    return seat


def void_billing_seat_if_within_grace(tenant, enrollment_id, academic_year_id, reason: str = "mistake") -> bool:
    seat = BillingSeat.objects.filter(
        tenant=tenant,
        enrollment_id=enrollment_id,
        academic_year_id=academic_year_id,
        voided_at__isnull=True,
    ).first()
    if not seat:
        return False

    grace_days = settings.BILLING_SEAT_VOID_GRACE_DAYS
    if (timezone.now() - seat.activated_at).days <= grace_days:
        seat.voided_at = timezone.now()
        seat.void_reason = reason
        seat.save(update_fields=["voided_at", "void_reason", "updated_at"])
        return True

    if not seat.locked_at:
        seat.locked_at = timezone.now()
        seat.save(update_fields=["locked_at", "updated_at"])
    return False
