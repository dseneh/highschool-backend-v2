"""ETag helpers for student detail responses."""

from django.db.models import Max, Q

from common.http_etag import build_etag
from students.models import Enrollment


def student_detail_etag(student) -> str:
    """Fingerprint student detail payload including related enrollment/user churn."""
    enrollment_latest = (
        Enrollment.objects.filter(student_id=student.id).aggregate(latest=Max("updated_at"))
    ).get("latest")

    user_fingerprint = (None, None, None, None, None)
    lookup_filter = Q()
    for value in (student.user_account_id_number, student.id_number):
        if value:
            lookup_filter |= Q(id_number=value)
    if lookup_filter:
        from users.models import User

        user = (
            User.objects.filter(lookup_filter)
            .only(
                "last_login",
                "last_password_updated",
                "status",
                "is_active",
                "photo",
            )
            .first()
        )
        if user:
            user_fingerprint = (
                user.last_login,
                user.last_password_updated,
                user.status,
                user.is_active,
                user.photo,
            )

    return build_etag(
        student.id,
        student.updated_at,
        enrollment_latest,
        *user_fingerprint,
        student.status,
        student.photo,
    )
