from __future__ import annotations

import logging
import uuid
from typing import Set

from django.db import connection
from django_tenants.utils import schema_context

from common.status import PersonStatus, Roles, UserAccountType
from notifications.services.teacher_scope import assert_teacher_can_target_audience
from users.models import User

logger = logging.getLogger(__name__)


def get_tenant_user_queryset():
    """Users with access to the current tenant schema.

    NOTE: We intentionally do NOT exclude users whose emails end with
    ``@local.user``. Those are placeholder emails assigned to students /
    teachers / parents who did not provide a real address, but they are
    still valid in-app recipients. The placeholder email is only relevant
    for the email channel, which gates itself via ``user_wants_email``.

    We resolve membership via the ``User.tenants`` M2M (lives in the
    public schema) instead of querying tenant-local ``UserTenantPermissions``
    rows. The M2M is the source-of-truth populated by ``tenant.add_user``,
    and it survives schema context switches without surprises.
    """
    current_schema = connection.schema_name
    public_schema = "public"
    if current_schema == public_schema:
        return User.objects.none()

    # Materialize the User ids in the public schema to avoid relying on
    # the search_path when the caller later iterates the queryset.
    with schema_context(public_schema):
        user_ids = list(
            User.objects.filter(
                tenants__schema_name=current_schema,
                is_active=True,
                status=PersonStatus.ACTIVE,
            )
            .values_list("id", flat=True)
            .distinct()
        )
        logger.info(
            "notifications.audience.get_tenant_user_queryset schema=%s found %d user(s)",
            current_schema,
            len(user_ids),
        )

        # Fallback: legacy tenants where the M2M wasn't populated.
        if not user_ids:
            from tenant_users.permissions.models import UserTenantPermissions

            with schema_context(current_schema):
                profile_ids = list(
                    UserTenantPermissions.objects.values_list(
                        "profile_id", flat=True
                    ).distinct()
                )
            if profile_ids:
                user_ids = list(
                    User.objects.filter(
                        id__in=profile_ids,
                        is_active=True,
                        status=PersonStatus.ACTIVE,
                    ).values_list("id", flat=True)
                )
                logger.info(
                    "notifications.audience.get_tenant_user_queryset schema=%s "
                    "fallback via UserTenantPermissions found %d user(s)",
                    current_schema,
                    len(user_ids),
                )

        return User.objects.filter(id__in=user_ids)


def resolve_user_ids(audience: dict, sender: User, *, category: str = "") -> Set[uuid.UUID]:
    audience = audience or {}
    assert_teacher_can_target_audience(sender, audience)

    scope = audience.get("scope", "all")
    ids: Set[uuid.UUID] = set()

    if scope == "all":
        qs = get_tenant_user_queryset()
        if category in ("grade", "finance"):
            qs = qs.filter(
                role__in=[Roles.STUDENT, Roles.PARENT],
            )
        ids.update(qs.values_list("id", flat=True))
        return ids

    if scope == "roles":
        roles = [r.lower() for r in (audience.get("roles") or [])]
        if roles:
            from django.db.models import Q

            role_filter = Q()
            for role in roles:
                role_filter |= Q(role__iexact=role)
            ids.update(
                get_tenant_user_queryset()
                .filter(role_filter)
                .values_list("id", flat=True)
            )
        return ids

    if scope == "student_and_parents":
        student_ids = list(audience.get("student_ids") or [])
        ids.update(
            _resolve_student_scope_user_ids(
                {"scope": "students", "student_ids": student_ids}, "students"
            )
        )
        ids.update(
            _resolve_student_scope_user_ids(
                {"scope": "parents_of_students", "student_ids": student_ids},
                "parents_of_students",
            )
        )
        return ids

    if scope == "user_ids":
        raw = audience.get("user_ids") or []
        tenant_ids = set(get_tenant_user_queryset().values_list("id", flat=True))
        for uid in raw:
            try:
                parsed = uuid.UUID(str(uid))
                if parsed in tenant_ids:
                    ids.add(parsed)
            except (ValueError, TypeError):
                continue
        return ids

    student_user_ids = _resolve_student_scope_user_ids(audience, scope)
    ids.update(student_user_ids)
    return ids


def _resolve_student_scope_user_ids(audience: dict, scope: str) -> Set[uuid.UUID]:
    from students.models import Enrollment, Student, StudentGuardian

    section_ids = list(audience.get("section_ids") or [])
    grade_level_ids = audience.get("grade_level_ids") or []
    student_ids = list(audience.get("student_ids") or [])

    enrollment_qs = Enrollment.objects.filter(active=True)
    if student_ids:
        enrollment_qs = enrollment_qs.filter(student_id__in=student_ids)
    elif section_ids:
        enrollment_qs = enrollment_qs.filter(section_id__in=section_ids)
    elif grade_level_ids:
        enrollment_qs = enrollment_qs.filter(grade_level_id__in=grade_level_ids)
    else:
        return set()

    students = Student.objects.filter(
        id__in=enrollment_qs.values_list("student_id", flat=True),
        active=True,
    )

    result: Set[uuid.UUID] = set()
    tenant_users = get_tenant_user_queryset()

    if scope in ("grade_sections", "students"):
        id_numbers = [
            x
            for x in students.exclude(user_account_id_number__isnull=True)
            .exclude(user_account_id_number="")
            .values_list("user_account_id_number", flat=True)
            if x
        ]
        if id_numbers:
            result.update(
                tenant_users.filter(id_number__in=id_numbers).values_list("id", flat=True)
            )

    if scope in ("grade_sections", "parents_of_students"):
        guardian_id_numbers = StudentGuardian.objects.filter(
            student__in=students,
            active=True,
        ).exclude(user_account_id_number__isnull=True).exclude(
            user_account_id_number=""
        ).values_list("user_account_id_number", flat=True)
        if guardian_id_numbers:
            result.update(
                tenant_users.filter(id_number__in=guardian_id_numbers).values_list(
                    "id", flat=True
                )
            )

    return result


def user_wants_email(user_id: uuid.UUID, category: str) -> bool:
    from notifications.models import UserNotificationPreference

    with schema_context("public"):
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return False
        if not user.email or user.email.endswith("@local.user"):
            return False

    pref = UserNotificationPreference.objects.filter(user_id=user_id).first()
    if pref is None:
        return True
    if not pref.email_enabled:
        return False
    muted = pref.muted_categories or []
    return category not in muted
