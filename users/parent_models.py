"""Shared identity and discovery only; tenant guardian rows authorize access."""
import uuid
from django.conf import settings
from django.db import models


class ParentProfile(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="parent_profile")
    created_at = models.DateTimeField(auto_now_add=True)


class ParentStudentLink(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    profile = models.ForeignKey(ParentProfile, on_delete=models.CASCADE, related_name="links")
    tenant = models.ForeignKey("core.Tenant", on_delete=models.CASCADE)
    guardian_id = models.UUIDField()
    active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["profile", "tenant", "guardian_id"], name="unique_parent_school_guardian")]


class ParentInvitation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey("core.Tenant", on_delete=models.CASCADE)
    guardian_id = models.UUIDField()
    email = models.EmailField()
    token_hash = models.CharField(max_length=64, unique=True)
    issued_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="parent_invitations_issued")
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    delivered_at = models.DateTimeField(null=True)
    accepted_at = models.DateTimeField(null=True)
    revoked_at = models.DateTimeField(null=True)
    accepted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="parent_invitations_accepted")
