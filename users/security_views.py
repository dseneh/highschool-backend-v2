"""Session management and security monitoring endpoints."""

from datetime import timedelta

from django.db import transaction
from django.db.models import Count, F, Q
from django.utils import timezone
from django_tenants.utils import get_public_schema_name, schema_context
from rest_framework.permissions import AllowAny, BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from users.models import (
    AuthenticationAuditEvent,
    CentralAuthSession,
    EmailMFAChallenge,
    RefreshToken,
    RefreshTokenFamily,
    SessionRevocation,
    TenantSession,
    User,
)


def _revoke_server_sessions(user_id, *, reason_time=None):
    now = reason_time or timezone.now()
    CentralAuthSession.objects.filter(user_id=user_id, revoked_at__isnull=True).update(
        revoked_at=now
    )
    TenantSession.objects.filter(user_id=user_id, revoked_at__isnull=True).update(
        revoked_at=now
    )
    RefreshTokenFamily.objects.filter(user_id=user_id, revoked_at__isnull=True).update(
        revoked_at=now
    )


def _current_session_id(request):
    auth = getattr(request, "auth", None)
    return str(auth.get("session_id", "")) if hasattr(auth, "get") else ""


class IsSecurityAdmin(BasePermission):
    message = "Only workspace administrators can view security monitoring data."

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        from authorization.services import get_assigned_role
        from users.tenant_access import is_global_superadmin

        if is_global_superadmin(request.user):
            return True
        role = get_assigned_role(request.user)
        return bool(role and role.is_active and role.system_key == "admin")


class RevokeAllSessionsView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request):
        now = timezone.now()
        with schema_context(get_public_schema_name()):
            User.objects.filter(pk=request.user.pk).update(
                security_version=F("security_version") + 1
            )
            _revoke_server_sessions(request.user.pk, reason_time=now)
        return Response(
            {"detail": "All sessions have been revoked. Sign in again on each device."}
        )


class ActiveSessionListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        now = timezone.now()
        current_session_id = _current_session_id(request)
        with schema_context(get_public_schema_name()):
            sessions = list(
                TenantSession.objects.select_related("tenant")
                .filter(
                    user_id=request.user.pk, revoked_at__isnull=True, expires_at__gt=now
                )
                .order_by("-last_used_at")
            )
        return Response(
            {
                "results": [
                    {
                        "id": str(item.id),
                        "workspace": item.tenant.schema_name,
                        "workspace_name": item.tenant.name,
                        "created_at": item.created_at,
                        "last_used_at": item.last_used_at,
                        "expires_at": item.expires_at,
                        "ip_address": item.ip_address,
                        "device": item.device_metadata
                        or {"user_agent": item.user_agent},
                        "is_current": str(item.id) == current_session_id,
                    }
                    for item in sessions
                ]
            }
        )


class RevokeSessionView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def delete(self, request, session_id):
        now = timezone.now()
        with schema_context(get_public_schema_name()):
            session = TenantSession.objects.filter(
                id=session_id,
                user_id=request.user.pk,
                revoked_at__isnull=True,
            ).first()
            if session is None:
                return Response({"detail": "Session was not found."}, status=404)
            session.revoked_at = now
            session.save(update_fields=["revoked_at"])
            RefreshToken.objects.filter(
                tenant_session=session, revoked_at__isnull=True
            ).update(revoked_at=now)
            if session.refresh_token_family_id:
                RefreshTokenFamily.objects.filter(
                    pk=session.refresh_token_family_id, revoked_at__isnull=True
                ).update(revoked_at=now)
            SessionRevocation.objects.create(
                scope=SessionRevocation.Scope.TENANT,
                reason="user_device_revocation",
                tenant_session=session,
                refresh_token_family=session.refresh_token_family,
                central_auth_session=session.global_session,
            )
            AuthenticationAuditEvent.objects.create(
                event_type="session_revoked_by_user",
                user=request.user,
                tenant=session.tenant,
                ip_address=request.META.get("REMOTE_ADDR") or None,
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
                metadata={"session_id": str(session.id)},
            )
        current_session_id = _current_session_id(request)
        return Response(
            {
                "ok": True,
                "current_session_revoked": str(session.id) == current_session_id,
            }
        )


class SecurityOverviewView(APIView):
    permission_classes = [IsAuthenticated, IsSecurityAdmin]

    def get(self, request):
        tenant = getattr(request, "tenant", None)
        if tenant is None:
            return Response({"detail": "A workspace is required."}, status=400)
        now = timezone.now()
        since = now - timedelta(days=30)
        with schema_context(get_public_schema_name()):
            events = AuthenticationAuditEvent.objects.filter(
                tenant=tenant, created_at__gte=since
            )
            summary = events.aggregate(
                total=Count("id"),
                suspicious=Count("id", filter=Q(event_type="suspicious_login")),
                failed_mfa=Count("id", filter=Q(event_type="mfa_verification_failed")),
                revoked=Count(
                    "id",
                    filter=Q(
                        event_type__in=["session_revoked_by_user", "tenant_logout"]
                    ),
                ),
            )
            active_sessions = TenantSession.objects.filter(
                tenant=tenant,
                revoked_at__isnull=True,
                expires_at__gt=now,
            ).count()
            recent = list(events.select_related("user").order_by("-created_at")[:50])
        return Response(
            {
                "period_days": 30,
                "summary": {**summary, "active_sessions": active_sessions},
                "events": [
                    {
                        "id": str(event.id),
                        "event_type": event.event_type,
                        "created_at": event.created_at,
                        "ip_address": event.ip_address,
                        "user_agent": event.user_agent,
                        "user": (
                            {
                                "id": str(event.user_id),
                                "name": event.user.get_full_name()
                                or event.user.username
                                or event.user.email,
                                "email": event.user.email,
                            }
                            if event.user
                            else None
                        ),
                        "metadata": event.metadata,
                    }
                    for event in recent
                ],
            }
        )


class EmailMFARecoveryStartView(APIView):
    permission_classes = [IsAuthenticated, IsSecurityAdmin]

    def post(self, request):
        from authorization.services import get_assigned_role
        from common.email_validation import is_valid_email
        from users.mfa import mask_email, requires_email_mfa
        from users.mfa_recovery import issue_recovery
        from users.tenant_access import is_global_superadmin

        user_id = request.data.get("user_id")
        new_email = str(request.data.get("new_email", "")).strip().lower()
        if not user_id or not is_valid_email(new_email):
            return Response(
                {"detail": "A user and valid replacement email are required."},
                status=400,
            )
        if str(user_id) == str(request.user.pk):
            return Response(
                {"detail": "You cannot initiate MFA recovery for your own account."},
                status=403,
            )

        with schema_context(get_public_schema_name()):
            target = User.objects.filter(pk=user_id, is_active=True).first()
            duplicate = (
                User.objects.filter(email__iexact=new_email)
                .exclude(pk=user_id)
                .exists()
            )
        if target is None:
            return Response({"detail": "User was not found."}, status=404)
        if duplicate:
            return Response(
                {
                    "detail": "That email address is already assigned to another account."
                },
                status=400,
            )

        actor_is_platform_admin = is_global_superadmin(request.user)
        target_is_platform_admin = is_global_superadmin(target)
        target_role = get_assigned_role(target)
        if (
            not target_is_platform_admin and target_role is None
        ) or not requires_email_mfa(target):
            return Response(
                {
                    "detail": "The selected user is not a privileged MFA account in this workspace."
                },
                status=400,
            )
        if (
            target_is_platform_admin
            or (target_role and target_role.system_key == "admin")
        ) and not actor_is_platform_admin:
            return Response(
                {
                    "detail": "Only a platform administrator can recover an administrator account."
                },
                status=403,
            )

        tenant = getattr(request, "tenant", None)
        tenant_schema = getattr(tenant, "schema_name", "")
        with schema_context(get_public_schema_name()):
            issued = issue_recovery(
                user=target,
                initiated_by=request.user,
                tenant_schema=tenant_schema,
                new_email=new_email,
            )
            if issued is None:
                return Response(
                    {"detail": "Unable to send the recovery verification code."},
                    status=503,
                )
            recovery, raw_token = issued
            AuthenticationAuditEvent.objects.create(
                event_type="mfa_recovery_started",
                user=target,
                tenant=tenant,
                ip_address=request.META.get("REMOTE_ADDR") or None,
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
                metadata={
                    "initiated_by": str(request.user.pk),
                    "recovery_id": str(recovery.id),
                },
            )
        return Response(
            {
                "challenge_token": raw_token,
                "expires_in": 900,
                "delivery": {"method": "email", "destination": mask_email(new_email)},
            },
            status=202,
        )


class EmailMFARecoveryVerifyView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        from core.models import Tenant
        from users.mfa_recovery import verify_recovery

        raw_token = str(request.data.get("challenge_token", ""))
        code = str(request.data.get("code", ""))
        if (
            not raw_token
            or len(raw_token) > 256
            or len(code) != 6
            or not code.isdigit()
        ):
            return Response({"detail": "Invalid or expired recovery code."}, status=400)

        now = timezone.now()
        with schema_context(get_public_schema_name()), transaction.atomic():
            recovery = verify_recovery(raw_token=raw_token, code=code)
            if recovery is None:
                return Response(
                    {"detail": "Invalid or expired recovery code."}, status=400
                )
            if (
                User.objects.filter(email__iexact=recovery.new_email)
                .exclude(pk=recovery.user_id)
                .exists()
            ):
                recovery.invalidated_at = now
                recovery.save(update_fields=["invalidated_at", "updated_at"])
                return Response(
                    {
                        "detail": "That email address is already assigned to another account."
                    },
                    status=400,
                )

            User.objects.filter(pk=recovery.user_id).update(
                email=recovery.new_email,
                security_version=F("security_version") + 1,
            )
            EmailMFAChallenge.objects.filter(
                user_id=recovery.user_id, used_at__isnull=True
            ).update(invalidated_at=now)
            _revoke_server_sessions(recovery.user_id, reason_time=now)
            tenant = Tenant.objects.filter(schema_name=recovery.tenant_schema).first()
            AuthenticationAuditEvent.objects.create(
                event_type="mfa_recovery_completed",
                user_id=recovery.user_id,
                tenant=tenant,
                ip_address=request.META.get("REMOTE_ADDR") or None,
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
                metadata={
                    "recovery_id": str(recovery.id),
                    "initiated_by": str(recovery.initiated_by_id),
                },
            )
        return Response(
            {
                "detail": "Recovery email verified. Sign in again using the updated address."
            }
        )
