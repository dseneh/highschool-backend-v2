"""Scope enforcement for grading read endpoints."""

from __future__ import annotations

from django.db.models import Q, QuerySet
from rest_framework.exceptions import PermissionDenied

from authorization.runtime import initialize_request_authorization
from grading.services.authorization import (
    get_teacher_allowed_section_ids,
    get_teacher_allowed_section_ids_for_subject,
    get_teacher_gradebook_scope,
)
from students.models import Enrollment, Student, StudentGuardian


DENIED_MESSAGE = "You do not have permission to view this grading data."


def grading_view_scope(request) -> str | None:
    return initialize_request_authorization(
        request,
        request.user,
    ).permission_scope("grades.view")


def accessible_student_ids(user) -> set:
    id_number = getattr(user, "id_number", "")
    if not id_number:
        return set()

    student_ids = set(
        Student.objects.filter(user_account_id_number=id_number).values_list(
            "id", flat=True
        )
    )
    student_ids.update(
        StudentGuardian.objects.filter(
            user_account_id_number=id_number,
            active=True,
        ).values_list("student_id", flat=True)
    )
    return student_ids


def filter_gradebooks_for_view_scope(queryset: QuerySet, request) -> QuerySet:
    scope = grading_view_scope(request)
    if scope == "all":
        return queryset
    if scope == "assigned":
        teacher_scope = get_teacher_gradebook_scope(request.user)
        if teacher_scope is None:
            return queryset.none()
        return queryset.filter(
            Q(section_subject_id__in=teacher_scope["explicit_section_subject_ids"])
            | Q(
                subject_id__in=teacher_scope["general_subject_ids"],
                section_id__in=teacher_scope["section_ids"],
            )
        ).distinct()
    if scope == "own":
        student_ids = accessible_student_ids(request.user)
        if not student_ids:
            return queryset.none()
        return queryset.filter(
            assessments__grades__student_id__in=student_ids
        ).distinct()
    return queryset.none()


def user_can_view_gradebook(gradebook, request) -> bool:
    return filter_gradebooks_for_view_scope(
        gradebook.__class__.objects.filter(pk=gradebook.pk),
        request,
    ).exists()


def filter_grades_for_view_scope(queryset: QuerySet, request) -> QuerySet:
    scope = grading_view_scope(request)
    if scope == "all":
        return queryset
    if scope == "assigned":
        section_ids = get_teacher_allowed_section_ids(request.user)
        if section_ids is None:
            return queryset.none()
        return queryset.filter(section_id__in=section_ids)
    if scope == "own":
        student_ids = accessible_student_ids(request.user)
        return queryset.filter(student_id__in=student_ids)
    return queryset.none()


def user_can_view_grade(grade, request) -> bool:
    scope = grading_view_scope(request)
    if scope == "all":
        return True
    if scope == "own":
        return grade.student_id in accessible_student_ids(request.user)
    if scope == "assigned":
        section_ids = get_teacher_allowed_section_ids_for_subject(
            request.user,
            grade.subject_id,
        )
        return section_ids is not None and grade.section_id in section_ids
    return False


def user_can_view_student_grades(
    student,
    request,
    *,
    academic_year=None,
    gradebook=None,
) -> bool:
    scope = grading_view_scope(request)
    if scope == "all":
        return True
    if scope == "own":
        return student.id in accessible_student_ids(request.user)
    if scope != "assigned":
        return False

    if gradebook is not None:
        section_ids = get_teacher_allowed_section_ids_for_subject(
            request.user,
            gradebook.subject_id,
        )
        return section_ids is not None and gradebook.section_id in section_ids

    section_ids = get_teacher_allowed_section_ids(request.user)
    if section_ids is None:
        return False
    enrollments = Enrollment.objects.filter(
        student=student,
        section_id__in=section_ids,
    )
    if academic_year is not None:
        enrollments = enrollments.filter(academic_year=academic_year)
    return enrollments.exists()


def user_can_view_section_grades(section_id, request, *, subject_id=None) -> bool:
    scope = grading_view_scope(request)
    if scope == "all":
        return True
    if scope != "assigned":
        return False
    if subject_id:
        section_ids = get_teacher_allowed_section_ids_for_subject(
            request.user,
            subject_id,
        )
    else:
        section_ids = get_teacher_allowed_section_ids(request.user)
    return section_ids is not None and str(section_id) in {
        str(value) for value in section_ids
    }


def require_scope_access(allowed: bool) -> None:
    if not allowed:
        raise PermissionDenied(DENIED_MESSAGE)


def require_all_grading_view_scope(request) -> None:
    require_scope_access(grading_view_scope(request) == "all")


def require_all_grading_scope(request, permission_code: str) -> None:
    scope = initialize_request_authorization(
        request,
        request.user,
    ).permission_scope(permission_code)
    require_scope_access(scope == "all")
