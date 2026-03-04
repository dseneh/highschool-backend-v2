"""
Student billing and financial models
"""
from decimal import Decimal

from .base import BaseModel, models


class StudentEnrollmentBill(BaseModel):
    enrollment = models.ForeignKey(
        "students.Enrollment", on_delete=models.CASCADE, related_name="student_bills"
    )
    name = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    type = models.CharField(
        max_length=20,
        choices=[
            ("tuition", "Tuition"),
            ("fee", "Fee"),
            ("other", "Other"),
        ],
    )
    notes = models.TextField(blank=True, null=True, default=None)

    class Meta:
        db_table = 'enrollment_bill'
        verbose_name = "Student Bill"
        verbose_name_plural = "Student Bills"
        indexes = [
            models.Index(fields=["enrollment", "type"]),
            models.Index(fields=["type"]),
        ]

    def __str__(self):
        return (
            f"{self.enrollment.student.get_full_name()} - {self.name} - {self.amount}"
        )


class StudentConcession(BaseModel):
    """Represents a concession (discount) applied to a student for an academic year."""

    TYPE_PERCENTAGE = "percentage"
    TYPE_FLAT = "flat"
    TYPE_CHOICES = [
        (TYPE_PERCENTAGE, "Percentage"),
        (TYPE_FLAT, "Flat Value"),
    ]

    TARGET_TOTAL = "entire_bill"
    TARGET_TUITION = "tuition"
    TARGET_OTHER_FEES = "other_fees"
    TARGET_CHOICES = [
        (TARGET_TOTAL, "Entire Bill"),
        (TARGET_TUITION, "Tuition Only"),
        (TARGET_OTHER_FEES, "Other Fees Only"),
    ]

    student = models.ForeignKey(
        "students.Student",
        on_delete=models.CASCADE,
        related_name="concessions",
    )
    academic_year = models.ForeignKey(
        "academics.AcademicYear",
        on_delete=models.CASCADE,
        related_name="student_concessions",
    )
    concession_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    target = models.CharField(max_length=20, choices=TARGET_CHOICES, default=TARGET_TOTAL)
    value = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Percentage value (e.g. 10 for 10%) or flat amount depending on concession_type",
    )
    amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text="Computed total concession amount based on target and value",
    )
    notes = models.TextField(blank=True, null=True, default=None)
    active = models.BooleanField(default=True)

    class Meta:
        db_table = "student_concession"
        verbose_name = "Student Concession"
        verbose_name_plural = "Student Concessions"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["student", "academic_year", "active"]),
            models.Index(fields=["academic_year", "active"]),
        ]

    def __str__(self):
        return (
            f"{self.student.get_full_name()} - {self.academic_year.name} - "
            f"{self.get_concession_type_display()} ({self.get_target_display()})"
        )

    def _get_enrollment(self):
        return self.student.enrollments.filter(academic_year=self.academic_year).first()

    def _get_base_amounts(self):
        enrollment = self._get_enrollment()
        if not enrollment:
            return Decimal("0"), Decimal("0"), Decimal("0")

        tuition = Decimal("0")
        other_fees = Decimal("0")

        for bill in enrollment.student_bills.all():
            amount = Decimal(str(bill.amount or 0))
            if str(bill.type).lower() == "tuition":
                tuition += amount
            else:
                other_fees += amount

        total_bill = tuition + other_fees
        return tuition, other_fees, total_bill

    def calculate_amount(self):
        tuition, other_fees, total_bill = self._get_base_amounts()

        if self.target == self.TARGET_TUITION:
            base_amount = tuition
        elif self.target == self.TARGET_OTHER_FEES:
            base_amount = other_fees
        else:
            base_amount = total_bill

        if base_amount <= 0:
            return Decimal("0")

        value = Decimal(str(self.value or 0))
        if value <= 0:
            return Decimal("0")

        if self.concession_type == self.TYPE_PERCENTAGE:
            amount = (base_amount * value) / Decimal("100")
        else:
            amount = value

        if amount > base_amount:
            amount = base_amount

        return amount.quantize(Decimal("0.01"))

    def save(self, *args, **kwargs):
        self.amount = self.calculate_amount()
        super().save(*args, **kwargs)


def calculate_concessions_for_enrollment(enrollment):
    """Return detailed concession breakdown for an enrollment."""
    concessions = StudentConcession.objects.filter(
        student=enrollment.student,
        academic_year=enrollment.academic_year,
        active=True,
    ).order_by("created_at")

    concession_items = []
    total_concession = Decimal("0")
    tuition_concession = Decimal("0")
    other_fees_concession = Decimal("0")

    for concession in concessions:
        amount = concession.calculate_amount()

        concession_items.append(
            {
                "id": str(concession.id),
                "concession_type": concession.concession_type,
                "target": concession.target,
                "value": float(concession.value),
                "amount": float(amount),
                "notes": concession.notes,
                "active": concession.active,
            }
        )

        total_concession += amount
        if concession.target == StudentConcession.TARGET_TUITION:
            tuition_concession += amount
        elif concession.target == StudentConcession.TARGET_OTHER_FEES:
            other_fees_concession += amount
        else:
            tuition_concession += amount
            other_fees_concession += Decimal("0")

    return {
        "items": concession_items,
        "total_concession": total_concession,
        "tuition_concession": tuition_concession,
        "other_fees_concession": other_fees_concession,
    }
