"""Academic structure models for the school management system.

All models are tenant-specific (live in tenant schemas).
"""

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

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


class SchoolCalendarSettings(BaseModel):
    """Tenant-scoped calendar configuration for operating weekdays and timezone."""

    DAY_OF_WEEK_CHOICES = [
        (1, "Monday"),
        (2, "Tuesday"),
        (3, "Wednesday"),
        (4, "Thursday"),
        (5, "Friday"),
        (6, "Saturday"),
        (7, "Sunday"),
    ]

    operating_days = models.JSONField(default=list)
    timezone = models.CharField(max_length=100, default="UTC")

    def clean(self):
        days = self.operating_days or [1, 2, 3, 4, 5]
        if not isinstance(days, list):
            raise ValidationError({"operating_days": "Operating days must be a list of weekday numbers."})

        invalid_days = [day for day in days if not isinstance(day, int) or day < 1 or day > 7]
        if invalid_days:
            raise ValidationError({"operating_days": "Operating days must contain weekday numbers between 1 and 7."})

        if len(days) != len(set(days)):
            raise ValidationError({"operating_days": "Operating days cannot contain duplicates."})

        self.operating_days = sorted(days)

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(defaults={"operating_days": [1, 2, 3, 4, 5]})
        return obj

    def __str__(self):
        return "School Calendar Settings"

    class Meta:
        db_table = "calendar_settings"
        verbose_name = "School Calendar Settings"
        verbose_name_plural = "School Calendar Settings"


class SchoolCalendarEvent(BaseModel):
    """Date-based school calendar event such as holidays or special days."""

    class EventType(models.TextChoices):
        HOLIDAY = "holiday", "Holiday"
        NON_SCHOOL_DAY = "non_school_day", "Non-school Day"
        SPECIAL_DAY = "special_day", "Special Day"
        SCHEDULE_OVERRIDE = "schedule_override", "Schedule Override"

    class RecurrenceType(models.TextChoices):
        NONE = "none", "None"
        YEARLY = "yearly", "Yearly"

    name = models.CharField(max_length=150)
    description = models.TextField(blank=True, null=True, default=None)
    event_type = models.CharField(
        max_length=30,
        choices=EventType.choices,
        default=EventType.HOLIDAY,
    )
    recurrence_type = models.CharField(
        max_length=20,
        choices=RecurrenceType.choices,
        default=RecurrenceType.NONE,
    )
    start_date = models.DateField()
    end_date = models.DateField()
    all_day = models.BooleanField(default=True)
    applies_to_all_sections = models.BooleanField(default=True)
    sections = models.ManyToManyField(
        "Section",
        blank=True,
        related_name="calendar_events",
        db_table="calendar_event_sections",
    )

    OCCURRENCE_YEAR_PAST = 1
    OCCURRENCE_YEAR_FUTURE = 5

    def clean(self):
        if self.start_date > self.end_date:
            raise ValidationError({"end_date": "End date must be on or after start date."})

        if self.recurrence_type == self.RecurrenceType.YEARLY and self.start_date.year != self.end_date.year:
            raise ValidationError(
                {"end_date": "Yearly recurring events must start and end within the same calendar year."}
            )

        if self.applies_to_all_sections and self.pk and self.sections.exists():
            raise ValidationError(
                {"sections": "Section-specific assignments must be empty when event applies to all sections."}
            )

    def occurs_in_range(self, range_start, range_end):
        if self.recurrence_type == self.RecurrenceType.NONE:
            return self.start_date <= range_end and self.end_date >= range_start

        duration_days = (self.end_date - self.start_date).days
        for year in range(range_start.year - 1, range_end.year + 2):
            occurrence_start = self.start_date.replace(year=year)
            occurrence_end = occurrence_start + timedelta(days=duration_days)
            if occurrence_start <= range_end and occurrence_end >= range_start:
                return True
        return False

    def _normalize_occurrence_start(self, year):
        try:
            return self.start_date.replace(year=year)
        except ValueError:
            if self.start_date.month == 2 and self.start_date.day == 29:
                return self.start_date.replace(year=year, day=28)
            raise

    def _iter_occurrence_dates(self):
        if self.recurrence_type == self.RecurrenceType.NONE:
            current = self.start_date
            while current <= self.end_date:
                yield current
                current += timedelta(days=1)
            return

        duration_days = (self.end_date - self.start_date).days
        current_year = timezone.now().date().year
        start_year = current_year - self.OCCURRENCE_YEAR_PAST
        end_year = current_year + self.OCCURRENCE_YEAR_FUTURE

        for year in range(start_year, end_year + 1):
            occurrence_start = self._normalize_occurrence_start(year)
            occurrence_end = occurrence_start + timedelta(days=duration_days)
            current = occurrence_start
            while current <= occurrence_end:
                yield current
                current += timedelta(days=1)

    def rebuild_occurrences(self):
        if not self.pk:
            return

        SchoolCalendarEventOccurrence.objects.filter(event=self).delete()
        occurrence_rows = [
            SchoolCalendarEventOccurrence(event=self, occurrence_date=occurrence_date)
            for occurrence_date in self._iter_occurrence_dates()
        ]
        SchoolCalendarEventOccurrence.objects.bulk_create(occurrence_rows, ignore_conflicts=True)

    def __str__(self):
        return self.name

    class Meta:
        db_table = "calendar_event"
        ordering = ["start_date", "name"]
        indexes = [
            models.Index(fields=["event_type", "start_date", "end_date"]),
            models.Index(fields=["recurrence_type", "start_date"]),
        ]


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


class SchoolCalendarEventOccurrence(BaseModel):
    """Expanded event rows by concrete date for fast calendar range queries."""

    event = models.ForeignKey(
        SchoolCalendarEvent,
        on_delete=models.CASCADE,
        related_name="occurrences",
    )
    occurrence_date = models.DateField()

    def __str__(self):
        return f"{self.event.name} @ {self.occurrence_date}"

    class Meta:
        db_table = "calendar_event_occurrence"
        ordering = ["occurrence_date", "event__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["event", "occurrence_date"],
                name="uniq_school_calendar_event_occurrence",
            )
        ]
        indexes = [
            models.Index(fields=["occurrence_date"]),
            models.Index(fields=["event", "occurrence_date"]),
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

    class PeriodType(models.TextChoices):
        CLASS = "class", "Class"
        RECESS = "recess", "Recess"

    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True, default=None)
    period_type = models.CharField(
        max_length=20,
        choices=PeriodType.choices,
        default=PeriodType.CLASS,
    )

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


class SectionTimeSlot(BaseModel):
    """A section-owned timetable slot.

    This allows each section to keep independent day/time ranges even when
    using shared period labels (e.g. Period 1, Recess).
    """

    DAY_OF_WEEK_CHOICES = [
        (1, "Monday"),
        (2, "Tuesday"),
        (3, "Wednesday"),
        (4, "Thursday"),
        (5, "Friday"),
        (6, "Saturday"),
        (7, "Sunday"),
    ]

    section = models.ForeignKey(
        Section, on_delete=models.CASCADE, related_name="time_slots"
    )
    period = models.ForeignKey(
        Period, on_delete=models.CASCADE, related_name="section_time_slots"
    )
    day_of_week = models.PositiveIntegerField(choices=DAY_OF_WEEK_CHOICES)
    start_time = models.TimeField()
    end_time = models.TimeField()
    sort_order = models.PositiveIntegerField(default=1)

    def clean(self):
        if self.start_time >= self.end_time:
            raise ValidationError("Start time must be earlier than end time.")

        overlap_exists = (
            SectionTimeSlot.objects.filter(
                section=self.section,
                day_of_week=self.day_of_week,
                active=True,
                start_time__lt=self.end_time,
                end_time__gt=self.start_time,
            )
            .exclude(id=self.id)
            .exists()
        )
        if overlap_exists:
            raise ValidationError(
                "This section already has an overlapping time slot for the selected day."
            )

    def __str__(self):
        return (
            f"{self.section.name} - {self.period.name} "
            f"(D{self.day_of_week} {self.start_time}-{self.end_time})"
        )

    class Meta:
        db_table = "section_time_slot"
        ordering = ["day_of_week", "sort_order", "start_time"]
        indexes = [
            models.Index(fields=["section", "day_of_week", "start_time"]),
            models.Index(fields=["section", "period"]),
        ]


class SectionSchedule(BaseModel):
    """A model to represent the schedule of a class."""

    section = models.ForeignKey(
        Section, on_delete=models.CASCADE, related_name="class_schedules"
    )
    subject = models.ForeignKey(
        SectionSubject,
        on_delete=models.CASCADE,
        related_name="class_schedules",
        null=True,
        blank=True,
    )
    section_time_slot = models.ForeignKey(
        SectionTimeSlot,
        on_delete=models.CASCADE,
        related_name="class_schedules",
        null=True,
        blank=True,
    )
    period_time = models.ForeignKey(
        PeriodTime,
        on_delete=models.CASCADE,
        related_name="class_schedules",
        null=True,
        blank=True,
    )
    period = models.ForeignKey(
        Period, on_delete=models.CASCADE, related_name="class_schedules"
    )

    def clean(self):
        if self.section_time_slot:
            if self.section_time_slot.section_id != self.section_id:
                raise ValidationError(
                    "Selected SectionTimeSlot does not belong to this section."
                )
            if self.section_time_slot.period_id != self.period_id:
                raise ValidationError(
                    "Selected SectionTimeSlot does not belong to the selected Period."
                )
        elif self.period_time:
            # Legacy path for compatibility until fully migrated.
            if self.period_time.period_id != self.period_id:
                raise ValidationError(
                    "The selected PeriodTime does not belong to the selected Period."
                )
        else:
            raise ValidationError("A section time slot is required.")

        # Recess should not carry a subject assignment.
        if self.period.period_type == Period.PeriodType.RECESS and self.subject is not None:
            raise ValidationError("Recess periods cannot have a subject assignment.")

        # Class periods must carry a subject assignment from the same section.
        if self.period.period_type == Period.PeriodType.CLASS:
            if self.subject is None:
                raise ValidationError("A subject assignment is required for class periods.")
            if self.subject.section_id != self.section_id:
                raise ValidationError("Selected section subject does not belong to this section.")

            # Check teacher conflicts only when a teacher is assigned.
            from staff.models import TeacherSubject

            teacher_assignments = TeacherSubject.objects.filter(
                section_subject=self.subject,
                active=True,
            ).select_related("teacher")

            # Prevent same teacher being scheduled across multiple sections at same period time.
            for assignment in teacher_assignments:
                conflict = (
                    SectionSchedule.objects.filter(
                        period_time=self.period_time,
                        subject__staff_teachers__teacher=assignment.teacher,
                        active=True,
                    )
                    .exclude(id=self.id)
                    .select_related("section", "period_time")
                    .first()
                )

                if conflict:
                    raise ValidationError(
                        f"Teacher {assignment.teacher.get_full_name()} is already scheduled "
                        f"for {conflict.section.name} at this period time."
                    )

        # One schedule row per section + period time.
        if self.section_time_slot is not None:
            section_slot_conflict = (
                SectionSchedule.objects.filter(
                    section=self.section,
                    section_time_slot=self.section_time_slot,
                    active=True,
                )
                .exclude(id=self.id)
                .exists()
            )
        else:
            section_slot_conflict = (
                SectionSchedule.objects.filter(
                    section=self.section,
                    period_time=self.period_time,
                    active=True,
                )
                .exclude(id=self.id)
                .exists()
            )
        if section_slot_conflict:
            raise ValidationError(
                "This section already has a schedule entry for the selected period time."
            )

    def __str__(self):
        if self.subject:
            return f"{self.section.name} - {self.subject.name} ({self.period.name})"
        return f"{self.section.name} - Recess ({self.period.name})"

    class Meta:
        db_table = 'section_schedule'


class GradeBookScheduleProjection(BaseModel):
    """Materialized mapping between class schedules and gradebooks."""

    class_schedule = models.ForeignKey(
        SectionSchedule,
        on_delete=models.CASCADE,
        related_name="gradebook_projections",
    )
    gradebook = models.ForeignKey(
        "grading.GradeBook",
        on_delete=models.CASCADE,
        related_name="schedule_projections",
    )
    section = models.ForeignKey(
        "Section",
        on_delete=models.CASCADE,
        related_name="gradebook_schedule_projections",
    )
    section_subject = models.ForeignKey(
        "SectionSubject",
        on_delete=models.CASCADE,
        related_name="gradebook_schedule_projections",
    )
    subject = models.ForeignKey(
        "Subject",
        on_delete=models.CASCADE,
        related_name="gradebook_schedule_projections",
    )
    period = models.ForeignKey(
        "Period",
        on_delete=models.CASCADE,
        related_name="gradebook_schedule_projections",
    )
    day_of_week = models.PositiveSmallIntegerField()
    start_time = models.TimeField()
    end_time = models.TimeField()

    class Meta:
        db_table = "gradebook_schedule_projection"
        ordering = ["day_of_week", "start_time", "gradebook__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["class_schedule", "gradebook"],
                name="uniq_gradebook_schedule_projection",
            )
        ]
        indexes = [
            models.Index(fields=["gradebook", "day_of_week", "start_time"]),
            models.Index(fields=["section", "day_of_week", "start_time"]),
        ]


class StudentScheduleProjection(BaseModel):
    """Materialized schedule rows for enrolled students."""

    class_schedule = models.ForeignKey(
        SectionSchedule,
        on_delete=models.CASCADE,
        related_name="student_projections",
    )
    enrollment = models.ForeignKey(
        "students.Enrollment",
        on_delete=models.CASCADE,
        related_name="schedule_projections",
    )
    student = models.ForeignKey(
        "students.Student",
        on_delete=models.CASCADE,
        related_name="schedule_projections",
    )
    section = models.ForeignKey(
        "Section",
        on_delete=models.CASCADE,
        related_name="student_schedule_projections",
    )
    section_subject = models.ForeignKey(
        "SectionSubject",
        on_delete=models.CASCADE,
        related_name="student_schedule_projections",
    )
    subject = models.ForeignKey(
        "Subject",
        on_delete=models.CASCADE,
        related_name="student_schedule_projections",
    )
    period = models.ForeignKey(
        "Period",
        on_delete=models.CASCADE,
        related_name="student_schedule_projections",
    )
    day_of_week = models.PositiveSmallIntegerField()
    start_time = models.TimeField()
    end_time = models.TimeField()

    class Meta:
        db_table = "student_schedule_projection"
        ordering = ["student__last_name", "day_of_week", "start_time"]
        constraints = [
            models.UniqueConstraint(
                fields=["enrollment", "class_schedule"],
                name="uniq_student_schedule_projection",
            )
        ]
        indexes = [
            models.Index(fields=["student", "day_of_week", "start_time"]),
            models.Index(fields=["section", "day_of_week", "start_time"]),
            models.Index(fields=["enrollment", "day_of_week"]),
        ]
