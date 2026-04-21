"""Grading system models for the school management system.

All models are tenant-specific (live in tenant schemas).
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import (
    Sum, F, ExpressionWrapper, FloatField, Count, CheckConstraint, Q, Index
)
from django.utils.translation import gettext_lazy as _

from common.models import BaseModel


class GradeLetter(BaseModel):
    """
    School-specific grade letters that define letter grades and their percentage ranges.
    Each school can customize their grading standards.
    
    Examples:
    - Letter: "A+", Min: 97, Max: 100
    - Letter: "A", Min: 93, Max: 96
    - Letter: "B+", Min: 87, Max: 92
    """
    letter = models.CharField(
        max_length=10,
        help_text="The letter grade (e.g., A+, A, B+, B, etc.)"
    )
    min_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        help_text="Minimum percentage for this letter grade (inclusive)"
    )
    max_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        help_text="Maximum percentage for this letter grade (inclusive)"
    )
    order = models.PositiveIntegerField(
        default=0,
        help_text="Order for display purposes (lower numbers first)"
    )

    class Meta:
        db_table = 'grade_letter'
        constraints = [
            models.UniqueConstraint(
                fields=['letter'],
                name='unique_letter_per_tenant'
            ),
            models.CheckConstraint(
                check=models.Q(min_percentage__lte=models.F('max_percentage')),
                name='grade_letter_min_lte_max'
            ),
            # Ensure percentages are within valid range
            models.CheckConstraint(
                check=models.Q(
                    min_percentage__gte=0,
                    max_percentage__lte=100
                ),
                name='grade_letter_percentage_valid_range'
            )
        ]
        indexes = [
            models.Index(fields=['min_percentage', 'max_percentage']),
            models.Index(fields=['order']),
        ]
        ordering = ['order', '-max_percentage']

    def __str__(self):
        return f"{self.letter} ({self.min_percentage}%-{self.max_percentage}%)"

    def clean(self):
        """Validate percentage ranges don't overlap with other letters in the same school."""
        super().clean()
        
        if self.min_percentage > self.max_percentage:
            raise ValidationError("Minimum percentage cannot be greater than maximum percentage.")
        
        overlapping = GradeLetter.objects.all().exclude(pk=self.pk)
        
        for other in overlapping:
            if (self.min_percentage <= other.max_percentage and 
                self.max_percentage >= other.min_percentage):
                raise ValidationError(
                    f"Percentage range {self.min_percentage}-{self.max_percentage}% "
                    f"overlaps with {other.letter} ({other.min_percentage}-{other.max_percentage}%)"
                )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    @classmethod
    def get_letter_for_percentage(cls, percentage):
        """Get the letter grade for a given percentage within a specific school."""
        try:
            grade_letter = cls.objects.get(
                min_percentage__lte=percentage,
                max_percentage__gte=percentage
            )
            return grade_letter.letter
        except cls.DoesNotExist:
            return "-"
        except cls.MultipleObjectsReturned:
            return cls.objects.filter(
                min_percentage__lte=percentage,
                max_percentage__gte=percentage
            ).first().letter


class HonorCategory(BaseModel):
    """
    School-specific honor/performance categories that classify students by their
    final average. Each category defines a percentage band; the dashboard uses
    these to produce an honor distribution (e.g., Principal's List, Honor Roll).

    Examples:
    - Label: "Principal's List",  Min: 95, Max: 100
    - Label: "Honor Roll",        Min: 90, Max: 94.99
    - Label: "Honorable Mention", Min: 85, Max: 89.99
    """

    label = models.CharField(
        max_length=100,
        help_text="Display name for the honor category (e.g., 'Principal's List')."
    )
    min_average = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        help_text="Minimum percentage average for this honor (inclusive)."
    )
    max_average = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        help_text="Maximum percentage average for this honor (inclusive)."
    )
    color = models.CharField(
        max_length=32,
        blank=True,
        default="",
        help_text="Optional badge color (hex or tailwind token) for UI rendering."
    )
    icon = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="Optional icon name for UI rendering."
    )
    order = models.PositiveIntegerField(
        default=0,
        help_text="Display order (lower numbers first)."
    )

    class Meta:
        db_table = 'honor_category'
        constraints = [
            models.UniqueConstraint(
                fields=['label'],
                name='unique_honor_label_per_tenant'
            ),
            models.CheckConstraint(
                check=models.Q(min_average__lte=models.F('max_average')),
                name='honor_category_min_lte_max'
            ),
            models.CheckConstraint(
                check=models.Q(
                    min_average__gte=0,
                    max_average__lte=100
                ),
                name='honor_category_percentage_valid_range'
            ),
        ]
        indexes = [
            models.Index(fields=['min_average', 'max_average']),
            models.Index(fields=['order']),
        ]
        ordering = ['order', '-max_average']

    def __str__(self):
        return f"{self.label} ({self.min_average}%-{self.max_average}%)"

    def clean(self):
        super().clean()

        if self.min_average > self.max_average:
            raise ValidationError("Minimum average cannot be greater than maximum average.")

        overlapping = HonorCategory.objects.all().exclude(pk=self.pk)
        for other in overlapping:
            if (self.min_average <= other.max_average and
                    self.max_average >= other.min_average):
                raise ValidationError(
                    f"Average range {self.min_average}-{self.max_average}% "
                    f"overlaps with {other.label} ({other.min_average}-{other.max_average}%)"
                )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    @classmethod
    def get_category_for_average(cls, average):
        """Return the HonorCategory containing the given percentage, or None."""
        if average is None:
            return None
        try:
            return cls.objects.get(
                active=True,
                min_average__lte=average,
                max_average__gte=average,
            )
        except cls.DoesNotExist:
            return None
        except cls.MultipleObjectsReturned:
            return cls.objects.filter(
                active=True,
                min_average__lte=average,
                max_average__gte=average,
            ).order_by('order').first()


class AssessmentType(BaseModel):
    """
    Catalog of assessment types (e.g., Assignment, Quiz, Test, Project, Final Grade).
    Scoped by School so schools can customize their taxonomy.
    
    is_single_entry: Used for single-entry grading mode where only final grades are captured.
                     When True, this assessment type represents a final grade entry.
    """
    name = models.CharField(max_length=64)
    description = models.TextField(blank=True, default="")
    is_single_entry = models.BooleanField(
        default=False,
        help_text="True if this assessment type is used for single-entry (final grade only) mode"
    )

    class Meta:
        db_table = 'assessment_type'
        unique_together = [("name",)]
        ordering = ["name"]
        indexes = [Index(fields=["name"])]

    def __str__(self) -> str:
        return self.name


class GradeBook(BaseModel):
    """
    Year-specific gradebook for a SectionSubject (Section × Subject template).

    calculation_method:
      - average   : simple average of item percentages
      - weighted  : weighted average using Assessment.weight
      - cumulative: sum(points earned) / sum(points possible) * 100

    Final-grade math counts ONLY Grade.status == APPROVED.
    """
    class CalculationMethod(models.TextChoices):
        AVERAGE = "average", _("Simple Average")
        WEIGHTED = "weighted", _("Weighted")
        CUMULATIVE = "cumulative", _("Cumulative Points")

    section_subject = models.ForeignKey(
        "academics.SectionSubject",
        on_delete=models.PROTECT,
        related_name="gradebooks",
        db_index=True,
        help_text="Timeless Section×Subject template.",
    )
    section = models.ForeignKey(
        "academics.Section",
        on_delete=models.PROTECT,
        related_name="gradebooks",
        db_index=True,
        help_text="Denormalized from section_subject for fast filtering.",
    )
    subject = models.ForeignKey(
        "academics.Subject",
        on_delete=models.PROTECT,
        related_name="gradebooks",
        db_index=True,
        help_text="Denormalized from section_subject for fast filtering.",
    )
    academic_year = models.ForeignKey(
        "academics.academicyear",
        on_delete=models.PROTECT,
        related_name="gradebooks",
        db_index=True,
        help_text="Year slice for this gradebook.",
    )

    name = models.CharField(max_length=120, help_text="e.g., Algebra I 2025–26 (10A)")
    calculation_method = models.CharField(
        max_length=16, choices=CalculationMethod.choices, default=CalculationMethod.AVERAGE, db_index=True
    )
    
    # Override BaseModel fields to avoid conflicts with students.GradeBook
    created_by = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_grading_gradebook_set",
        to_field="id",
    )
    updated_by = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="updated_grading_gradebook_set", 
        to_field="id",
    )

    class Meta:
        db_table = 'gradebook'
        unique_together = ("section_subject", "academic_year", "name")
        indexes = [
            Index(fields=["section_subject", "academic_year"]),
            Index(fields=["academic_year", "calculation_method"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} — {self.section_subject} [{self.academic_year}]"

    # ---------- Final grade helpers (APPROVED only) ----------

    def _final_queryset_for_student(self, student_id) -> models.QuerySet:
        """
        Internal helper: approved Grade rows for this gradebook and student.
        Optimized to use denormalized fields and avoid unnecessary JOINs.
        Only includes grades from assessments where is_calculated=True.
        """
        return (
            Grade.objects.filter(
                # Use denormalized fields to avoid JOINs where possible
                student_id=student_id,
                status=Grade.Status.APPROVED,
                # Only join to gradebook when necessary
                assessment__gradebook=self,
                # Only include grades from assessments that should be calculated
                assessment__is_calculated=True,
            )
            .select_related("assessment")
            .only("score", "assessment__max_score", "assessment__weight", "assessment_id")
        )

    def final_percentage_for_student(self, student, status='approved') -> Optional[Decimal]:
        """
        Compute student's final percentage (0..100) for this GradeBook,
        using this gradebook's calculation_method.

        Args:
            student: Student instance
            status: Grade status to filter by ('approved' by default, 'any' for all statuses, or specific status)

        Returns:
            Decimal rounded to 2 decimals, or None if no grades exist.
        """
        # Build the base query
        qs = (
            Grade.objects
            .filter(
                assessment__gradebook=self,
                student=student,
                assessment__is_calculated=True,
                score__isnull=False
            )
            .select_related("assessment")
            .only("score", "assessment__max_score", "assessment__weight", "assessment_id")
        )
        
        # Add status filter only if not 'any'
        if status != 'any':
            qs = qs.filter(status=status)
        
        # Check if there are any grades first
        if not qs.exists():
            return None
        
        # Optimized: Single query with count to avoid separate exists() check
        if self.calculation_method == self.CalculationMethod.CUMULATIVE:
            agg = qs.aggregate(
                count=Count('id'),
                total_earned=Sum("score"), 
                total_possible=Sum("assessment__max_score")
            )
            if not agg['count'] or not agg["total_possible"]:
                return None
            pct = (Decimal(str(agg["total_earned"])) / Decimal(str(agg["total_possible"]))) * Decimal("100")
            return pct.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        # For weighted and average, we need percentage calculations
        # Filter out grades where score is None or max_score is None/0
        valid_qs = qs.filter(score__isnull=False, assessment__max_score__gt=0)
        
        if not valid_qs.exists():
            return None
            
        perc_expr = ExpressionWrapper(
            (F("score") / F("assessment__max_score")) * 100.0, output_field=FloatField()
        )

        if self.calculation_method == self.CalculationMethod.WEIGHTED:
            weighted_val = ExpressionWrapper(perc_expr * F("assessment__weight"), output_field=FloatField())
            agg = valid_qs.aggregate(
                count=Count('id'),
                wsum=Sum(weighted_val), 
                wtot=Sum("assessment__weight")
            )
            if not agg['count'] or not agg["wtot"]:
                return None
            pct = Decimal(str(agg["wsum"])) / Decimal(str(agg["wtot"]))
            return pct.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        # Simple average
        agg = valid_qs.aggregate(
            psum=Sum(perc_expr), 
            cnt=Count("id")
        )
        if not agg["cnt"] or agg["psum"] is None:
            return None
        pct = Decimal(str(agg["psum"])) / Decimal(str(agg["cnt"]))
        return pct.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def final_percentage_for_student_cached(self, student, cache_timeout: int = 300) -> Optional[Decimal]:
        """
        Cached version of final_percentage_for_student.
        Cache expires when grades are updated or after cache_timeout seconds.
        
        Args:
            student: Student instance
            cache_timeout: Cache timeout in seconds (default: 5 minutes)
        """
        cache_key = f"final_grade:gb_{self.id}:student_{student.pk}"
        
        # Try to get from cache first
        cached_result = cache.get(cache_key)
        if cached_result is not None:
            return cached_result
            
        # Calculate and cache the result
        result = self.final_percentage_for_student(student)
        cache.set(cache_key, result, cache_timeout)
        
        return result

    def bulk_final_percentages_for_students(self, student_ids: list) -> dict:
        """
        Calculate final percentages for multiple students in a single optimized query.
        Returns dict mapping student_id -> final_percentage (or None).
        
        This is much more efficient than calling final_percentage_for_student 
        multiple times as it uses a single database query.
        """
        if not student_ids:
            return {}
            
        # Get all approved grades for these students in this gradebook
        # Only include grades from items that should be calculated
        qs = Grade.objects.filter(
            student_id__in=student_ids,
            status=Grade.Status.APPROVED,
            assessment__gradebook=self,
            assessment__is_calculated=True,
        ).select_related("assessment").only(
            "student_id", "score", "assessment__max_score", "assessment__weight"
        )
        
        # Group by student and calculate
        result = {}
        grades_by_student = {}
        
        # Group grades by student
        for grade in qs:
            if grade.student_id not in grades_by_student:
                grades_by_student[grade.student_id] = []
            grades_by_student[grade.student_id].append(grade)
        
        # Calculate final percentage for each student
        for student_id in student_ids:
            student_grades = grades_by_student.get(student_id, [])
            if not student_grades:
                result[student_id] = None
                continue
                
            if self.calculation_method == self.CalculationMethod.CUMULATIVE:
                total_earned = sum(Decimal(str(g.score)) for g in student_grades)
                total_possible = sum(Decimal(str(g.assessment.max_score)) for g in student_grades)
                if total_possible:
                    pct = (total_earned / total_possible) * Decimal('100')
                else:
                    pct = None
                    
            elif self.calculation_method == self.CalculationMethod.WEIGHTED:
                weighted_sum = sum(
                    (Decimal(str(g.score)) / Decimal(str(g.assessment.max_score))) * 
                    Decimal('100') * Decimal(str(g.assessment.weight))
                    for g in student_grades
                )
                total_weight = sum(Decimal(str(g.assessment.weight)) for g in student_grades)
                if total_weight:
                    pct = weighted_sum / total_weight
                else:
                    pct = None
                    
            else:  # Simple average
                percentages = [
                    (Decimal(str(g.score)) / Decimal(str(g.assessment.max_score))) * Decimal('100')
                    for g in student_grades
                ]
                pct = sum(percentages) / len(percentages) if percentages else None
            
            if pct is not None:
                result[student_id] = pct.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            else:
                result[student_id] = None
                
        return result

    def get_assessments_count(self) -> int:
        """
        Get the total number of active assessments in this gradebook.
        """
        return self.assessments.filter(active=True).count()

    def get_calculated_assessments_count(self) -> int:
        """
        Get the number of active assessments that are included in calculations.
        """
        return self.assessments.filter(active=True, is_calculated=True).count()

    def get_overall_average_percentage(self) -> Optional[Decimal]:
        """
        Calculate the overall average percentage across all students in this gradebook
        for the academic year, considering only APPROVED grades.
        
        Returns:
            Decimal rounded to 2 decimals representing the average percentage,
            or None if no approved grades exist.
        """
        from students.models import Enrollment
        
        # Get all enrolled students for this section/academic year
        enrollments = Enrollment.objects.filter(
            section=self.section,
            academic_year=self.academic_year,
            active=True
        ).select_related('student')
        
        if not enrollments.exists():
            return None
        
        student_ids = [enrollment.student_id for enrollment in enrollments]
        
        # Use the existing bulk calculation method
        student_percentages = self.bulk_final_percentages_for_students(student_ids)
        
        # Filter out None values (students with no grades)
        valid_percentages = [pct for pct in student_percentages.values() if pct is not None]
        
        if not valid_percentages:
            return None
        
        # Calculate average
        total = sum(valid_percentages)
        average = total / len(valid_percentages)
        
        return average.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def get_gradebook_statistics(self) -> dict:
        """
        Get comprehensive statistics for this gradebook.
        
        Returns:
            dict containing:
            - total_assessments: Total number of active assessments
            - calculated_assessments: Number of assessments included in calculations
            - overall_average: Overall class average percentage (or None)
            - students_with_grades: Number of students who have at least one approved grade
            - total_enrolled_students: Total number of enrolled students
        """
        from students.models import Enrollment
        
        stats = {
            'total_assessments': self.get_assessments_count(),
            'calculated_assessments': self.get_calculated_assessments_count(),
            'overall_average': self.get_overall_average_percentage(),
        }
        
        # Get enrollment statistics
        enrollments = Enrollment.objects.filter(
            section=self.section,
            academic_year=self.academic_year,
            active=True
        )
        
        stats['total_enrolled_students'] = enrollments.count()
        
        # Count students with at least one approved grade
        student_ids = list(enrollments.values_list('student_id', flat=True))
        if student_ids:
            students_with_grades = Grade.objects.filter(
                assessment__gradebook=self,
                student_id__in=student_ids,
                status=Grade.Status.APPROVED
            ).values('student_id').distinct().count()
            stats['students_with_grades'] = students_with_grades
        else:
            stats['students_with_grades'] = 0
        
        return stats

    def get_workflow_status_summary(self) -> dict:
        """
        Get workflow status summary for all grades in this gradebook.
        Returns counts of grades in each status and the predominant status.
        
        Returns:
            dict containing:
            - draft_count: Number of grades in draft status
            - pending_count: Number of grades in pending status
            - reviewed_count: Number of grades in reviewed status
            - submitted_count: Number of grades in submitted status
            - approved_count: Number of grades in approved status
            - rejected_count: Number of grades in rejected status
            - total_grades: Total number of grades
            - predominant_status: The most common status (or "draft" if no grades)
        """
        from django.db.models import Count, Q
        
        # Get status counts for all grades in this gradebook
        status_counts = Grade.objects.filter(
            assessment__gradebook=self
        ).values('status').annotate(count=Count('id'))
        
        # Initialize counts
        counts = {
            'draft': 0,
            'pending': 0,
            'reviewed': 0,
            'submitted': 0,
            'approved': 0,
            'rejected': 0,
        }
        
        total = 0
        for item in status_counts:
            status = item['status'] or 'draft'
            count = item['count']
            if status in counts:
                counts[status] = count
                total += count
        
        # Determine predominant status
        if total == 0:
            predominant_status = 'draft'
        else:
            predominant_status = max(counts.items(), key=lambda x: x[1])[0]
        
        return {
            'draft_count': counts['draft'],
            'pending_count': counts['pending'],
            'reviewed_count': counts['reviewed'],
            'submitted_count': counts['submitted'],
            'approved_count': counts['approved'],
            'rejected_count': counts['rejected'],
            'total_grades': total,
            'predominant_status': predominant_status,
        }


class Assessment(BaseModel):
    """
    An assessment instance (Quiz 1, Test 2, Project, ...).

    - marking_period: dated instance so we can bucket items into MP1/MP2/... within the year.
    - max_score: points possible for this assessment
    - weight: used only in WEIGHTED calculation_method
    """
    gradebook = models.ForeignKey(GradeBook, on_delete=models.CASCADE, related_name="assessments", db_index=True)
    name = models.CharField(max_length=120)

    assessment_type = models.ForeignKey(
        AssessmentType, null=True, blank=True, on_delete=models.SET_NULL, related_name="assessments"
    )
    marking_period = models.ForeignKey(
        "academics.markingperiod",  # change app label if needed
        null=True, blank=True, on_delete=models.SET_NULL, related_name="assessments",
        help_text="Dated marking period; used for MP subtotals and validations.",
    )

    max_score = models.DecimalField(max_digits=8, decimal_places=2, default=100)
    weight = models.DecimalField(max_digits=8, decimal_places=2, default=1)
    due_date = models.DateField(null=True, blank=True)
    is_calculated = models.BooleanField(
        default=True,
        help_text="Whether this assessment should be included in final grade calculations."
    )

    class Meta:
        db_table = 'assessment'
        ordering = ["due_date", "name"]
        indexes = [
            Index(fields=["gradebook", "marking_period"]),
            Index(fields=["marking_period", "due_date"]),
        ]
        constraints = [
            CheckConstraint(check=Q(max_score__gt=0), name="assessment_max_score_positive"),
            CheckConstraint(check=Q(weight__gt=0), name="assessment_weight_positive"),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.gradebook.name})"

    def clean(self):
        """
        Optional: if a marking_period is set, enforce that due_date
        falls within that MP's date window.
        """
        if self.marking_period and self.due_date:
            mp = self.marking_period
            if not (mp.start_date <= self.due_date <= mp.end_date):
                raise ValidationError(_(f"Due date must fall within the Marking Period dates ({mp.start_date} - {mp.end_date})."))


class Grade(BaseModel):
    """
    A student's score for an Assessment.

    Integrity:
      - FK to core.Enrollment guarantees the student belonged to the roster/year.
      - Denormalized fields (student, academic_year, section, subject) allow fast filters.
      - Only APPROVED grades count in rollups.

    Edit workflow:
      - draft    : teacher can edit freely
      - pending  : submitted for review
      - reviewed : reviewed by reviewer/admin
      - approved : locked; counted in final grade
    """
    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        PENDING = "pending", _("Pending Review")
        REVIEWED = "reviewed", _("Reviewed")
        SUBMITTED = "submitted", _("Submitted")
        APPROVED = "approved", _("Approved")
        REJECTED = "rejected", _("Rejected")

    assessment = models.ForeignKey(Assessment, on_delete=models.CASCADE, related_name="grades", db_index=True)
    enrollment = models.ForeignKey(
        "students.Enrollment",
        on_delete=models.CASCADE,
        related_name="grades",
        db_index=True,
        help_text="Year-scoped roster row (one per student × academic_year in your schema).",
    )

    # ---- Denormalized covering FKs (kept in sync in save()) ----
    student = models.ForeignKey("students.Student", on_delete=models.CASCADE, related_name="grades_by_student", db_index=True)
    academic_year = models.ForeignKey("academics.academicyear", on_delete=models.CASCADE, related_name="grades_in_year", db_index=True)
    section = models.ForeignKey("academics.Section", on_delete=models.CASCADE, related_name="grades_in_section", db_index=True)
    subject = models.ForeignKey("academics.Subject", on_delete=models.CASCADE, related_name="grades_in_subject", db_index=True)

    score = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, db_index=True, blank=True, null=True)
    comment = models.TextField(blank=True, null=True, default=None)
    needs_correction = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Flag indicating this grade requires correction/review"
    )

    class Meta:
        db_table = 'grade'
        unique_together = ("assessment", "enrollment")
        indexes = [
            Index(fields=["student", "status"]),
            Index(fields=["academic_year", "student"]),
            Index(fields=["assessment", "status"]),
            Index(fields=["subject", "academic_year", "student"]),
            Index(fields=["section", "subject", "status"]),
            Index(fields=["student", "status", "assessment"]),
        ]
        constraints = [CheckConstraint(check=Q(score__gte=0), name="grade_score_non_negative")]

    def __str__(self) -> str:
        return f"{self.student} — {self.assessment.name}: {self.score} ({self.status})"

    def clean(self):
        """
        Ensure denormalized fields match their sources and enforce score sanity.
        """
        # Enrollment.student must match denorm student
        if self.enrollment_id and self.student_id and self.enrollment.student_id != self.student_id:
            raise ValidationError(_("Grade.student must match Enrollment.student."))

        # Score sanity vs Assessment.max_score
        if self.assessment_id:
            max_score = self.assessment.max_score
            if self.score is not None and max_score is not None and self.score > max_score:
                raise ValidationError(_("Score cannot exceed Assessment.max_score."))

        # Alignment with GradeBook
        gb = self.assessment.gradebook if self.assessment_id else None
        if gb:
            if self.academic_year_id and self.academic_year_id != gb.academic_year_id:
                raise ValidationError(_("Grade.academic_year must match GradeBook.academic_year."))
            ss = gb.section_subject
            if self.section_id and hasattr(ss, "section_id") and self.section_id != ss.section_id:
                raise ValidationError(_("Grade.section must match GradeBook's SectionSubject.section."))
            if self.subject_id and hasattr(ss, "subject_id") and self.subject_id != ss.subject_id:
                raise ValidationError(_("Grade.subject must match GradeBook's SectionSubject.subject."))

    def save(self, *args, **kwargs):
        """
        Keep denormalized fields in sync automatically on every save.
        Invalidate final grade cache when approved grades change.
        """
        if self.enrollment_id:
            self.student_id = self.enrollment.student_id
            self.section_id = self.enrollment.section_id
            self.academic_year_id = self.enrollment.academic_year_id

        if self.assessment_id:
            gb = self.assessment.gradebook
            ss = gb.section_subject
            if hasattr(ss, "subject_id"):
                self.subject_id = ss.subject_id

        # Invalidate final grade cache if this is an approved grade
        if self.status == self.Status.APPROVED and self.assessment_id and self.student_id:
            cache_key = f"final_grade:gb_{self.assessment.gradebook_id}:student_{self.student_id}"
            cache.delete(cache_key)

        super().save(*args, **kwargs)


class GradeHistory(BaseModel):
    """
    Audit trail for grade changes.
    Tracks every modification to a grade including who, when, what changed, and why.
    
    Independent of workflow status - allows tracking grade corrections at any time.
    """
    CHANGE_TYPE_CHOICES = (
        ("create", "Created"),
        ("score", "Score Changed"),
        ("status", "Status Changed"),
        ("comment", "Comment Changed"),
        ("correction", "Correction"),
        ("bulk", "Bulk Update"),
    )

    grade = models.ForeignKey(
        Grade,
        on_delete=models.CASCADE,
        related_name="history",
        db_index=True
    )

    # Snapshot of values at time of change
    old_score = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    new_score = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)

    old_status = models.CharField(max_length=16, null=True, blank=True)
    new_status = models.CharField(max_length=16, null=True, blank=True)

    old_comment = models.TextField(null=True, blank=True)
    new_comment = models.TextField(null=True, blank=True)

    # Who made the change
    changed_by = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="grade_changes"
    )

    # Why the change was made
    change_reason = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Reason for the change (e.g., 'Grade correction', 'Re-grading after appeal')"
    )

    # Change metadata
    change_type = models.CharField(
        max_length=20,
        choices=CHANGE_TYPE_CHOICES,
        default="score"
    )

    # IP address for additional audit
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        db_table = 'grade_history'
        ordering = ["-created_at"]
        indexes = [
            Index(fields=["grade", "-created_at"]),
            Index(fields=["changed_by", "-created_at"]),
        ]
        verbose_name = "Grade History"
        verbose_name_plural = "Grade Histories"

    def __str__(self):
        return f"{self.grade} - {self.change_type} by {self.changed_by} at {self.created_at}"


# ============================================================================
# DEFAULT ASSESSMENT TEMPLATES
# ============================================================================


class DefaultAssessmentTemplate(BaseModel):
    """
    Reusable assessment template that defines standard assessments.
    These templates are reference data used to automatically create Assessment instances 
    across all gradebooks. Templates are NOT year-specific - they're reusable blueprints.
    
    Example: School creates "Quiz 1", "Midterm Exam", "Final Project" templates.
    When gradebooks are created, assessments are auto-generated from these templates.
    
    The 'target' field determines which marking periods receive this assessment:
    - 'marking_period': Applied to regular marking periods (MP1, MP2, MP3, MP5, MP6, MP7)
    - 'exam': Applied only to exam marking periods (MP4, MP8 - semester exam periods)
    """
    ASSESSMENT_TARGET_CHOICES = (("marking_period", "Marking Period"), ("exam", "Exam"))

    name = models.CharField(
        max_length=120,
        help_text="Name of the assessment (e.g., 'Quiz 1', 'Midterm Exam')"
    )
    assessment_type = models.ForeignKey(
        AssessmentType,
        on_delete=models.PROTECT,
        related_name="default_templates",
        help_text="Type of assessment (Quiz, Test, Exam, Project, etc.)"
    )
    max_score = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=100,
        help_text="Maximum possible score for this assessment"
    )
    weight = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=1,
        help_text="Weight used in weighted grade calculations"
    )
    is_calculated = models.BooleanField(
        default=True,
        help_text="Whether assessments created from this template should be included in final grade calculations"
    )
    order = models.PositiveIntegerField(
        default=0,
        help_text="Display order within marking period (lower numbers first)"
    )
    description = models.TextField(
        blank=True,
        null=True,
        help_text="Optional description or instructions for this assessment"
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Inactive templates won't be used for auto-generation"
    )
    target = models.CharField(
        max_length=32,
        choices=ASSESSMENT_TARGET_CHOICES,
        default="marking_period",
        help_text="Determines which marking periods receive this assessment. 'marking_period' for regular periods, 'exam' for semester exam periods."
    )

    class Meta:
        db_table = 'assessment_template'
        ordering = ["order", "name"]
        indexes = [
            Index(fields=["assessment_type"]),
        ]
        constraints = [
            CheckConstraint(
                check=Q(max_score__gt=0),
                name="default_template_max_score_positive"
            ),
            CheckConstraint(
                check=Q(weight__gt=0),
                name="default_template_weight_positive"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.assessment_type.name})"
