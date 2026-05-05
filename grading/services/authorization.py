from django.db.models import Q
from rest_framework.exceptions import PermissionDenied

from common.status import Roles
from hr.models import Employee, EmployeeTeacherSection, EmployeeTeacherSubject


def _is_teacher_role(user) -> bool:
    return (getattr(user, "role", "") or "").strip().lower() == Roles.TEACHER


def _find_employee_for_user(user):
    if not user:
        return None
    return (
        Employee.objects.filter(
            Q(user_account_id_number=user.id_number) | Q(id_number=user.id_number)
        )
        .only("id", "id_number", "user_account_id_number", "is_teacher")
        .first()
    )


def _find_employee_by_id_number(teacher_id_number):
    if not teacher_id_number:
        return None

    return (
        Employee.objects.filter(
            Q(id_number=teacher_id_number) | Q(user_account_id_number=teacher_id_number)
        )
        .only("id", "id_number", "user_account_id_number", "is_teacher")
        .first()
    )


def _is_teacher_user(user) -> bool:
    if _is_teacher_role(user):
        return True
    employee = _find_employee_for_user(user)
    return bool(employee and employee.is_teacher)


def _get_teacher_employee(user):
    """
    Resolve the current user to a staff record when the user is a teacher.
    Non-teacher users return None and are handled by role-based access policy.
    """
    if not user or not user.is_authenticated:
        return None

    employee = _find_employee_for_user(user)
    has_teacher_flag = bool(employee and employee.is_teacher)

    if not _is_teacher_role(user):
        # Non-teacher roles are only treated as teacher when the HR employee record is marked as teacher.
        if has_teacher_flag:
            return employee
        return None

    if not has_teacher_flag:
        raise PermissionDenied("Teacher profile not found or not marked as teacher.")

    return employee


def _get_teacher_employee_by_id_number(teacher_id_number):
    """Resolve a teacher employee record by HR employee id_number or linked user id number."""
    if not teacher_id_number:
        return None

    employee = _find_employee_by_id_number(teacher_id_number)
    if not employee or not employee.is_teacher:
        raise PermissionDenied("Selected staff is not a valid teacher.")

    return employee


def _get_teacher_section_ids(teacher_id):
    return set(
        EmployeeTeacherSection.objects.filter(teacher_id=teacher_id).values_list("section_id", flat=True)
    )


def get_teacher_allowed_section_ids_for_subject(user, subject_id):
    """
    Return section ids a teacher can access for a given subject.

    Rules:
    - Teacher must be assigned to the section (TeacherSection)
    - Subject permission can be section-scoped (TeacherSubject.section_subject)
      or teacher-subject scoped (TeacherSubject.subject).
    """
    teacher_employee = _get_teacher_employee(user)
    if not teacher_employee:
        return None

    section_ids = _get_teacher_section_ids(teacher_employee.id)
    if not section_ids:
        return set()

    section_scoped_subject_sections = set(
        EmployeeTeacherSubject.objects.filter(
            teacher_id=teacher_employee.id,
            section_subject__subject_id=subject_id,
            section_subject__section_id__in=section_ids,
        ).values_list("section_subject__section_id", flat=True)
    )

    has_general_subject_assignment = EmployeeTeacherSubject.objects.filter(
        teacher_id=teacher_employee.id,
        subject_id=subject_id,
        section_subject__isnull=True,
    ).exists()

    if has_general_subject_assignment:
        return section_ids

    return section_scoped_subject_sections


def enforce_teacher_grade_access(user, section_id, subject_id):
    """
    Enforce teacher ownership for grading operations.
    Non-teacher users are allowed through and handled by role/privilege policies.
    """
    allowed_sections = get_teacher_allowed_section_ids_for_subject(user, subject_id)
    if allowed_sections is None:
        return

    # Normalize to str for comparison: section_id may be a str (from URL params)
    # while allowed_sections contains uuid.UUID objects from values_list().
    normalized = str(section_id)
    if normalized not in {str(s) for s in allowed_sections}:
        raise PermissionDenied(
            "You are not assigned to this class/subject."
        )


def get_teacher_allowed_section_ids(user):
    """
    Return all section IDs a teacher is assigned to (across all subjects).
    Returns None for non-teachers (meaning no teacher-based filtering needed).
    Returns empty set if teacher has no section assignments.
    """
    teacher_employee = _get_teacher_employee(user)
    if not teacher_employee:
        return None
    
    return _get_teacher_section_ids(teacher_employee.id)


def get_teacher_gradebook_scope(user, teacher_id_number=None):
    """
    Return teacher gradebook scope for list filtering.

    Shape:
    {
        "explicit_section_subject_ids": set[str],
        "general_subject_ids": set[str],
        "section_ids": set[str],
    }

    - Non-teacher users return None (no teacher-specific filtering needed).
    - Teachers with no assignments return empty sets.
    """
    # If a specific teacher is requested, only admin/registrar can scope by another teacher.
    if teacher_id_number:
        if _is_teacher_user(user) and user.id_number != teacher_id_number:
            raise PermissionDenied("Teachers can only access their own gradebooks.")

        teacher_employee = _get_teacher_employee_by_id_number(teacher_id_number)
    else:
        teacher_employee = _get_teacher_employee(user)
        if not teacher_employee:
            return None

    section_ids = _get_teacher_section_ids(teacher_employee.id)

    explicit_section_subject_ids = set(
        EmployeeTeacherSubject.objects.filter(
            teacher_id=teacher_employee.id,
            section_subject__isnull=False,
        ).values_list("section_subject_id", flat=True)
    )

    # "General" subject assignment means subject is assigned to teacher
    # but not tied to one specific section_subject row.
    general_subject_ids = set(
        EmployeeTeacherSubject.objects.filter(
            teacher_id=teacher_employee.id,
            section_subject__isnull=True,
        ).values_list("subject_id", flat=True)
    )

    return {
        "explicit_section_subject_ids": explicit_section_subject_ids,
        "general_subject_ids": general_subject_ids,
        "section_ids": section_ids,
    }
