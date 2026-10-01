"""Email proof and school-scoped self-service registration records."""
import uuid
from django.conf import settings
from django.db import models


class AccountSetupChallenge(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey("core.Tenant", on_delete=models.CASCADE)
    email = models.EmailField()
    account_type = models.CharField(max_length=10)
    code_hash = models.CharField(max_length=128)
    proof_hash = models.CharField(max_length=64, blank=True)
    source_ids = models.JSONField(default=dict)
    attempts = models.PositiveSmallIntegerField(default=0)
    expires_at = models.DateTimeField()
    verified_at = models.DateTimeField(null=True)
    used_at = models.DateTimeField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)


class VerifiedAccountEmail(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    email = models.EmailField()
    verified_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "email"], name="unique_verified_account_email")]


class ParentSchoolRegistration(models.Model):
    profile = models.ForeignKey("users.ParentProfile", on_delete=models.CASCADE)
    tenant = models.ForeignKey("core.Tenant", on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["profile", "tenant"], name="unique_parent_school_registration")]


class ParentLinkRequest(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey("core.Tenant", on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    student_id = models.UUIDField()
    relationship = models.CharField(max_length=20)
    status = models.CharField(max_length=10, default="pending")
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="parent_requests_reviewed")
    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "user", "student_id"], condition=models.Q(status="pending"), name="unique_pending_parent_link_request")]


class SchoolUserAccess(models.Model):
    """Approval only; grants no membership until verified account setup completes."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey("core.Tenant", on_delete=models.CASCADE)
    email = models.EmailField()
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    # Roles live in tenant schemas, so never create a cross-schema foreign key.
    role_id = models.UUIDField()
    role_name = models.CharField(max_length=150)
    permission_version = models.PositiveBigIntegerField()
    approved_grants = models.JSONField(default=dict)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="school_access_approvals")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="school_access_records")
    status = models.CharField(max_length=10, default="pending", choices=[("pending", "Pending"), ("accepted", "Accepted"), ("revoked", "Revoked")])
    created_at = models.DateTimeField(auto_now_add=True)
    accepted_at = models.DateTimeField(null=True)
    instructions_sent_at = models.DateTimeField(null=True)
    instructions_failed = models.BooleanField(default=False)
    class Meta:
        constraints = [models.UniqueConstraint(fields=["tenant", "email", "role_id"], condition=models.Q(status="pending"), name="unique_pending_school_user_access")]
