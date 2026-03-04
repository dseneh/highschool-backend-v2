from django.db import models
from django.db.models import Case, DecimalField, Q, Sum, When

from common.models import BaseModel, BasePersonModel
from common.status import (
    AttendanceStatus,
    EnrollmentStatus,
    EnrollmentType,
    GradeStatus,
    StudentStatus,
)


class Student(BasePersonModel):
    prev_id_number = models.CharField(
        max_length=50, blank=True, null=True, default=None
    )
    # date_of_enrollment = models.DateField(blank=True, null=True, default=None)
    date_of_graduation = models.DateField(blank=True, null=True, default=None)
    entry_date = models.DateField(blank=True, null=True, default=None)
    grade_level = models.ForeignKey(
        "core.GradeLevel",
        on_delete=models.CASCADE,
        related_name="student_grade_level",
        blank=True,
        null=True,
        default=None,
    )
    user_account = models.OneToOneField(
        "users.user",
        on_delete=models.CASCADE,
        related_name="student_account",
        null=True,
        blank=True,
        default=None,
    )

    class Meta:
        verbose_name = "Student"
        verbose_name_plural = "Students"
        ordering = ["id_number", "last_name", "first_name"]
        indexes = [
            models.Index(fields=["id_number"]),
            models.Index(fields=["prev_id_number"]),
            models.Index(fields=["last_name"]),
        ]

    def save(self, *args, **kwargs):
        # save default image path if not provided
        if not self.photo:
            self.photo = f"images/default_{self.gender}.jpg"
        return super().save(*args, **kwargs)

    def is_enrolled(self, academic_year=None):
        """
        Check if the student is enrolled in the given academic year.
        If no academic year is provided, check for any active enrollment.
        """
        if not academic_year:
            from academics.models import AcademicYear

            academic_year = AcademicYear.objects.filter(current=True).first()
        return self.enrollments.filter(academic_year=academic_year).exists()
        # return self.enrollments.filter(status=EnrollmentStatus.ACTIVE).exists()

    # get balance due for the student for the current academic year
    @property
    def balance_due(self, academic_year_id=None):
        """
        Calculate the total balance due for the student in the current academic year.
        This considers only completed transactions.
        """
        return self.get_approved_balance(academic_year_id)

    def get_balance_before_approved(self, academic_year_id=None):
        """
        Calculate the balance considering pending transactions.
        This shows what the balance would be if pending payments were processed.
        """
        from academics.models import AcademicYear

        academic_year = AcademicYear.objects.filter(current=True).first()
        if academic_year_id:
            academic_year = AcademicYear.objects.filter(id=academic_year_id).first()

        if not academic_year:
            return 0

        enrollment = self.enrollments.filter(academic_year=academic_year).first()
        if not enrollment:
            return 0

        # Get total bills using aggregation
        total_bills = (
            enrollment.student_bills.aggregate(total=Sum("amount"))["total"] or 0
        )

        # Get pending payments using aggregation
        total_pending = (
            self.transactions.filter(
                academic_year=academic_year, status="pending"
            ).aggregate(total=Sum("amount"))["total"]
            or 0
        )

        return total_bills - total_pending

    def get_approved_balance(self, academic_year_id=None):
        """
        Calculate the balance after approved/completed transactions only.
        This shows the current actual balance.
        """
        from academics.models import AcademicYear

        academic_year = AcademicYear.objects.filter(current=True).first()
        if academic_year_id:
            academic_year = AcademicYear.objects.filter(id=academic_year_id).first()

        if not academic_year:
            return 0

        enrollment = self.enrollments.filter(academic_year=academic_year).first()
        if not enrollment:
            return 0

        # Get total bills using aggregation
        total_bills = (
            enrollment.student_bills.aggregate(total=Sum("amount"))["total"] or 0
        )

        # Get completed payments using aggregation
        total_completed = (
            self.transactions.filter(
                academic_year=academic_year, status="completed"
            ).aggregate(total=Sum("amount"))["total"]
            or 0
        )

        return total_bills - total_completed

    def get_balance_summary(self, academic_year_id=None):
        """
        Get a comprehensive balance summary for the student.
        Returns a dictionary with all balance information.
        Optimized with single query using conditional aggregation.
        """
        from academics.models import AcademicYear

        academic_year = AcademicYear.objects.filter(current=True).first()
        if academic_year_id:
            academic_year = AcademicYear.objects.filter(id=academic_year_id).first()

        if not academic_year:
            return {
                "total_bills": 0,
                "total_pending": 0,
                "total_completed": 0,
                "total_rejected": 0,
                "balance_before_approved": 0,
                "approved_balance": 0,
                "outstanding_balance": 0,
            }

        enrollment = self.enrollments.filter(academic_year=academic_year).first()
        if not enrollment:
            return {
                "total_bills": 0,
                "total_pending": 0,
                "total_completed": 0,
                "total_rejected": 0,
                "balance_before_approved": 0,
                "approved_balance": 0,
                "outstanding_balance": 0,
            }

        # Get total bills using aggregation
        total_bills = (
            enrollment.student_bills.aggregate(total=Sum("amount"))["total"] or 0
        )

        # Get all transaction totals in a single query using conditional aggregation
        transaction_summary = self.transactions.filter(
            academic_year=academic_year
        ).aggregate(
            total_pending=Sum(
                Case(
                    When(status="pending", then="amount"),
                    default=0,
                    output_field=DecimalField(max_digits=10, decimal_places=2),
                )
            ),
            total_completed=Sum(
                Case(
                    When(status="completed", then="amount"),
                    default=0,
                    output_field=DecimalField(max_digits=10, decimal_places=2),
                )
            ),
            total_rejected=Sum(
                Case(
                    When(status="rejected", then="amount"),
                    default=0,
                    output_field=DecimalField(max_digits=10, decimal_places=2),
                )
            ),
        )

        total_pending = transaction_summary["total_pending"] or 0
        total_completed = transaction_summary["total_completed"] or 0
        total_rejected = transaction_summary["total_rejected"] or 0

        # Calculate different balances
        balance_before_approved = total_bills - total_pending
        approved_balance = total_bills - total_completed
        outstanding_balance = total_bills - (total_completed + total_pending)

        return {
            "total_bills": float(total_bills),
            "total_pending": float(total_pending),
            "total_completed": float(total_completed),
            "total_rejected": float(total_rejected),
            "balance_before_approved": float(balance_before_approved),
            "approved_balance": float(approved_balance),
            "outstanding_balance": float(outstanding_balance),
        }


class Enrollment(BaseModel):
    student = models.ForeignKey(
        Student, on_delete=models.CASCADE, related_name="enrollments"
    )
    academic_year = models.ForeignKey(
        "academics.academicyear", on_delete=models.CASCADE, related_name="enrollments"
    )
    grade_level = models.ForeignKey(
        "core.GradeLevel", on_delete=models.CASCADE, related_name="enrollments"
    )
    section = models.ForeignKey(
        "core.Section", on_delete=models.CASCADE, related_name="enrollments"
    )
    date_enrolled = models.DateField(auto_now_add=True)
    notes = models.TextField(blank=True, null=True, default=None)
    status = models.CharField(
        max_length=20,
        choices=EnrollmentStatus.choices(),
        default=EnrollmentStatus.PENDING,
    )
    enrolled_as = models.CharField(
        max_length=20,
        choices=EnrollmentType.choices(),
        default=EnrollmentType.NEW,
    )

    def __str__(self):
        return f"{self.student.get_full_name()} - {self.section} ({self.academic_year})"


class Attendance(BaseModel):
    enrollment = models.ForeignKey(
        Enrollment, on_delete=models.CASCADE, related_name="attendance"
    )
    marking_period = models.ForeignKey(
        "academics.markingperiod", on_delete=models.CASCADE, related_name="attendance"
    )
    date = models.DateField()
    status = models.CharField(
        max_length=20,
        choices=AttendanceStatus.choices(),
        default=AttendanceStatus.PRESENT,
    )
    notes = models.TextField(blank=True, null=True, default=None)

    def __str__(self):
        return (
            f"{self.enrollment.student.get_full_name()} - {self.date} ({self.status})"
        )


# class EnrollmentSubject(BaseModel):
#     enrollment = models.ForeignKey(
#         Enrollment, on_delete=models.CASCADE, related_name="subjects"
#     )
#     subject = models.ForeignKey(
#         "core.Subject",
#         on_delete=models.CASCADE,
#         related_name="enrollment_subjects",
#     )


class GradeBook(BaseModel):
    enrollment = models.ForeignKey(
        Enrollment, on_delete=models.CASCADE, related_name="grade_books"
    )
    marking_period = models.ForeignKey(
        "academics.markingperiod", on_delete=models.CASCADE, related_name="grade_books"
    )  # Marking period
    subject = models.ForeignKey(
        "core.Subject", on_delete=models.CASCADE, related_name="grade_books"
    )
    prev_grade = models.DecimalField(
        max_digits=4, decimal_places=1, default=None, blank=True, null=True
    )
    grade = models.DecimalField(
        max_digits=4, decimal_places=1, default=None, blank=True, null=True
    )
    grade_letter = models.CharField(max_length=2, null=True, blank=True, default=None)
    grade_target = models.DecimalField(
        max_digits=4, decimal_places=1, default=100, blank=True, null=True
    )
    date_added = models.DateField(default=None, blank=True, null=True)
    notes = models.TextField(blank=True, null=True, default=None)
    status = models.CharField(
        max_length=20,
        choices=GradeStatus.choices(),
        default=GradeStatus.NONE,
        blank=True,
        null=True,
    )

    def __str__(self):
        return (
            f"{self.enrollment.student.get_full_name()} - {self.subject} ({self.grade})"
        )


class StudentEnrollmentBill(BaseModel):
    enrollment = models.ForeignKey(
        Enrollment, on_delete=models.CASCADE, related_name="student_bills"
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

    def __str__(self):
        return (
            f"{self.enrollment.student.get_full_name()} - {self.name} - {self.amount}"
        )
