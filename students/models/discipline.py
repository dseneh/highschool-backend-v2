from django.db import models
from django.utils import timezone
from datetime import timedelta

from .base import BaseModel


class DisciplinaryActionType(BaseModel):
    class Category(models.TextChoices):
        INFORMAL = "informal", "Informal"
        CORRECTIVE = "corrective", "Corrective"
        RESTRICTIVE = "restrictive", "Restrictive"
        ACADEMIC = "academic", "Academic"
        SUPPORTIVE = "supportive", "Supportive"
        SUSPENSION = "suspension", "Suspension"
        PLACEMENT = "placement", "Placement"
        SEVERE = "severe", "Severe"
        ADMINISTRATIVE = "administrative", "Administrative"

    class ActionOutcome(models.TextChoices):
        NO_ACTION = "no_action", "No Action"
        WARNING = "warning", "Warning"
        DETENTION = "detention", "Detention"
        SUSPENSION = "suspension", "Suspension"
        EXPULSION = "expulsion", "Expulsion"
        PROBATION = "probation", "Probation"
        COUNSELING = "counseling", "Counseling"
        WITHDRAWAL = "withdrawal", "Withdrawal"

    name = models.CharField(max_length=255)
    code = models.SlugField(max_length=120, unique=True)
    category = models.CharField(max_length=30, choices=Category.choices)
    action_outcome = models.CharField(
        max_length=24,
        choices=ActionOutcome.choices,
        default=ActionOutcome.WARNING,
    )
    description = models.TextField(blank=True, null=True, default=None)
    requires_start_date = models.BooleanField(default=True)
    requires_end_date = models.BooleanField(default=False)
    requires_parent_notification = models.BooleanField(default=False)
    requires_approval = models.BooleanField(default=False)
    default_duration_days = models.PositiveSmallIntegerField(default=1)
    max_duration_days = models.PositiveSmallIntegerField(default=30)
    default_severity = models.PositiveSmallIntegerField(default=1)
    allow_manual_override = models.BooleanField(default=True)

    class Meta:
        db_table = "disciplinary_action_type"
        verbose_name = "Disciplinary Action Type"
        verbose_name_plural = "Disciplinary Action Types"
        ordering = ["category", "name"]
        indexes = [
            models.Index(fields=["category"]),
            models.Index(fields=["code"]),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()

        duration_required_outcomes = {
            self.ActionOutcome.DETENTION,
            self.ActionOutcome.SUSPENSION,
            self.ActionOutcome.EXPULSION,
            self.ActionOutcome.PROBATION,
        }

        if self.default_duration_days < 1:
            self.default_duration_days = 1
        if self.max_duration_days < self.default_duration_days:
            self.max_duration_days = self.default_duration_days

        if self.action_outcome not in duration_required_outcomes:
            # Non time-bound outcomes default to same-day record windows.
            self.default_duration_days = 1
            self.max_duration_days = 1

        if self.default_severity < 1:
            self.default_severity = 1
        if self.default_severity > 5:
            self.default_severity = 5


class StudentDisciplinaryAction(BaseModel):
    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        INACTIVE = "inactive", "Inactive"

    class Severity(models.IntegerChoices):
        MINOR = 1, "Minor"
        MODERATE = 2, "Moderate"
        SERIOUS = 3, "Serious"
        SEVERE = 4, "Severe"
        CRITICAL = 5, "Critical"

    student = models.ForeignKey(
        "students.Student",
        on_delete=models.CASCADE,
        related_name="disciplinary_actions",
    )
    action_type = models.ForeignKey(
        "students.DisciplinaryActionType",
        on_delete=models.SET_NULL,
        related_name="student_actions",
        blank=True,
        null=True,
        default=None,
    )
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True, default=None)
    action_taken = models.TextField()
    start_date = models.DateField()
    end_date = models.DateField()
    duration_days = models.PositiveSmallIntegerField(blank=True, null=True, default=None)
    severity = models.PositiveSmallIntegerField(
        choices=Severity.choices,
        default=Severity.MINOR,
    )
    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.ACTIVE,
    )

    class Meta:
        db_table = "student_disciplinary_action"
        verbose_name = "Student Disciplinary Action"
        verbose_name_plural = "Student Disciplinary Actions"
        ordering = ["-start_date", "-created_at"]
        indexes = [
            models.Index(fields=["student", "start_date"]),
            models.Index(fields=["start_date", "end_date"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self):
        return f"{self.student.get_full_name()} - {self.title}"

    def clean(self):
        super().clean()
        if self.start_date and self.duration_days and not self.end_date:
            self.end_date = self.start_date + timedelta(days=self.duration_days - 1)

        if self.end_date and self.start_date and self.end_date < self.start_date:
            from django.core.exceptions import ValidationError

            raise ValidationError({"end_date": "End date cannot be earlier than start date."})

        if self.start_date and self.end_date and not self.duration_days:
            self.duration_days = (self.end_date - self.start_date).days + 1

    @property
    def is_active_window(self) -> bool:
        today = timezone.localdate()
        return (
            self.active
            and self.status == self.Status.ACTIVE
            and self.start_date <= today <= self.end_date
        )
