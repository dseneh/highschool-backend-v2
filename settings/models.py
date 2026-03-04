"""
Settings Models

This module contains models for managing system-wide and school-specific settings.
Settings control various aspects of the system behavior.
"""

from django.db import models
from common.models import BaseModel


class GradingStyleChoices(models.TextChoices):
    """Grading style options"""

    SINGLE_ENTRY = "single_entry", "Single Entry (Final Grades Only)"
    MULTIPLE_ENTRY = "multiple_entry", "Multiple Entry (Assessments & Final Grades)"


class GradingSettings(BaseModel):
    """
    Settings for grading system behavior.

    Controls how grades are captured and managed:
    - Single Entry: Only final grades are captured (one assessment per gradebook/marking period)
    - Multiple Entry: Multiple assessments (quizzes, tests, etc.) with automatic calculation
    """

    grading_style = models.CharField(
        max_length=20,
        choices=GradingStyleChoices.choices,
        default=GradingStyleChoices.MULTIPLE_ENTRY,
        help_text="How grades are captured: single final grade or multiple assessments",
    )

    # Single Entry Settings
    single_entry_assessment_name = models.CharField(
        max_length=100,
        default="Final Grade",
        help_text="Name for the single assessment when using single entry mode",
    )

    # Multiple Entry Settings
    use_default_templates = models.BooleanField(
        default=True,
        help_text="Auto-generate assessments from default templates (multiple entry mode only)",
    )

    auto_calculate_final_grade = models.BooleanField(
        default=True, help_text="Automatically calculate final grades from assessments"
    )

    # Calculation Settings
    default_calculation_method = models.CharField(
        max_length=20,
        choices=[
            ("average", "Simple Average"),
            ("weighted", "Weighted Average"),
        ],
        default="average",
        help_text="Default calculation method for gradebooks",
    )

    # Approval Settings
    require_grade_approval = models.BooleanField(
        default=True, help_text="Require explicit approval before grades are finalized"
    )
    require_grade_review = models.BooleanField(
        default=True, help_text="Require explicit review before grades are finalized"
    )
    display_assessment_on_single_entry = models.BooleanField(
        default=True,
        help_text="Display assessment information on single entry grade views",
    )

    allow_assessment_delete = models.BooleanField(
        default=False, help_text="Allow deletion of assessments in multiple entry mode"
    )

    allow_assessment_create = models.BooleanField(
        default=False,
        help_text="Allow creation of new assessments in multiple entry mode",
    )

    allow_assessment_edit = models.BooleanField(
        default=False, help_text="Allow editing of assessments in multiple entry mode"
    )

    # Grade Letter Settings
    use_letter_grades = models.BooleanField(
        default=True, help_text="Display letter grades alongside percentages"
    )

    # Additional Options
    allow_teacher_override = models.BooleanField(
        default=True, help_text="Allow teachers to manually adjust calculated grades"
    )

    lock_grades_after_semester = models.BooleanField(
        default=False, help_text="Prevent grade modifications after semester ends"
    )

    display_grade_status = models.BooleanField(
        default=True, help_text="Display the status of grades (e.g., Draft, Finalized)"
    )

    cumulative_average_calculation = models.BooleanField(
        default=False,
        help_text="cumulative the points earned to calculate the grade average",
    )

    # Metadata
    notes = models.TextField(
        blank=True, null=True, help_text="Additional notes about grading configuration"
    )

    class Meta:
        db_table = 'grading_settings'
        verbose_name = "Grading Settings"
        verbose_name_plural = "Grading Settings"
        ordering = ["grading_style"]

    def __str__(self):
        return f"Grading Settings ({self.get_grading_style_display()})"

    def is_single_entry_mode(self):
        """Check if school uses single entry grading"""
        return self.grading_style == GradingStyleChoices.SINGLE_ENTRY

    def is_multiple_entry_mode(self):
        """Check if school uses multiple entry grading"""
        return self.grading_style == GradingStyleChoices.MULTIPLE_ENTRY

    def save(self, *args, **kwargs):
        """Override save to ensure consistency"""
        # If single entry mode, disable template usage
        if self.is_single_entry_mode():
            self.use_default_templates = False

        super().save(*args, **kwargs)
