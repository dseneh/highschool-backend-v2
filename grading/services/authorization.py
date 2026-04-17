from django.db.models import Q
from rest_framework.exceptions import PermissionDenied

from common.status import Roles
from staff.models import Staff, TeacherSection, TeacherSubject


def _get_teacher_staff(user):
    """
    Resolve the current user to a staff record when the user is a teacher.
    Non-teacher users return None and are handled by role-based access policy.
    """
    if not user or not user.is_authenticated:
        return None

    if user.role != Roles.TEACHER:
        return None

    staff = Staff.objects.filter(
        Q(user_account_id_number=user.id_number) | Q(id_number=user.id_number)
    ).only("id", "is_teacher").first()

    if not staff or not staff.is_teacher:
        raise PermissionDenied("Teacher profile not found or not marked as teacher.")

    return staff


def _get_teacher_staff_by_id_number(teacher_id_number):
    """Resolve a teacher staff record by staff id_number or hr.Employee id_number."""
    if not teacher_id_number:
        return None

    # Try Staff model first
    staff = Staff.objects.filter(id_number=teacher_id_number).only("id", "id_number", "is_teacher").first()

    # Fallback: look up via hr.Employee → user_account_id_number → Staff
    if not staff:
        from hr.models import Employee

        employee = Employee.objects.filter(
            id_number=teacher_id_number
        ).only("user_account_id_number").first()

        if employee and employee.user_account_id_number:
            staff = Staff.objects.filter(
                Q(user_account_id_number=employee.user_account_id_number)
                | Q(id_number=employee.user_account_id_number)
            ).only("id", "id_number", "is_teacher").first()

    if not staff or not staff.is_teacher:
        raise PermissionDenied("Selected staff is not a valid teacher.")

    return staff


def _get_teacher_section_ids(staff_id):
    return set(
        TeacherSection.objects.filter(teacher_id=staff_id).values_list("section_id", flat=True)
    )


def get_teacher_allowed_section_ids_for_subject(user, subject_id):
    """
    Return section ids a teacher can access for a given subject.

    Rules:
    - Teacher must be assigned to the section (TeacherSection)
    - Subject permission can be section-scoped (TeacherSubject.section_subject)
      or teacher-subject scoped (TeacherSubject.subject).
    """
    teacher_staff = _get_teacher_staff(user)
    if not teacher_staff:
        return None

    section_ids = _get_teacher_section_ids(teacher_staff.id)
    if not section_ids:
        return set()

    section_scoped_subject_sections = set(
        TeacherSubject.objects.filter(
            teacher_id=teacher_staff.id,
            section_subject__subject_id=subject_id,
            section_subject__section_id__in=section_ids,
        ).values_list("section_subject__section_id", flat=True)
    )

    has_general_subject_assignment = TeacherSubject.objects.filter(
        teacher_id=teacher_staff.id,
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

    if section_id not in allowed_sections:
        raise PermissionDenied(
            "You are not assigned to this class/subject."
        )


def get_teacher_allowed_section_ids(user):
    """
    Return all section IDs a teacher is assigned to (across all subjects).
    Returns None for non-teachers (meaning no teacher-based filtering needed).
    Returns empty set if teacher has no section assignments.
    """
    teacher_staff = _get_teacher_staff(user)
    if not teacher_staff:
        return None
    
    return _get_teacher_section_ids(teacher_staff.id)


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
        if user.role == Roles.TEACHER and user.id_number != teacher_id_number:
            raise PermissionDenied("Teachers can only access their own gradebooks.")

        teacher_staff = _get_teacher_staff_by_id_number(teacher_id_number)
    else:
        teacher_staff = _get_teacher_staff(user)
        if not teacher_staff:
            return None

    section_ids = _get_teacher_section_ids(teacher_staff.id)

    explicit_section_subject_ids = set(
        TeacherSubject.objects.filter(
            teacher_id=teacher_staff.id,
            section_subject__isnull=False,
        ).values_list("section_subject_id", flat=True)
    )

    # "General" subject assignment means subject is assigned to teacher
    # but not tied to one specific section_subject row.
    general_subject_ids = set(
        TeacherSubject.objects.filter(
            teacher_id=teacher_staff.id,
            section_subject__isnull=True,
        ).values_list("subject_id", flat=True)
    )

    return {
        "explicit_section_subject_ids": explicit_section_subject_ids,
        "general_subject_ids": general_subject_ids,
        "section_ids": section_ids,
    }
