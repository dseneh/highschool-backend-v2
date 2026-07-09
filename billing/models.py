import uuid

from django.db import models

from core.models import Tenant


class BillingSeat(models.Model):
    """
    One billable student seat for a tenant academic year (public schema).
    Decouples Stripe quantity from live enrollment rows.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="billing_seats",
    )
    student_id = models.UUIDField(null=True, blank=True)
    enrollment_id = models.UUIDField()
    academic_year_id = models.UUIDField()
    activated_at = models.DateTimeField()
    voided_at = models.DateTimeField(null=True, blank=True)
    void_reason = models.CharField(max_length=64, blank=True, default="")
    locked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "billing_seat"
        indexes = [
            models.Index(fields=["tenant", "academic_year_id", "voided_at"]),
            models.Index(fields=["tenant", "enrollment_id"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "enrollment_id", "academic_year_id"],
                name="billing_seat_unique_enrollment_year",
            ),
        ]

    @property
    def is_billable(self) -> bool:
        return self.voided_at is None
