"""RBAC scope helpers for primary student-record endpoints."""

from __future__ import annotations

from django.db.models import Q, QuerySet

def permission_scope(request, permission_code: str) -> str | None:
    permission_scope = getattr(request, "permission_scope", None)
    if callable(permission_scope):
        return permission_scope(permission_code)

    user = getattr(request, "user", None)
    if not user or not getattr(user, "is_authenticated", False):
        return None

    from authorization.runtime import initialize_request_authorization

    return initialize_request_authorization(request, user).permission_scope(permission_code)


def student_view_scope(request) -> str | None:
    return permission_scope(request, "students.view")


def filter_students_for_view_scope(queryset: QuerySet, request) -> QuerySet:
    return filter_students_for_permission_scope(
        queryset,
        request,
        "students.view",
    )


def filter_students_for_permission_scope(
    queryset: QuerySet,
    request,
    permission_code: str,
) -> QuerySet:
    """Constrain students to the caller's RBAC read scope.

    All scopes are enforced by this helper, with unknown scopes failing closed.
    """
    scope = permission_scope(request, permission_code)
    if scope == "all":
        return queryset
    if scope == "own":
        from students.models import StudentGuardian

        user_id_number = getattr(request.user, "id_number", "")
        guardian_student_ids = StudentGuardian.objects.filter(
            user_account_id_number=user_id_number,
            active=True,
        ).values("student_id")
        return queryset.filter(
            Q(user_account_id_number=user_id_number)
            | Q(id__in=guardian_student_ids)
        ).distinct()
    if scope == "assigned":
        from hr.models import Employee, EmployeeTeacherSection
        from staff.models import Staff, TeacherSection

        user_id_number = getattr(request.user, "id_number", "")
        employee = Employee.objects.filter(
            Q(user_account_id_number=user_id_number) | Q(id_number=user_id_number),
            is_teacher=True,
        ).only("id").first()
        staff = Staff.objects.filter(
            Q(user_account_id_number=user_id_number) | Q(id_number=user_id_number)
        ).only("id").first()
        section_ids = set()
        if employee is not None:
            section_ids.update(
                EmployeeTeacherSection.objects.filter(teacher=employee).values_list(
                    "section_id", flat=True
                )
            )
        if staff is not None:
            section_ids.update(
                TeacherSection.objects.filter(teacher=staff).values_list(
                    "section_id", flat=True
                )
            )
        if not section_ids:
            return queryset.none()
        return queryset.filter(
            enrollments__academic_year__current=True,
            enrollments__section_id__in=section_ids,
        ).distinct()
    return queryset.none()


def user_can_view_student(student, request) -> bool:
    return filter_students_for_view_scope(
        student.__class__.objects.filter(pk=student.pk), request
    ).exists()


def user_can_access_student_for_permission(
    student,
    request,
    permission_code: str,
) -> bool:
    return filter_students_for_permission_scope(
        student.__class__.objects.filter(pk=student.pk),
        request,
        permission_code,
    ).exists()


def user_has_all_student_view_scope(request) -> bool:
    return student_view_scope(request) == "all"