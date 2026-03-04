"""
GradeBook model for student grades and academic performance
"""
from .base import BaseModel, GradeStatus, models


class GradeBook(BaseModel):
    enrollment = models.ForeignKey(
        "students.Enrollment", on_delete=models.CASCADE, related_name="grade_books"
    )
    marking_period = models.ForeignKey(
        "academics.markingperiod", on_delete=models.CASCADE, related_name="grade_books"
    )  # Marking period
    subject = models.ForeignKey(
        "academics.Subject", on_delete=models.CASCADE, related_name="grade_books"
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

    class Meta:
        db_table = 'student_grade_book'
        verbose_name = "Grade Book Entry"
        verbose_name_plural = "Grade Book Entries"
        unique_together = ["enrollment", "marking_period", "subject"]
        indexes = [
            models.Index(fields=["enrollment", "marking_period"]),
            models.Index(fields=["subject", "marking_period"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self):
        return (
            f"{self.enrollment.student.get_full_name()} - {self.subject} ({self.grade})"
        )
