from django.core.exceptions import ValidationError
from django.db import models, transaction
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

APPLICANT_UPLOAD_STATUSES = {
    ApplicationStatus.DRAFT,
    ApplicationStatus.INFORMATION_REQUESTED,
    ApplicationStatus.INFORMATION_RECEIVED,
}


def applicable_document_requirements(application):
    requirements = application.cycle.document_requirements.filter(
        active=True,
        application_type=application.application_type,
    )
    if application.requested_grade_level_id:
        requirements = requirements.filter(
            models.Q(grade_level__isnull=True)
            | models.Q(grade_level_id=application.requested_grade_level_id)
        )
    else:
        requirements = requirements.filter(grade_level__isnull=True)
    return requirements


def application_submission_errors(application):
    errors = {}
    required_student_fields = {"first_name", "last_name", "date_of_birth", "gender"}
    missing_student = sorted(field for field in required_student_fields if not application.student_profile.get(field))
    if missing_student:
        errors["student_profile"] = f"Missing required fields: {', '.join(missing_student)}."
    if not application.guardian_profiles:
        errors["guardian_profiles"] = "At least one guardian or responsible contact is required."
    required_consents = {"information_accurate", "data_processing"}
    missing_consents = sorted(field for field in required_consents if application.consents.get(field) is not True)
    if missing_consents:
        errors["consents"] = f"Required declarations are incomplete: {', '.join(missing_consents)}."

    requirements = applicable_document_requirements(application).filter(required=True)
    uploaded_requirement_ids = set(application.documents.values_list("requirement_id", flat=True))
    missing_documents = [item.name for item in requirements if item.id not in uploaded_requirement_ids]
    if missing_documents:
        errors["documents"] = f"Missing required documents: {', '.join(missing_documents)}."
    return errors


def application_approval_errors(application):
    errors = {}
    requirements = applicable_document_requirements(application).filter(required=True)
    for requirement in requirements:
        document = application.documents.filter(requirement=requirement).first()
        if document is None:
            errors[str(requirement.id)] = f"{requirement.name} has not been uploaded."
        elif document.scan_status != document.ScanStatus.CLEAN:
            errors[str(requirement.id)] = f"{requirement.name} has not passed its security scan."
        elif document.review_status != document.ReviewStatus.ACCEPTED:
            errors[str(requirement.id)] = f"{requirement.name} has not been accepted."
    return errors


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
