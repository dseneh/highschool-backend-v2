from __future__ import annotations

import uuid
from typing import Optional

from rest_framework.exceptions import PermissionDenied

from hr.models import Employee, EmployeeTeacherSection


def get_employee_for_user(user) -> Optional[Employee]:
    if not user or not getattr(user, "is_authenticated", False):
        return None
    id_number = getattr(user, "id_number", None)
    if not id_number:
        return None
    return (
        Employee.objects.filter(user_account_id_number=id_number, active=True)
        .select_related("department", "position")
        .first()
    )


def get_teacher_section_ids(user) -> set[uuid.UUID]:
    employee = get_employee_for_user(user)
    if not employee:
        return set()
    return set(
        EmployeeTeacherSection.objects.filter(teacher=employee).values_list(
            "section_id", flat=True
        )
    )


def get_section_ids_for_students(student_ids: list) -> set[uuid.UUID]:
    if not student_ids:
        return set()
    from students.models import Enrollment

    return set(
        Enrollment.objects.filter(
            student_id__in=student_ids,
            active=True,
        ).values_list("section_id", flat=True)
    )


def assert_teacher_can_target_audience(user, audience: dict) -> None:
    """Raise PermissionDenied if teacher audience exceeds assigned sections."""
    from common.status import Roles

    role = (getattr(user, "role", "") or "").lower()
    if role not in {Roles.TEACHER}:
        return

    allowed = get_teacher_section_ids(user)
    if not allowed:
        raise PermissionDenied(
            "No employee record or section assignments found for this teacher."
        )

    scope = (audience or {}).get("scope", "")
    if scope in ("all", "roles"):
        raise PermissionDenied("Teachers cannot send school-wide or role-based broadcasts.")

    section_ids = {uuid.UUID(str(s)) for s in (audience.get("section_ids") or [])}
    grade_level_ids = audience.get("grade_level_ids") or []

    if grade_level_ids and not section_ids:
        from academics.models import Section

        section_ids = set(
            Section.objects.filter(grade_level_id__in=grade_level_ids).values_list(
                "id", flat=True
            )
        )

    student_ids = audience.get("student_ids") or []
    if student_ids:
        implied = get_section_ids_for_students(student_ids)
        section_ids = section_ids | implied

    if section_ids and not section_ids.issubset(allowed):
        raise PermissionDenied(
            "You can only send notifications to sections you are assigned to teach."
        )

    if scope in ("grade_sections", "students", "parents_of_students") and not (
        section_ids or student_ids
    ):
        raise PermissionDenied("Specify at least one section or student for class notifications.")
