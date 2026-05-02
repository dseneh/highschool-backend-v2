"""HR app models for employee-first human resources management."""

from datetime import date, datetime
from decimal import Decimal

from django.db import models
from django.utils import timezone

from common.models import BaseModel, BasePersonModel


class EmployeeDepartment(BaseModel):
    """Organizational units for employees."""

    name = models.CharField(max_length=150)
    code = models.CharField(max_length=30, blank=True, default="")
    description = models.TextField(blank=True, null=True, default=None)

    class Meta:
        db_table = "employee_department"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["name"],
                name="hr_uniq_employee_department_name_per_tenant",
            ),
            models.UniqueConstraint(
                fields=["code"],
                name="hr_uniq_employee_department_code_per_tenant",
                condition=~models.Q(code=""),
            ),
        ]

    def __str__(self):
        return self.name


class EmployeePosition(BaseModel):
    """Job roles available to employees."""

    class EmploymentType(models.TextChoices):
        FULL_TIME = "full_time", "Full-time"
        PART_TIME = "part_time", "Part-time"
        CONTRACT = "contract", "Contract"
        TEMPORARY = "temporary", "Temporary"
        INTERN = "intern", "Intern"

    department = models.ForeignKey(
        EmployeeDepartment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="positions",
    )
    title = models.CharField(max_length=150)
    code = models.CharField(max_length=30, blank=True, default="")
    description = models.TextField(blank=True, null=True, default=None)
    employment_type = models.CharField(
        max_length=20,
        choices=EmploymentType.choices,
        default=EmploymentType.FULL_TIME,
    )
    can_teach = models.BooleanField(default=False)

    class Meta:
        db_table = "employee_position"
        ordering = ["title"]
        constraints = [
            models.UniqueConstraint(
                fields=["title", "department"],
                name="hr_uniq_employee_position_title_per_department",
            ),
            models.UniqueConstraint(
                fields=["code"],
                name="hr_uniq_employee_position_code_per_tenant",
                condition=~models.Q(code=""),
            ),
        ]

    def __str__(self):
        return self.title


class Employee(BasePersonModel):
    """Canonical employee record for the HR module."""

    class EmploymentStatus(models.TextChoices):
        ACTIVE = "active", "Active"
        INACTIVE = "inactive", "Inactive"
        SUSPENDED = "suspended", "Suspended"
        TERMINATED = "terminated", "Terminated"
        ON_LEAVE = "on_leave", "On Leave"
        RETIRED = "retired", "Retired"

    employee_number = models.CharField(max_length=30, unique=True)
    hire_date = models.DateField(null=True, blank=True, default=None)
    termination_date = models.DateField(null=True, blank=True, default=None)
    termination_reason = models.TextField(blank=True, null=True, default=None)
    employment_status = models.CharField(
        max_length=20,
        choices=EmploymentStatus.choices,
        default=EmploymentStatus.ACTIVE,
    )
    department = models.ForeignKey(
        EmployeeDepartment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employees",
    )
    position = models.ForeignKey(
        EmployeePosition,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employees",
    )
    manager = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="direct_reports",
    )
    job_title = models.CharField(max_length=150, blank=True, null=True, default=None)
    employment_type = models.CharField(
        max_length=20,
        choices=EmployeePosition.EmploymentType.choices,
        default=EmployeePosition.EmploymentType.FULL_TIME,
    )
    national_id = models.CharField(max_length=100, blank=True, null=True, default=None)
    passport_number = models.CharField(max_length=100, blank=True, null=True, default=None)
    user_account_id_number = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        default=None,
        help_text="Loose link to a User.id_number in the public schema.",
    )
    is_teacher = models.BooleanField(default=False)

    # ---- Payroll fields ---------------------------------------------------
    class SalaryType(models.TextChoices):
        MONTHLY = "monthly", "Monthly Salary"
        HOURLY = "hourly", "Hourly Wage"

    salary_type = models.CharField(
        max_length=20,
        choices=SalaryType.choices,
        default=SalaryType.MONTHLY,
    )
    basic_salary = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Monthly base for MONTHLY salary types; ignored for HOURLY.",
    )
    hourly_rate = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Hourly rate; required for HOURLY and used for overtime computation.",
    )
    pay_schedule = models.ForeignKey(
        "payroll.PaySchedule",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employees",
    )
    tax_rules = models.ManyToManyField(
        "payroll.TaxRule",
        blank=True,
        related_name="employees",
        help_text="Override tax rules for this employee. If empty, all active rules apply.",
    )
    tax_id = models.CharField(max_length=60, blank=True, null=True, default=None)
    bank_name = models.CharField(max_length=120, blank=True, null=True, default=None)
    bank_account_number = models.CharField(max_length=60, blank=True, null=True, default=None)

    class Meta:
        db_table = "employee"
        ordering = ["first_name", "last_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["employee_number"],
                name="hr_uniq_employee_number_per_tenant",
                condition=~models.Q(employee_number=""),
            )
        ]

    def __str__(self):
        return f"{self.employee_number} - {self.get_full_name()}"

    def save(self, *args, **kwargs):
        if not self.id_number:
            self.id_number = self._generate_id_number()
        super().save(*args, **kwargs)

    @classmethod
    def _generate_id_number(cls) -> str:
        """Generate a tenant-unique ID number like ``EMP-ID-000001``.

        Used as a default when callers don't supply one. The value is
        derived from the highest existing numeric suffix to avoid races
        with concurrent inserts of arbitrary user-supplied values.
        """
        prefix = "EMP-"
        next_seq = 1
        last = (
            cls.objects.filter(id_number__startswith=prefix)
            .order_by("-id_number")
            .values_list("id_number", flat=True)
            .first()
        )
        if last:
            suffix = "".join(ch for ch in last[len(prefix):] if ch.isdigit())
            if suffix.isdigit():
                next_seq = int(suffix) + 1
        return f"{prefix}{next_seq:06d}"

    def get_leave_requests_for_display(self, leave_requests=None):
        if leave_requests is not None:
            return list(leave_requests)
        if self.pk and not self._state.adding:
            return list(self.leave_requests.select_related("leave_type").all())
        return []

    def get_leave_balance_summary(self, leave_requests=None, as_of_date=None):
        requests = self.get_leave_requests_for_display(leave_requests)
        as_of_date = as_of_date or timezone.localdate()
        current_year = as_of_date.year

        leave_types_by_id = {}
        for request in requests:
            leave_type = getattr(request, "leave_type", None)
            if not leave_type:
                continue
            leave_type_key = str(
                getattr(leave_type, "id", None)
                or request.leave_type_id
                or leave_type.code
                or leave_type.name
            )
            leave_types_by_id[leave_type_key] = leave_type

        if self.pk and not self._state.adding:
            for leave_type in LeaveType.objects.filter(active=True).order_by("name"):
                leave_types_by_id.setdefault(str(leave_type.id), leave_type)

        summary = []
        for _, leave_type in sorted(leave_types_by_id.items(), key=lambda item: item[1].name):
            approved_requests = [
                request
                for request in requests
                if request.leave_type == leave_type
                and request.status == LeaveRequest.Status.APPROVED
                and request.start_date
            ]
            prior_year_requests = [
                request for request in approved_requests if request.start_date.year == current_year - 1
            ]
            carried_over_days = leave_type.get_carried_over_days(
                employee=self,
                approved_requests=prior_year_requests,
                as_of_date=as_of_date,
            )
            entitled_days = leave_type.get_entitled_days(
                employee=self,
                as_of_date=as_of_date,
                carried_over_days=carried_over_days,
            )
            used_days = sum(
                request.total_days
                for request in approved_requests
                if request.start_date.year == current_year
            )
            summary.append(
                {
                    "year": current_year,
                    "leave_type": leave_type.name,
                    "leave_type_code": leave_type.code or None,
                    "default_days": leave_type.default_days,
                    "entitled_days": entitled_days,
                    "carried_over_days": carried_over_days,
                    "used_days": used_days,
                    "remaining_days": max(entitled_days - used_days, 0),
                    "accrual_frequency": leave_type.accrual_frequency,
                    "allow_carryover": leave_type.allow_carryover,
                    "max_carryover_days": leave_type.max_carryover_days,
                }
            )

        return summary

    def payroll_readiness(self):
        """Return ``{ready: bool, missing: [str]}`` summarizing payroll setup.

        An employee is payroll-ready when they have an assigned pay
        schedule and either a non-zero basic salary (MONTHLY) or hourly
        rate (HOURLY).
        """
        missing: list[str] = []
        if not self.pay_schedule_id:
            missing.append("pay_schedule")
        if self.salary_type == self.SalaryType.MONTHLY:
            if not self.basic_salary or self.basic_salary <= 0:
                missing.append("basic_salary")
        else:  # HOURLY
            if not self.hourly_rate or self.hourly_rate <= 0:
                missing.append("hourly_rate")
        if self.pk and not self.tax_rules.exists():
            missing.append("tax_rules")
        if self.employment_status != self.EmploymentStatus.ACTIVE:
            missing.append("active_status")
        return {"ready": not missing, "missing": missing}


class EmployeeContact(BaseModel):
    """Emergency or related contacts for an employee."""

    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="contacts",
    )
    contact_type = models.CharField(max_length=50, blank=True, null=True, default=None)
    first_name = models.CharField(max_length=150, blank=True, null=True, default=None)
    last_name = models.CharField(max_length=150, blank=True, null=True, default=None)
    phone_number = models.CharField(max_length=30, blank=True, null=True, default=None)
    email = models.EmailField(blank=True, null=True, default=None)
    relationship = models.CharField(max_length=100, blank=True, null=True, default=None)
    street = models.CharField(max_length=255, blank=True, null=True, default=None)
    city = models.CharField(max_length=100, blank=True, null=True, default=None)
    state = models.CharField(max_length=100, blank=True, null=True, default=None)
    postal_code = models.CharField(max_length=50, blank=True, null=True, default=None)
    country = models.CharField(max_length=100, blank=True, null=True, default=None)
    is_primary = models.BooleanField(default=False)

    class Meta:
        db_table = "employee_contact"
        ordering = ["-is_primary", "first_name", "last_name"]

    def __str__(self):
        full_name = f"{self.first_name or ''} {self.last_name or ''}".strip()
        return full_name or f"Contact for {self.employee.get_full_name()}"


class EmployeeDependent(BasePersonModel):
    """Dependents attached to an employee record."""

    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="dependents",
    )
    relationship = models.CharField(max_length=100, blank=True, null=True, default=None)
    national_id = models.CharField(max_length=100, blank=True, null=True, default=None)

    class Meta:
        db_table = "employee_dependent"
        ordering = ["first_name", "last_name"]

    def __str__(self):
        return f"{self.get_full_name()} ({self.relationship or 'Dependent'})"


class LeaveType(BaseModel):
    """Types of leave that employees can request."""

    class AccrualFrequency(models.TextChoices):
        UPFRONT = "upfront", "Upfront"
        MONTHLY = "monthly", "Monthly"
        QUARTERLY = "quarterly", "Quarterly"
        ANNUALLY = "annually", "Annually"

    name = models.CharField(max_length=120)
    code = models.CharField(max_length=30, blank=True, default="")
    description = models.TextField(blank=True, null=True, default=None)
    default_days = models.PositiveIntegerField(default=1)
    requires_approval = models.BooleanField(default=True)
    accrual_frequency = models.CharField(
        max_length=20,
        choices=AccrualFrequency.choices,
        default=AccrualFrequency.UPFRONT,
    )
    allow_carryover = models.BooleanField(default=False)
    max_carryover_days = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "leave_type"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["name"],
                name="hr_uniq_leave_type_name_per_tenant",
            ),
            models.UniqueConstraint(
                fields=["code"],
                name="hr_uniq_leave_type_code_per_tenant",
                condition=~models.Q(code=""),
            ),
        ]

    def __str__(self):
        return self.name

    def get_entitled_days(self, employee=None, as_of_date=None, carried_over_days=0):
        as_of_date = as_of_date or timezone.localdate()
        start_of_year = date(as_of_date.year, 1, 1)
        hire_date = getattr(employee, "hire_date", None)

        if hire_date and hire_date > as_of_date:
            return max(carried_over_days, 0)

        effective_start = max(start_of_year, hire_date) if hire_date else start_of_year

        if self.accrual_frequency == self.AccrualFrequency.MONTHLY:
            months_elapsed = max(as_of_date.month - effective_start.month + 1, 0)
            accrued_days = (self.default_days * min(months_elapsed, 12)) // 12
        elif self.accrual_frequency == self.AccrualFrequency.QUARTERLY:
            current_quarter = ((as_of_date.month - 1) // 3) + 1
            start_quarter = ((effective_start.month - 1) // 3) + 1
            quarters_elapsed = max(current_quarter - start_quarter + 1, 0)
            accrued_days = (self.default_days * min(quarters_elapsed, 4)) // 4
        else:
            accrued_days = self.default_days

        return max(accrued_days + max(carried_over_days, 0), 0)

    def get_carried_over_days(self, employee=None, approved_requests=None, as_of_date=None):
        if not self.allow_carryover:
            return 0

        as_of_date = as_of_date or timezone.localdate()
        previous_year_end = date(as_of_date.year - 1, 12, 31)
        hire_date = getattr(employee, "hire_date", None)

        if hire_date and hire_date > previous_year_end:
            return 0

        prior_year_entitlement = self.get_entitled_days(
            employee=employee,
            as_of_date=previous_year_end,
            carried_over_days=0,
        )
        prior_year_used = sum(request.total_days for request in (approved_requests or []))
        unused_days = max(prior_year_entitlement - prior_year_used, 0)

        if self.max_carryover_days:
            return min(unused_days, self.max_carryover_days)
        return unused_days


class LeaveRequest(BaseModel):
    """Employee leave application and approval record."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        CANCELLED = "cancelled", "Cancelled"

    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="leave_requests",
    )
    leave_type = models.ForeignKey(
        LeaveType,
        on_delete=models.PROTECT,
        related_name="leave_requests",
    )
    start_date = models.DateField()
    end_date = models.DateField()
    reason = models.TextField(blank=True, null=True, default=None)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    reviewed_at = models.DateTimeField(blank=True, null=True, default=None)
    review_note = models.TextField(blank=True, null=True, default=None)

    class Meta:
        db_table = "leave_request"
        ordering = ["-start_date", "-created_at"]

    def __str__(self):
        return f"{self.employee.get_full_name()} - {self.leave_type.name}"

    @property
    def total_days(self):
        if not self.start_date or not self.end_date:
            return 0
        return (self.end_date - self.start_date).days + 1

    def approve(self, review_note=None):
        self.status = self.Status.APPROVED
        self.reviewed_at = timezone.now()
        if review_note is not None:
            self.review_note = review_note
        self._update_employee_status(Employee.EmploymentStatus.ON_LEAVE)
        self._persist_status_change()

    def reject(self, review_note=None):
        self.status = self.Status.REJECTED
        self.reviewed_at = timezone.now()
        if review_note is not None:
            self.review_note = review_note
        if self.employee.employment_status == Employee.EmploymentStatus.ON_LEAVE:
            self._update_employee_status(Employee.EmploymentStatus.ACTIVE)
        self._persist_status_change()

    def cancel(self, review_note=None):
        self.status = self.Status.CANCELLED
        self.reviewed_at = timezone.now()
        if review_note is not None:
            self.review_note = review_note
        if self.employee.employment_status == Employee.EmploymentStatus.ON_LEAVE:
            self._update_employee_status(Employee.EmploymentStatus.ACTIVE)
        self._persist_status_change()

    def _update_employee_status(self, status_value):
        self.employee.employment_status = status_value
        self.employee.updated_by = self.updated_by
        if self.employee.pk and not self.employee._state.adding:
            self.employee.save(update_fields=["employment_status", "updated_by", "updated_at"])

    def _persist_status_change(self):
        if self.pk and not self._state.adding:
            self.save(update_fields=["status", "reviewed_at", "review_note", "updated_by", "updated_at"])


class EmployeeAttendance(BaseModel):
    """Daily attendance record for an employee."""

    class Status(models.TextChoices):
        PRESENT = "present", "Present"
        LATE = "late", "Late"
        ABSENT = "absent", "Absent"
        REMOTE = "remote", "Remote"
        ON_LEAVE = "on_leave", "On Leave"

    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="attendance_records",
    )
    attendance_date = models.DateField(default=timezone.localdate)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PRESENT,
    )
    check_in_time = models.TimeField(blank=True, null=True, default=None)
    check_out_time = models.TimeField(blank=True, null=True, default=None)
    notes = models.TextField(blank=True, null=True, default=None)

    class Meta:
        db_table = "employee_attendance"
        ordering = ["-attendance_date", "employee__first_name", "employee__last_name"]
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "attendance_date"],
                name="hr_uniq_employee_attendance_per_day",
            )
        ]

    def __str__(self):
        return f"{self.employee.get_full_name()} - {self.attendance_date}"

    @property
    def hours_worked(self):
        if not self.check_in_time or not self.check_out_time:
            return 0.0

        check_in = self.check_in_time
        check_out = self.check_out_time

        if isinstance(check_in, str):
            check_in = datetime.strptime(check_in, "%H:%M:%S").time()
        if isinstance(check_out, str):
            check_out = datetime.strptime(check_out, "%H:%M:%S").time()

        started = datetime.combine(date.today(), check_in)
        ended = datetime.combine(date.today(), check_out)
        if ended < started:
            return 0.0

        return round((ended - started).total_seconds() / 3600, 2)


class EmployeePerformanceReview(BaseModel):
    """Structured performance review records for employees."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        IN_PROGRESS = "in_progress", "In Progress"
        COMPLETED = "completed", "Completed"
        ACKNOWLEDGED = "acknowledged", "Acknowledged"

    class Rating(models.TextChoices):
        NEEDS_IMPROVEMENT = "needs_improvement", "Needs Improvement"
        MEETS_EXPECTATIONS = "meets_expectations", "Meets Expectations"
        EXCEEDS_EXPECTATIONS = "exceeds_expectations", "Exceeds Expectations"
        OUTSTANDING = "outstanding", "Outstanding"

    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="performance_reviews",
    )
    reviewer = models.ForeignKey(
        Employee,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviews_conducted",
    )
    review_title = models.CharField(max_length=180)
    review_period = models.CharField(max_length=100, blank=True, null=True, default=None)
    review_date = models.DateField(default=timezone.localdate)
    next_review_date = models.DateField(blank=True, null=True, default=None)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    rating = models.CharField(
        max_length=30,
        choices=Rating.choices,
        default=Rating.MEETS_EXPECTATIONS,
    )
    goals_summary = models.TextField(blank=True, null=True, default=None)
    strengths = models.TextField(blank=True, null=True, default=None)
    improvement_areas = models.TextField(blank=True, null=True, default=None)
    manager_comments = models.TextField(blank=True, null=True, default=None)
    employee_comments = models.TextField(blank=True, null=True, default=None)
    overall_score = models.DecimalField(max_digits=4, decimal_places=2, blank=True, null=True, default=None)

    class Meta:
        db_table = "employee_performance_review"
        ordering = ["-review_date", "employee__first_name", "employee__last_name"]

    def __str__(self):
        return f"{self.employee.get_full_name()} - {self.review_title}"

    @property
    def rating_score(self):
        score_map = {
            self.Rating.NEEDS_IMPROVEMENT: 2,
            self.Rating.MEETS_EXPECTATIONS: 3,
            self.Rating.EXCEEDS_EXPECTATIONS: 5,
            self.Rating.OUTSTANDING: 5,
        }
        return score_map.get(self.rating, 0)

    @property
    def is_completed(self):
        return self.status in {self.Status.COMPLETED, self.Status.ACKNOWLEDGED}


