import hashlib
import uuid

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


class OAuthClient(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    client_id = models.CharField(max_length=120, unique=True)
    name = models.CharField(max_length=200)
    is_active = models.BooleanField(default=True)
    require_pkce = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "auth_oauth_client"
        indexes = [
            models.Index(fields=["client_id"]),
            models.Index(fields=["is_active"]),
        ]

    def __str__(self):
        return f"{self.client_id} ({self.name})"


class OAuthRedirectURI(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    client = models.ForeignKey(
        OAuthClient,
        on_delete=models.CASCADE,
        related_name="redirect_uris",
    )
    redirect_uri = models.URLField(max_length=500)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "auth_oauth_redirect_uri"
        constraints = [
            models.UniqueConstraint(
                fields=["client", "redirect_uri"],
                name="auth_oauth_redirect_uri_unique",
            )
        ]
        indexes = [
            models.Index(fields=["client", "is_active"]),
        ]


class CentralAuthSession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session_key_hash = models.CharField(max_length=128, unique=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="central_auth_sessions",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)

    class Meta:
        db_table = "auth_central_auth_session"
        indexes = [
            models.Index(fields=["user", "revoked_at"]),
            models.Index(fields=["expires_at"]),
        ]

    def is_active(self) -> bool:
        now = timezone.now()
        return self.revoked_at is None and self.expires_at > now


class AuthorizationRequest(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    state_hash = models.CharField(max_length=128, db_index=True)
    client = models.ForeignKey(
        OAuthClient,
        on_delete=models.CASCADE,
        related_name="authorization_requests",
    )
    tenant = models.ForeignKey(
        "core.Tenant",
        on_delete=models.CASCADE,
        related_name="authorization_requests",
    )
    redirect_uri = models.URLField(max_length=500)
    code_challenge = models.CharField(max_length=255)
    code_challenge_method = models.CharField(max_length=20, default="S256")
    return_to = models.CharField(max_length=500, default="/")
    requested_scopes = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "auth_authorization_request"
        indexes = [
            models.Index(fields=["state_hash"]),
            models.Index(fields=["expires_at", "consumed_at"]),
        ]


class AuthorizationCode(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code_hash = models.CharField(max_length=128, unique=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="authorization_codes",
    )
    tenant = models.ForeignKey(
        "core.Tenant",
        on_delete=models.CASCADE,
        related_name="authorization_codes",
    )
    client = models.ForeignKey(
        OAuthClient,
        on_delete=models.CASCADE,
        related_name="authorization_codes",
    )
    redirect_uri = models.URLField(max_length=500)
    code_challenge = models.CharField(max_length=255)
    code_challenge_method = models.CharField(max_length=20, default="S256")
    requested_scopes = models.JSONField(default=list, blank=True)
    return_to = models.CharField(max_length=500, default="/")
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    auth_session = models.ForeignKey(
        CentralAuthSession,
        on_delete=models.SET_NULL,
        related_name="authorization_codes",
        null=True,
        blank=True,
    )

    class Meta:
        db_table = "auth_authorization_code"
        indexes = [
            models.Index(fields=["code_hash"]),
            models.Index(fields=["expires_at", "consumed_at"]),
            models.Index(fields=["tenant", "user"]),
        ]


class RefreshTokenFamily(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="refresh_token_families",
    )
    tenant = models.ForeignKey(
        "core.Tenant",
        on_delete=models.CASCADE,
        related_name="refresh_token_families",
    )
    global_session = models.ForeignKey(
        CentralAuthSession,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="refresh_token_families",
    )
    revoked_at = models.DateTimeField(null=True, blank=True)
    reuse_detected_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "auth_refresh_token_family"
        indexes = [
            models.Index(fields=["user", "tenant", "revoked_at"]),
        ]


class TenantSession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session_key_hash = models.CharField(max_length=128, unique=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="tenant_sessions",
    )
    tenant = models.ForeignKey(
        "core.Tenant",
        on_delete=models.CASCADE,
        related_name="tenant_sessions",
    )
    membership_id = models.CharField(max_length=100, blank=True)
    roles = models.JSONField(default=list, blank=True)
    permission_version = models.IntegerField(default=1, validators=[MinValueValidator(1)])
    refresh_token_family = models.ForeignKey(
        RefreshTokenFamily,
        on_delete=models.SET_NULL,
        related_name="tenant_sessions",
        null=True,
        blank=True,
    )
    global_session = models.ForeignKey(
        CentralAuthSession,
        on_delete=models.SET_NULL,
        related_name="tenant_sessions",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)

    class Meta:
        db_table = "auth_tenant_session"
        indexes = [
            models.Index(fields=["global_session", "revoked_at"]),
            models.Index(fields=["tenant", "user", "revoked_at"]),
            models.Index(fields=["expires_at"]),
        ]


class RefreshToken(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    family = models.ForeignKey(
        RefreshTokenFamily,
        on_delete=models.CASCADE,
        related_name="tokens",
    )
    tenant_session = models.ForeignKey(
        TenantSession,
        on_delete=models.CASCADE,
        related_name="refresh_tokens",
    )
    token_hash = models.CharField(max_length=128, unique=True)
    rotated_from = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rotated_to",
    )
    issued_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    rotated_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    reuse_detected = models.BooleanField(default=False)

    class Meta:
        db_table = "auth_refresh_token"
        indexes = [
            models.Index(fields=["token_hash"]),
            models.Index(fields=["family", "revoked_at"]),
            models.Index(fields=["expires_at"]),
        ]


class SessionRevocation(models.Model):
    class Scope(models.TextChoices):
        TENANT = "tenant", "Tenant"
        GLOBAL = "global", "Global"
        TOKEN_FAMILY = "token_family", "Token Family"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    scope = models.CharField(max_length=20, choices=Scope.choices)
    reason = models.CharField(max_length=200, blank=True)
    central_auth_session = models.ForeignKey(
        CentralAuthSession,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="revocations",
    )
    tenant_session = models.ForeignKey(
        TenantSession,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="revocations",
    )
    refresh_token_family = models.ForeignKey(
        RefreshTokenFamily,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="revocations",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "auth_session_revocation"
        indexes = [
            models.Index(fields=["scope", "created_at"]),
        ]


class AuthenticationAuditEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event_type = models.CharField(max_length=80, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="auth_audit_events",
        null=True,
        blank=True,
    )
    tenant = models.ForeignKey(
        "core.Tenant",
        on_delete=models.SET_NULL,
        related_name="auth_audit_events",
        null=True,
        blank=True,
    )
    client = models.ForeignKey(
        OAuthClient,
        on_delete=models.SET_NULL,
        related_name="auth_audit_events",
        null=True,
        blank=True,
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "auth_audit_event"
        indexes = [
            models.Index(fields=["event_type", "created_at"]),
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["tenant", "created_at"]),
        ]


def hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
