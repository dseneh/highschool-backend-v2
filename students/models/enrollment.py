"""
Enrollment model for student academic year enrollments
"""
from .base import BaseModel, EnrollmentStatus, EnrollmentType, models


class Enrollment(BaseModel):
    student = models.ForeignKey(
        "students.Student", on_delete=models.CASCADE, related_name="enrollments"
    )
    academic_year = models.ForeignKey(
        "academics.academicyear", on_delete=models.CASCADE, related_name="enrollments"
    )
    grade_level = models.ForeignKey(
        "academics.GradeLevel", on_delete=models.CASCADE, related_name="enrollments"
    )
    next_grade_level = models.ForeignKey(
        "academics.GradeLevel",
        on_delete=models.CASCADE,
        related_name="next_enrollments",
        blank=True,
        null=True,
        default=None,
    )
    section = models.ForeignKey(
        "academics.Section", on_delete=models.CASCADE, related_name="enrollments"
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

    class Meta:
        db_table = 'enrollment'
        verbose_name = "Enrollment"
        verbose_name_plural = "Enrollments"
        unique_together = ["student", "academic_year"]
        indexes = [
            models.Index(fields=["student", "academic_year"]),
            models.Index(fields=["academic_year", "section"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self):
        return f"{self.student.get_full_name()} - {self.section} ({self.academic_year})"
