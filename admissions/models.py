import uuid

from django.core.validators import FileExtensionValidator
from django.db import models

from common.models import BaseModel
from core.storage import PrivateTenantAwareS3Storage

from .enums import ApplicationStatus, ApplicationType
from .request_ids import generate_request_id


private_document_storage = PrivateTenantAwareS3Storage()


def application_document_path(instance, filename):
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    return f"admissions/{instance.application.request_id}/{uuid.uuid4().hex}.{extension}"


class AdmissionCycle(BaseModel):
    name = models.CharField(max_length=160)
    academic_year = models.ForeignKey("academics.AcademicYear", on_delete=models.PROTECT, related_name="admission_cycles")
    opens_at = models.DateTimeField()
    closes_at = models.DateTimeField()
    new_admissions_open = models.BooleanField(default=True)
    returning_registration_open = models.BooleanField(default=True)
    eligible_grade_levels = models.ManyToManyField("academics.GradeLevel", blank=True, related_name="admission_cycles")
    instructions = models.TextField(blank=True, default="")

    class Meta:
        db_table = "admission_cycle"
        ordering = ["-opens_at"]
        indexes = [models.Index(fields=["active", "opens_at", "closes_at"])]


class AdmissionApplication(BaseModel):
    request_id = models.CharField(max_length=32, unique=True, default=generate_request_id, editable=False)
    application_type = models.CharField(max_length=32, choices=ApplicationType.choices)
    cycle = models.ForeignKey(AdmissionCycle, on_delete=models.PROTECT, related_name="applications")
    status = models.CharField(max_length=32, choices=ApplicationStatus.choices, default=ApplicationStatus.DRAFT, db_index=True)
    applicant_name = models.CharField(max_length=255)
    applicant_email = models.EmailField(blank=True, default="")
    applicant_phone = models.CharField(max_length=32, blank=True, default="")
    returning_student = models.ForeignKey("students.Student", on_delete=models.PROTECT, null=True, blank=True, related_name="registration_applications")
    requested_grade_level = models.ForeignKey("academics.GradeLevel", on_delete=models.PROTECT, null=True, blank=True, related_name="admission_applications")
    assigned_reviewer = models.ForeignKey("users.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="assigned_admission_applications")
    student_profile = models.JSONField(default=dict, blank=True)
    guardian_profiles = models.JSONField(default=list, blank=True)
    previous_school_records = models.JSONField(default=list, blank=True)
    proposed_student_changes = models.JSONField(default=dict, blank=True)
    consents = models.JSONField(default=dict, blank=True)
    submission_snapshot = models.JSONField(default=dict, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    decision_at = models.DateTimeField(null=True, blank=True)
    version = models.PositiveIntegerField(default=1)

    class Meta:
        db_table = "admission_application"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["cycle", "status", "-created_at"]),
            models.Index(fields=["application_type", "status"]),
            models.Index(fields=["assigned_reviewer", "status"]),
            models.Index(fields=["applicant_email"]),
            models.Index(fields=["applicant_phone"]),
        ]


class ApplicantIdentity(BaseModel):
    application = models.OneToOneField(AdmissionApplication, on_delete=models.CASCADE, related_name="applicant_identity")
    email_verified_at = models.DateTimeField(null=True, blank=True)
    phone_verified_at = models.DateTimeField(null=True, blank=True)
    token_version = models.PositiveIntegerField(default=1)
    failed_attempts = models.PositiveSmallIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "applicant_identity"


class ApplicantAccessToken(BaseModel):
    application = models.ForeignKey(AdmissionApplication, on_delete=models.CASCADE, related_name="access_tokens")
    purpose = models.CharField(max_length=32)
    token_hash = models.CharField(max_length=128, unique=True)
    expires_at = models.DateTimeField(db_index=True)
    used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "applicant_access_token"
        indexes = [models.Index(fields=["application", "purpose", "expires_at"])]


class ApplicationDocumentRequirement(BaseModel):
    cycle = models.ForeignKey(AdmissionCycle, on_delete=models.CASCADE, related_name="document_requirements")
    application_type = models.CharField(max_length=32, choices=ApplicationType.choices)
    grade_level = models.ForeignKey("academics.GradeLevel", on_delete=models.CASCADE, null=True, blank=True, related_name="admission_document_requirements")
    name = models.CharField(max_length=160)
    instructions = models.TextField(blank=True, default="")
    required = models.BooleanField(default=True)
    allowed_extensions = models.JSONField(default=list, blank=True)
    max_size_bytes = models.PositiveBigIntegerField(default=10 * 1024 * 1024)

    class Meta:
        db_table = "application_document_requirement"
        ordering = ["name"]


class ApplicationDocument(BaseModel):
    class ScanStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        CLEAN = "clean", "Clean"
        REJECTED = "rejected", "Rejected"
        FAILED = "failed", "Failed"

    class ReviewStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        ACCEPTED = "accepted", "Accepted"
        REJECTED = "rejected", "Rejected"

    application = models.ForeignKey(AdmissionApplication, on_delete=models.CASCADE, related_name="documents")
    requirement = models.ForeignKey(ApplicationDocumentRequirement, on_delete=models.SET_NULL, null=True, blank=True, related_name="documents")
    file = models.FileField(
        upload_to=application_document_path,
        storage=private_document_storage,
        validators=[FileExtensionValidator(["pdf", "png", "jpg", "jpeg"])],
    )
    original_name = models.CharField(max_length=255)
    mime_type = models.CharField(max_length=120)
    size_bytes = models.PositiveBigIntegerField()
    checksum_sha256 = models.CharField(max_length=64, db_index=True)
    scan_status = models.CharField(max_length=16, choices=ScanStatus.choices, default=ScanStatus.PENDING, db_index=True)
    review_status = models.CharField(max_length=16, choices=ReviewStatus.choices, default=ReviewStatus.PENDING, db_index=True)
    review_note = models.TextField(blank=True, default="")

    class Meta:
        db_table = "application_document"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["application", "scan_status", "review_status"])]


class ApplicationMessage(BaseModel):
    class AuthorType(models.TextChoices):
        APPLICANT = "applicant", "Applicant"
        SCHOOL = "school", "School"
        SYSTEM = "system", "System"

    application = models.ForeignKey(AdmissionApplication, on_delete=models.CASCADE, related_name="messages")
    author_type = models.CharField(max_length=16, choices=AuthorType.choices)
    body = models.TextField()
    applicant_read_at = models.DateTimeField(null=True, blank=True)
    school_read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "application_message"
        ordering = ["created_at"]
        indexes = [models.Index(fields=["application", "created_at"])]


class ApplicationInformationRequest(BaseModel):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        RESPONDED = "responded", "Responded"
        RESOLVED = "resolved", "Resolved"
        CANCELLED = "cancelled", "Cancelled"

    application = models.ForeignKey(AdmissionApplication, on_delete=models.CASCADE, related_name="information_requests")
    title = models.CharField(max_length=160)
    instructions = models.TextField()
    due_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN, db_index=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "application_information_request"
        ordering = ["-created_at"]


class ApplicationPlacement(BaseModel):
    application = models.OneToOneField(AdmissionApplication, on_delete=models.CASCADE, related_name="placement")
    academic_year = models.ForeignKey("academics.AcademicYear", on_delete=models.PROTECT, related_name="admission_placements")
    grade_level = models.ForeignKey("academics.GradeLevel", on_delete=models.PROTECT, related_name="admission_placements")
    section = models.ForeignKey("academics.Section", on_delete=models.PROTECT, related_name="admission_placements")
    enrolled_as = models.CharField(max_length=20, choices=[("new", "New"), ("returning", "Returning"), ("transferred", "Transferred")])
    notes = models.TextField(blank=True, default="")

    class Meta:
        db_table = "application_placement"


class ApplicationStatusHistory(BaseModel):
    application = models.ForeignKey(AdmissionApplication, on_delete=models.CASCADE, related_name="status_history")
    from_status = models.CharField(max_length=32, blank=True, default="")
    to_status = models.CharField(max_length=32, choices=ApplicationStatus.choices)
    reason = models.TextField(blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "application_status_history"
        ordering = ["created_at"]
        indexes = [models.Index(fields=["application", "created_at"])]


class ApplicationConversion(BaseModel):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"

    application = models.OneToOneField(AdmissionApplication, on_delete=models.PROTECT, related_name="conversion")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    student = models.ForeignKey("students.Student", on_delete=models.PROTECT, null=True, blank=True, related_name="admission_conversions")
    enrollment = models.ForeignKey("students.Enrollment", on_delete=models.PROTECT, null=True, blank=True, related_name="admission_conversions")
    accounting_bill = models.ForeignKey("accounting.AccountingStudentBill", on_delete=models.PROTECT, null=True, blank=True, related_name="admission_conversions")
    error_code = models.CharField(max_length=80, blank=True, default="")
    error_detail = models.TextField(blank=True, default="")
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "application_conversion"
