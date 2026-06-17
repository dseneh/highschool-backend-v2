"""Historical / transferred transcript grade records."""

from __future__ import annotations

from typing import Optional

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from common.models import BaseModel


class HistoricalGradeRecord(BaseModel):
    """
    One year-end final grade from a student's transcript (prior school or transfer credit).
    Optional marking_period for mid-year transfer into a regular academic year only.
    """

    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        VERIFIED = "verified", _("Verified")

    student = models.ForeignKey(
        "students.Student",
        on_delete=models.CASCADE,
        related_name="historical_grade_records",
        db_index=True,
    )
    institution_name = models.CharField(max_length=255)
    academic_year = models.ForeignKey(
        "academics.AcademicYear",
        on_delete=models.PROTECT,
        related_name="historical_grade_records",
        blank=True,
        null=True,
        default=None,
    )
    academic_year_label = models.CharField(
        max_length=50,
        help_text='Display label, e.g. "2024-2025".',
    )
    period_start_date = models.DateField(blank=True, null=True, default=None)
    period_end_date = models.DateField(blank=True, null=True, default=None)
    grade_level = models.ForeignKey(
        "academics.GradeLevel",
        on_delete=models.PROTECT,
        related_name="historical_grade_records",
    )
    subject_name = models.CharField(max_length=255)
    subject = models.ForeignKey(
        "academics.Subject",
        on_delete=models.PROTECT,
        related_name="historical_grade_records",
    )
    marking_period = models.ForeignKey(
        "academics.MarkingPeriod",
        on_delete=models.SET_NULL,
        related_name="historical_grade_records",
        blank=True,
        null=True,
        default=None,
        help_text="Only for mid-year transfer credit on regular years.",
    )
    final_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        blank=True,
        null=True,
        default=None,
    )
    final_letter = models.CharField(max_length=10, blank=True, null=True, default=None)
    credits = models.DecimalField(
        max_digits=4,
        decimal_places=1,
        blank=True,
        null=True,
        default=None,
    )
    include_in_rankings = models.BooleanField(default=False)
    include_in_honor_roll = models.BooleanField(default=False)
    notes = models.TextField(blank=True, null=True, default=None)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )
    verified_by = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        related_name="verified_historical_grades",
        blank=True,
        null=True,
        default=None,
    )
    verified_at = models.DateTimeField(blank=True, null=True, default=None)

    class Meta:
        db_table = "historical_grade_record"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["student", "status"]),
            models.Index(fields=["academic_year"]),
            models.Index(fields=["grade_level", "subject"]),
            models.Index(fields=["period_end_date"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "student",
                    "institution_name",
                    "academic_year_label",
                    "grade_level",
                    "subject",
                ],
                condition=models.Q(marking_period__isnull=True),
                name="unique_historical_grade_full_year",
            ),
            models.UniqueConstraint(
                fields=[
                    "student",
                    "institution_name",
                    "academic_year_label",
                    "grade_level",
                    "subject",
                    "marking_period",
                ],
                condition=models.Q(marking_period__isnull=False),
                name="unique_historical_grade_with_period",
            ),
        ]

    def __str__(self):
        period = f" · {self.marking_period}" if self.marking_period_id else ""
        return (
            f"{self.student_id} · {self.institution_name} · "
            f"{self.subject_name}{period} ({self.final_percentage}%)"
        )

    @property
    def source(self) -> str:
        return "transferred"

    @property
    def include_in_calculations(self) -> bool:
        return self.include_in_rankings or self.include_in_honor_roll

    @property
    def counts_toward_year(self) -> bool:
        if self.academic_year_id:
            return self.academic_year.is_regular
        return False

    def resolve_academic_year(self) -> Optional["AcademicYear"]:
        if self.academic_year_id:
            return self.academic_year
        from students.services.historical_academic_year import resolve_academic_year_for_historical_grade

        return resolve_academic_year_for_historical_grade(
            year_label=self.academic_year_label,
            create_historical_if_missing=False,
        )

    def clean(self):
        super().clean()
        if self.final_percentage is not None:
            if self.final_percentage < 0 or self.final_percentage > 100:
                raise ValidationError(
                    {"final_percentage": "Percentage must be between 0 and 100."}
                )

    def save(self, *args, **kwargs):
        if not self.subject_name and self.subject_id:
            self.subject_name = self.subject.name
        if self.final_percentage is not None and not self.final_letter:
            from grading.models import GradeLetter

            self.final_letter = GradeLetter.get_letter_for_percentage(self.final_percentage)
        if not self.academic_year_id and self.academic_year_label:
            from students.services.historical_academic_year import (
                resolve_academic_year_for_historical_grade,
            )

            resolved = resolve_academic_year_for_historical_grade(
                year_label=self.academic_year_label,
                create_historical_if_missing=True,
            )
            if resolved:
                self.academic_year = resolved
                if not self.academic_year_label:
                    self.academic_year_label = resolved.name or self.academic_year_label
        super().save(*args, **kwargs)
