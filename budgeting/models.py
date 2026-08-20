from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from common.models import BaseModel


class Budget(BaseModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SUBMITTED = "submitted", "Submitted"
        APPROVED = "approved", "Approved"
        ACTIVE = "active", "Active"
        CLOSED = "closed", "Closed"

    academic_year = models.ForeignKey(
        "academics.AcademicYear", on_delete=models.PROTECT, related_name="budgets"
    )
    name = models.CharField(max_length=160)
    base_currency = models.ForeignKey(
        "accounting.AccountingCurrency", on_delete=models.PROTECT, related_name="budgets"
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    is_original = models.BooleanField(default=True, editable=False)
    version = models.PositiveIntegerField(default=1)
    notes = models.TextField(blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    submitted_by = models.ForeignKey(
        "users.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="submitted_budgets",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        "users.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="approved_budgets",
    )
    activated_at = models.DateTimeField(null=True, blank=True)
    activated_by = models.ForeignKey(
        "users.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="activated_budgets",
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(
        "users.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="closed_budgets",
    )

    class Meta:
        db_table = "budget"
        ordering = ["-academic_year__start_date", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["academic_year"], condition=Q(is_original=True),
                name="budget_one_original_per_academic_year",
            ),
            models.CheckConstraint(check=Q(version__gte=1), name="budget_version_positive"),
        ]

    def clean(self):
        super().clean()
        errors = {}
        if self.academic_year_id and not self.academic_year.is_regular:
            errors["academic_year"] = "Budgets require a regular academic year."
        if self.base_currency_id and not self.base_currency.is_base_currency:
            errors["base_currency"] = "Budget currency must be the accounting base currency."
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"{self.name} ({self.academic_year})"


class BudgetSection(BaseModel):
    class SectionType(models.TextChoices):
        REVENUE = "revenue", "Revenue"
        EXPENSE = "expense", "Expense"

    budget = models.ForeignKey(Budget, on_delete=models.CASCADE, related_name="sections")
    name = models.CharField(max_length=160)
    section_type = models.CharField(max_length=12, choices=SectionType.choices)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "budget_section"
        ordering = ["sort_order", "name"]
        constraints = [
            models.UniqueConstraint(fields=["budget", "name"], name="budget_section_name_unique")
        ]

    def __str__(self):
        return self.name


class BudgetLine(BaseModel):
    class SourceType(models.TextChoices):
        CUSTOM = "custom", "Custom"
        FEE_RATE = "fee_rate", "Fee rate"
        PAYROLL = "payroll", "Payroll"
        PRIOR_ACTUAL = "prior_actual", "Prior actual"

    section = models.ForeignKey(BudgetSection, on_delete=models.CASCADE, related_name="lines")
    name = models.CharField(max_length=200)
    source_type = models.CharField(max_length=24, choices=SourceType.choices, default=SourceType.CUSTOM)
    source_ref = models.CharField(max_length=255, blank=True)
    source_snapshot = models.JSONField(default=dict, blank=True)
    gl_account = models.ForeignKey(
        "accounting.AccountingLedgerAccount", on_delete=models.PROTECT,
        related_name="budget_lines", null=True, blank=True,
    )
    annual_planned_amount = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "budget_line"
        ordering = ["sort_order", "name"]
        constraints = [
            models.UniqueConstraint(fields=["section", "name"], name="budget_line_name_unique"),
            models.CheckConstraint(
                check=Q(annual_planned_amount__gte=0), name="budget_line_amount_nonnegative"
            ),
        ]

    @property
    def budget(self):
        return self.section.budget

    def __str__(self):
        return self.name


class BudgetLinePeriod(BaseModel):
    line = models.ForeignKey(BudgetLine, on_delete=models.CASCADE, related_name="periods")
    start_date = models.DateField()
    end_date = models.DateField()
    planned_amount = models.DecimalField(max_digits=18, decimal_places=2, default=Decimal("0.00"))

    class Meta:
        db_table = "budget_line_period"
        ordering = ["start_date"]
        constraints = [
            models.UniqueConstraint(fields=["line", "start_date", "end_date"], name="budget_line_period_unique"),
            models.CheckConstraint(check=Q(end_date__gte=models.F("start_date")), name="budget_period_dates_valid"),
            models.CheckConstraint(check=Q(planned_amount__gte=0), name="budget_period_amount_nonnegative"),
        ]

    def clean(self):
        super().clean()
        if self.line_id:
            year = self.line.budget.academic_year
            if year.start_date and (self.start_date < year.start_date or self.end_date > year.end_date):
                raise ValidationError("Budget periods must fall within the academic year.")
            overlapping = BudgetLinePeriod.objects.filter(
                line_id=self.line_id,
                start_date__lte=self.end_date,
                end_date__gte=self.start_date,
            )
            if self.pk:
                overlapping = overlapping.exclude(pk=self.pk)
            if overlapping.exists():
                raise ValidationError("Budget periods for a line cannot overlap.")


class BudgetEnrollmentAssumption(BaseModel):
    budget = models.ForeignKey(Budget, on_delete=models.CASCADE, related_name="enrollment_assumptions")
    grade_level = models.ForeignKey(
        "academics.GradeLevel", on_delete=models.PROTECT, related_name="budget_assumptions"
    )
    student_category = models.CharField(max_length=50, blank=True)
    estimated_students = models.PositiveIntegerField()
    prior_actual_students = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        db_table = "budget_enrollment_assumption"
        ordering = ["grade_level__level", "student_category"]
        constraints = [
            models.UniqueConstraint(
                fields=["budget", "grade_level", "student_category"],
                name="budget_enrollment_assumption_unique",
            )
        ]


class BudgetRevision(BaseModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    budget = models.ForeignKey(Budget, on_delete=models.CASCADE, related_name="revisions")
    number = models.PositiveIntegerField()
    reason = models.TextField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        "users.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="approved_budget_revisions",
    )

    class Meta:
        db_table = "budget_revision"
        ordering = ["-number"]
        constraints = [
            models.UniqueConstraint(fields=["budget", "number"], name="budget_revision_number_unique"),
            models.CheckConstraint(check=Q(number__gte=1), name="budget_revision_number_positive"),
        ]


class BudgetRevisionLineDelta(BaseModel):
    revision = models.ForeignKey(BudgetRevision, on_delete=models.CASCADE, related_name="line_deltas")
    budget_line = models.ForeignKey(BudgetLine, on_delete=models.PROTECT, related_name="revision_deltas")
    amount_delta = models.DecimalField(max_digits=18, decimal_places=2)
    rationale = models.CharField(max_length=255, blank=True)

    class Meta:
        db_table = "budget_revision_line_delta"
        constraints = [
            models.UniqueConstraint(fields=["revision", "budget_line"], name="budget_revision_line_unique"),
            models.CheckConstraint(check=~Q(amount_delta=0), name="budget_revision_delta_nonzero"),
        ]

    def clean(self):
        super().clean()
        if self.revision_id and self.budget_line_id and self.revision.budget_id != self.budget_line.budget.id:
            raise ValidationError("Revision line must belong to the revision budget.")


class BudgetLifecycleEvent(BaseModel):
    budget = models.ForeignKey(Budget, on_delete=models.CASCADE, related_name="lifecycle_events")
    from_status = models.CharField(max_length=16, blank=True)
    to_status = models.CharField(max_length=16, choices=Budget.Status.choices)
    event_type = models.CharField(max_length=30)
    actor = models.ForeignKey(
        "users.User", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="budget_lifecycle_events",
    )
    reason = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "budget_lifecycle_event"
        ordering = ["-created_at"]
