from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .enums import ApplicationStatus
from .models import AdmissionApplication, ApplicationStatusHistory


ALLOWED_TRANSITIONS = {
    ApplicationStatus.DRAFT: {ApplicationStatus.SUBMITTED, ApplicationStatus.WITHDRAWN},
    ApplicationStatus.SUBMITTED: {ApplicationStatus.UNDER_REVIEW, ApplicationStatus.WITHDRAWN, ApplicationStatus.CANCELLED},
    ApplicationStatus.UNDER_REVIEW: {ApplicationStatus.INFORMATION_REQUESTED, ApplicationStatus.APPROVED, ApplicationStatus.REJECTED, ApplicationStatus.CANCELLED},
    ApplicationStatus.INFORMATION_REQUESTED: {ApplicationStatus.INFORMATION_RECEIVED, ApplicationStatus.WITHDRAWN, ApplicationStatus.CANCELLED},
    ApplicationStatus.INFORMATION_RECEIVED: {ApplicationStatus.UNDER_REVIEW, ApplicationStatus.APPROVED, ApplicationStatus.REJECTED},
    ApplicationStatus.APPROVED: {ApplicationStatus.ENROLLMENT_READY, ApplicationStatus.CANCELLED},
    ApplicationStatus.ENROLLMENT_READY: {ApplicationStatus.ENROLLED, ApplicationStatus.CANCELLED},
    ApplicationStatus.REJECTED: set(),
    ApplicationStatus.WITHDRAWN: set(),
    ApplicationStatus.ENROLLED: set(),
    ApplicationStatus.CANCELLED: set(),
}


@transaction.atomic
def transition_application(*, application, to_status, actor=None, reason="", metadata=None):
    locked = AdmissionApplication.objects.select_for_update().get(pk=application.pk)
    if to_status not in ALLOWED_TRANSITIONS.get(locked.status, set()):
        raise ValidationError(f"Cannot transition application from '{locked.status}' to '{to_status}'.")
    previous = locked.status
    locked.status = to_status
    locked.version += 1
    locked.updated_by = actor
    update_fields = ["status", "version", "updated_by", "updated_at"]
    if to_status == ApplicationStatus.SUBMITTED:
        locked.submitted_at = timezone.now()
        locked.submission_snapshot = {
            "student_profile": locked.student_profile,
            "guardian_profiles": locked.guardian_profiles,
            "previous_school_records": locked.previous_school_records,
            "proposed_student_changes": locked.proposed_student_changes,
            "consents": locked.consents,
        }
        update_fields.extend(["submitted_at", "submission_snapshot"])
    if to_status in {ApplicationStatus.APPROVED, ApplicationStatus.REJECTED}:
        locked.decision_at = timezone.now()
        update_fields.append("decision_at")
    locked.save(update_fields=update_fields)
    ApplicationStatusHistory.objects.create(
        application=locked, from_status=previous, to_status=to_status,
        reason=reason, metadata=metadata or {}, created_by=actor, updated_by=actor,
    )
    return locked
