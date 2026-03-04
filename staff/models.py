"""Staff management models for the school management system.

All models are tenant-specific (live in tenant schemas).
"""

from django.db import models
from decimal import Decimal

from common.models import BaseModel, BasePersonModel
from common.status import PersonStatus

class Department(BaseModel):
    """Represents a department within a school (e.g., Science, Administration)."""
    name = models.CharField(max_length=150)
    code = models.CharField(max_length=30, blank=True, default="")
    description = models.TextField(blank=True, null=True, default=None)
    created_by = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_staff_department_set",
        to_field="id",
        blank=True,
        default=None,
    )
    updated_by = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="updated_staff_department_set",
        to_field="id",
        blank=True,
        default=None,
    )

    class Meta:
        db_table = 'department'
        constraints = [
            models.UniqueConstraint(
                fields=["name"], name="staff_uniq_department_name_per_tenant"
            ),
            models.UniqueConstraint(
                fields=["code"],
                name="staff_uniq_department_code_per_tenant",
                condition=~models.Q(code=""),
            ),
        ]
        ordering = ["name"]

    def __str__(self):
        return self.name


class PositionCategory(BaseModel):
    """Groups positions under logical categories such as Faculty, Administrative, or Support."""
    name = models.CharField(max_length=80)
    description = models.TextField(blank=True, null=True, default=None)
    created_by = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_staff_positioncategory_set",
        to_field="id",
        blank=True,
        default=None,
    )
    updated_by = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="updated_staff_positioncategory_set",
        to_field="id",
        blank=True,
        default=None,
    )

    class Meta:
        db_table = 'position_category'
        constraints = [
            models.UniqueConstraint(
                fields=["name"], name="staff_uniq_positioncategory_name_per_tenant"
            )
        ]
        ordering = ["name"]

    def __str__(self):
        return self.name


class Position(BaseModel):
    """Defines a job title or role that staff can hold (e.g., Teacher, Registrar)."""
    class EmploymentType(models.TextChoices):
        FULL_TIME = "full_time", "Full-time"
        PART_TIME = "part_time", "Part-time"
        CONTRACT = "contract", "Contract"
        TEMPORARY = "temporary", "Temporary"
        INTERN = "intern", "Intern"

    class CompensationType(models.TextChoices):
        SALARY = "salary", "Salary"
        HOURLY = "hourly", "Hourly"
        STIPEND = "stipend", "Stipend"

    category = models.ForeignKey(
        PositionCategory,
        on_delete=models.SET_NULL,
        related_name="staff_positions",
        null=True,
        blank=True,
    )
    department = models.ForeignKey(
        Department,
        on_delete=models.SET_NULL,
        related_name="staff_positions",
        null=True,
        blank=True,
    )

    title = models.CharField(max_length=150)
    code = models.CharField(max_length=30, blank=True, default="")
    description = models.TextField(blank=True, null=True, default=None)
    level = models.PositiveIntegerField(default=1)
    employment_type = models.CharField(
        max_length=20, choices=EmploymentType.choices, default=EmploymentType.FULL_TIME
    )
    compensation_type = models.CharField(
        max_length=20, choices=CompensationType.choices, default=CompensationType.SALARY
    )
    salary_min = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    salary_max = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    teaching_role = models.BooleanField(default=False)
    can_delete = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_staff_position_set",
        to_field="id",
        blank=True,
        default=None,
    )
    updated_by = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="updated_staff_position_set",
        to_field="id",
        blank=True,
        default=None,
    )

    class Meta:
        db_table = 'position'
        constraints = [
            models.UniqueConstraint(
                fields=["title", "department"],
                name="staff_uniq_position_title_per_dept_per_tenant",
            ),
            models.UniqueConstraint(
                fields=["code"],
                name="staff_uniq_position_code_per_tenant",
                condition=~models.Q(code=""),
            ),
            models.CheckConstraint(
                check=models.Q(salary_min__lte=models.F("salary_max"))
                | models.Q(salary_min__isnull=True)
                | models.Q(salary_max__isnull=True),
                name="staff_chk_position_salary_range_valid",
            ),
        ]
        ordering = ["level"]

    def __str__(self):
        return f"{self.title} ({self.level})"


class Staff(BasePersonModel):
    """Represents a staff member (faculty or non-faculty) working in the school."""
    class EmploymentStatus(models.TextChoices):
        ACTIVE = "active", "Active"
        INACTIVE = "inactive", "Inactive"
        SUSPENDED = "suspended", "Suspended"
        TERMINATED = "terminated", "Terminated"
        ON_LEAVE = "on_leave", "On Leave"
        RETIRED = "retired", "Retired"

    position = models.ForeignKey(
        Position,
        on_delete=models.SET_NULL,
        related_name="staff",
        null=True,
        blank=True,
    )
    hire_date = models.DateField(null=True, blank=True)
    status = models.CharField(
        max_length=20, choices=EmploymentStatus.choices, default=EmploymentStatus.ACTIVE
    )
    photo = models.ImageField(
        upload_to="staff",
        null=True,
        blank=True,
        default=None,
    )
    primary_department = models.ForeignKey(
        Department,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="staff",
    )
    id_number = models.CharField(max_length=20, unique=True)
    is_teacher = models.BooleanField(
        default=False,
        help_text="Direct flag to mark staff as teacher, independent of position",
    )

    user_account_id_number = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        default=None,
        help_text="User ID number (string reference to User.id_number in public schema). Loose coupling instead of cross-schema FK."
    )

    suspension_date = models.DateField(null=True, blank=True)
    suspension_reason = models.TextField(null=True, blank=True)
    termination_date = models.DateField(null=True, blank=True)
    termination_reason = models.TextField(null=True, blank=True)
    
    # Manager relationship - self-referential for hierarchical structure
    manager = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='subordinates',
        help_text="The staff member who manages this person"
    )

    # --- MANAGER FIX ---
    # We use a helper to import the manager only when the class is being initialized.
    # This prevents the "NoneType" error and avoids circular imports.
    def _get_staff_manager():
        from staff.managers import StaffManager
        return StaffManager()
    
    objects = _get_staff_manager()

    class Meta:
        db_table = 'staff'
        constraints = [
            models.UniqueConstraint(
                fields=["id_number"],
                name="staff_uniq_id_number_per_tenant",
                condition=~models.Q(id_number=""),
            )
        ]
        ordering = ["last_name", "first_name"]

    def __str__(self):
        return f"{self.last_name}, {self.first_name}"

    def get_full_name(self):
        parts = [self.first_name]
        if self.middle_name:
            parts.append(self.middle_name)
        parts.append(self.last_name)
        return " ".join(parts)

    @property
    def photo_url(self):
        """Return photo URL if exists, otherwise None"""
        return self.photo.url if self.photo else None

    @property
    def current_position(self):
        # Safely handle the related name if history doesn't exist
        if not hasattr(self, 'position_histories'):
            return None
        history = self.position_histories.filter(end_date__isnull=True).first()
        return history.position if history else None

    def get_all_subordinates(self):
        """
        Get all subordinates (direct and indirect) of this staff member.
        Used to prevent circular manager assignments.
        """
        subordinates = set()
        direct = self.subordinates.all()
        subordinates.update(direct)
        
        # Recursively get subordinates of subordinates
        for sub in direct:
            subordinates.update(sub.get_all_subordinates())
        
        return subordinates
    
    def can_be_manager_of(self, potential_manager):
        """
        Check if a staff member can be a manager of this person.
        
        Rules:
        - Cannot be self
        - Cannot be someone this person manages
        - Cannot be someone below this person in hierarchy
        
        Returns: (is_valid, error_message)
        """
        if not potential_manager:
            return True, None
        
        # Cannot be self
        if self.id == potential_manager.id:
            return False, "A staff member cannot be their own manager"
        
        # Cannot be someone this person already manages
        all_subordinates = self.get_all_subordinates()
        if potential_manager.id in [sub.id for sub in all_subordinates]:
            return False, "Manager cannot be someone you are managing (would create a circular dependency)"
        
        return True, None


class TeacherSection(BaseModel):
    teacher = models.ForeignKey(
        "staff.Staff", on_delete=models.CASCADE, related_name="classes"
    )
    section = models.ForeignKey(
        "academics.Section", on_delete=models.CASCADE, related_name="staff_teachers"
    )
    created_by = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_staff_teachersection_set",
        to_field="id",
        blank=True,
        default=None,
    )
    updated_by = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="updated_staff_teachersection_set",
        to_field="id",
        blank=True,
        default=None,
    )

    class Meta:
        db_table = 'teacher_section'


class TeacherSubject(BaseModel):
    teacher = models.ForeignKey(
        "staff.Staff", on_delete=models.CASCADE, related_name="subjects"
    )
    subject = models.ForeignKey(
        "academics.Subject", on_delete=models.CASCADE, related_name="staff_teachers"
    )
    created_by = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_staff_teachersubject_set",
        to_field="id",
        blank=True,
        default=None,
    )
    updated_by = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="updated_staff_teachersubject_set",
        to_field="id",
        blank=True,
        default=None,
    )

    class Meta:
        db_table = 'teacher_subject'


class TeacherSchedule(BaseModel):
    class_schedule = models.ForeignKey(
        "academics.SectionSchedule", on_delete=models.CASCADE, related_name="staff_teachers"
    )
    teacher = models.ForeignKey(
        "staff.Staff", on_delete=models.CASCADE, related_name="schedules"
    )
    created_by = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_staff_teacherschedule_set",
        to_field="id",
        blank=True,
        default=None,
    )
    updated_by = models.ForeignKey(
        "users.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="updated_staff_teacherschedule_set",
        to_field="id",
        blank=True,
        default=None,
    )

    class Meta:
        db_table = 'teacher_schedule'
