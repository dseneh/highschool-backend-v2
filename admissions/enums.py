from django.db import models


class ApplicationType(models.TextChoices):
    NEW_ADMISSION = "new_admission", "New admission"
    RETURNING_REGISTRATION = "returning_registration", "Returning registration"


class ApplicationStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    SUBMITTED = "submitted", "Submitted"
    UNDER_REVIEW = "under_review", "Under review"
    INFORMATION_REQUESTED = "information_requested", "Information requested"
    INFORMATION_RECEIVED = "information_received", "Information received"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"
    WITHDRAWN = "withdrawn", "Withdrawn"
    ENROLLMENT_READY = "enrollment_ready", "Enrollment ready"
    ENROLLED = "enrolled", "Enrolled"
    CANCELLED = "cancelled", "Cancelled"
