"""
Attendance model for tracking student attendance
"""
from .base import AttendanceStatus, BaseModel, models


class Attendance(BaseModel):
    enrollment = models.ForeignKey(
        "students.Enrollment", on_delete=models.CASCADE, related_name="attendance"
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

    class Meta:
        db_table = 'attendance'
        verbose_name = "Attendance"
        verbose_name_plural = "Attendance Records"
        unique_together = ["enrollment", "date"]
        indexes = [
            models.Index(fields=["enrollment", "date"]),
            models.Index(fields=["marking_period", "date"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self):
        return (
            f"{self.enrollment.student.get_full_name()} - {self.date} ({self.status})"
        )
