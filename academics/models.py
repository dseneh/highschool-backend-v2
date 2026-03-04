"""Academic structure models for the school management system.

All models are tenant-specific (live in tenant schemas).
"""

from django.db import models
from django.forms import ValidationError

from common.models import BaseModel

class AcademicYear(BaseModel):
    start_date = models.DateField()
    end_date = models.DateField()
    name = models.CharField(max_length=100, blank=True, null=True)
    current = models.BooleanField(default=False)
    status = models.CharField(
        max_length=20,
        choices=[("active", "Active"), ("inactive", "Inactive"), ("onhold", "On Hold")],
        default="active",
    )

    def __str__(self):
        return self.name

    class Meta:
        db_table = 'academic_year'
        verbose_name = "Academic Year"
        verbose_name_plural = "Academic Years"
        ordering = ["-start_date"]
        indexes = [
            models.Index(fields=["name", "start_date"]),
        ]

    @classmethod
    def get_current_academic_year(cls):
        """Get the current academic year for the school."""
        return cls.objects.filter(current=True).first()
    
    @classmethod
    def get_academic_year(cls, academic_year_id=None):
        """Get the academic year by id."""
        if not academic_year_id:
            return cls.get_current_academic_year()
        return cls.objects.filter(id=academic_year_id).first()


class Semester(BaseModel):
    academic_year = models.ForeignKey(
        AcademicYear,
        on_delete=models.CASCADE,
        related_name="semesters",
        null=True,
        blank=True,
        default=None,
    )
    name = models.CharField(max_length=100)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)

    def __str__(self):
        return self.name

    class Meta:
        db_table = 'semester'
        verbose_name = "Semester"
        verbose_name_plural = "Semesters"
        ordering = [
            "start_date",
        ]
        indexes = [
            models.Index(fields=["name", "start_date", "end_date"]),
        ]


class MarkingPeriod(BaseModel):
    """A model to represent the marking period within a semester.
    Example: First Marking Period, etc.
    """

    semester = models.ForeignKey(
        Semester, on_delete=models.CASCADE, related_name="marking_periods"
    )
    name = models.CharField(max_length=100)
    short_name = models.CharField(max_length=50, blank=True, null=True, default=None)
    description = models.TextField(blank=True, null=True, default=None)
    start_date = models.DateField()
    end_date = models.DateField()
    # current = models.BooleanField(default=False)

    def __str__(self):
        return self.name

    class Meta:
        db_table = 'marking_period'
        verbose_name = "Marking Period"
        verbose_name_plural = "Marking Periods"
        ordering = ["start_date"]
        indexes = [
            models.Index(fields=["semester", "name"]),
        ]


class Division(BaseModel):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True, default=None)

    def __str__(self):
        return self.name

    class Meta:
        db_table = 'division'
        verbose_name = "Division"
        verbose_name_plural = "Divisions"
        ordering = ["name"]
        indexes = [
            models.Index(fields=["name"]),
        ]


class GradeLevel(BaseModel):
    level = models.PositiveIntegerField(
        default=1, help_text="Grade level number (e.g., 1 for 1st grade)"
    )  # 1, 2, 3, etc.
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True, default=None)
    division = models.ForeignKey(
        Division, on_delete=models.CASCADE, related_name="grade_levels"
    )  # elementary, middle, high school
    max_class_capacity = models.PositiveIntegerField(
        default=30, help_text="Maximum number of students in a class"
    )
    # tuition_fee = models.DecimalField(
    #     max_digits=13, decimal_places=2,
    #     default=0.00,
    # )
    short_name = models.CharField(max_length=50, blank=True, null=True, default=None)

    def __str__(self):
        return self.name

    class Meta:
        db_table = 'grade_level'
        verbose_name = "Grade Level"
        verbose_name_plural = "Grade Levels"
        ordering = ["level"]
        indexes = [
            models.Index(fields=["name"]),
        ]


class GradeLevelTuitionFee(BaseModel):
    grade_level = models.ForeignKey(
        GradeLevel, on_delete=models.CASCADE, related_name="tuition_fees"
    )
    targeted_student_type = models.CharField(
        max_length=100, blank=True, null=True
    )  # target student type (e.g., new, old, transfer)
    amount = models.DecimalField(
        max_digits=13,
        decimal_places=2,
        default=0.00,
        help_text="Tuition fee for the grade level",
    )

    def __str__(self):
        return f"{self.grade_level.name} - {self.amount}"

    class Meta:
        db_table = 'grade_level_tuition_fee'
        ordering = ["grade_level"]


class Section(BaseModel):
    """Section of a grade level.
    Example: 1st grade A, 2nd grade, etc."""

    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True, default=None)
    grade_level = models.ForeignKey(
        GradeLevel, on_delete=models.CASCADE, related_name="sections"
    )  # 1st, 2nd, 3rd grade, etc.
    max_capacity = models.PositiveIntegerField(
        default=0, null=True, blank=True
    )  # inherite from grade level if not set
    tuition_fee = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        blank=True,
        null=True,
        default=None,
    )  # inherit from grade level if not set
    room_number = models.CharField(max_length=50, blank=True, null=True, default=None)

    def __str__(self):
        return self.name

    class Meta:
        db_table = 'section'
        ordering = ["name"]
        indexes = [
            models.Index(fields=["grade_level", "name"]),
        ]


class Subject(BaseModel):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True, default=None)

    def __str__(self):
        return self.name

    class Meta:
        db_table = 'subject'
        ordering = ["name"]


class SectionSubject(BaseModel):
    section = models.ForeignKey(
        Section, on_delete=models.CASCADE, related_name="section_subjects"
    )
    subject = models.ForeignKey(
        Subject, on_delete=models.CASCADE, related_name="section_subjects"
    )

    def __str__(self):
        return f"{self.section.name} - {self.subject.name}"

    class Meta:
        db_table = 'section_subject'
        ordering = ["-active", "subject__name"]


class Period(BaseModel):
    """A model to represent the period of a class.
    Example: 1st period, 2nd period, etc.
    """

    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True, default=None)

    def __str__(self):
        return self.name

    class Meta:
        db_table = 'period'


class PeriodTime(BaseModel):
    """A model to represent the time of a period.
    Example: 1st period from 8:00 AM to 9:00 AM, etc.
    """

    period = models.ForeignKey(
        Period, on_delete=models.CASCADE, related_name="period_times"
    )
    start_time = models.TimeField()
    end_time = models.TimeField()
    day_of_week = models.PositiveIntegerField(
        choices=[
            (1, "Monday"),
            (2, "Tuesday"),
            (3, "Wednesday"),
            (4, "Thursday"),
            (5, "Friday"),
            (6, "Saturday"),
            (7, "Sunday"),
        ]
    )

    def __str__(self):
        return f"{self.period.name} - {self.start_time} to {self.end_time}"

    class Meta:
        db_table = 'period_time'
        verbose_name = "Period Time"
        verbose_name_plural = "Period Times"
        ordering = ["start_time", "end_time"]
        indexes = [
            models.Index(fields=["period", "start_time"]),
        ]


class SectionSchedule(BaseModel):
    """A model to represent the schedule of a class."""

    section = models.ForeignKey(
        Section, on_delete=models.CASCADE, related_name="class_schedules"
    )
    subject = models.ForeignKey(
        SectionSubject, on_delete=models.CASCADE, related_name="class_schedules"
    )
    period_time = models.ForeignKey(
        PeriodTime, on_delete=models.CASCADE, related_name="class_schedules"
    )
    period = models.ForeignKey(
        Period, on_delete=models.CASCADE, related_name="class_schedules"
    )

    def clean(self):
        # Ensure the selected PeriodTime belongs to the selected Period
        if self.period_time.period != self.period:
            raise ValidationError(
                "The selected PeriodTime does not belong to the selected Period."
            )

    def __str__(self):
        return f"{self.section.name} - {self.subject.name} ({self.period.name})"

    class Meta:
        db_table = 'section_schedule'
