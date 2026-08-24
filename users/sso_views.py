import secrets
from datetime import timedelta
from urllib.parse import urlencode, urlparse
from django.conf import settings

from django.db import transaction
from django.http import HttpResponseRedirect
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from common.status import PersonStatus
from core.models import Domain, Tenant
from api.authentication import TenantAwareJWTAuthentication, TenantSessionAuthentication
from users.models import (
    CentralAuthSession,
    AuthenticationAuditEvent,
    AuthorizationCode,
    OAuthClient,
    OAuthRedirectURI,
    RefreshToken as RefreshTokenRecord,
    RefreshTokenFamily,
    SessionRevocation,
    TenantSession,
)
from users.sso_serializers import (
    SsoBootstrapSerializer,
    GlobalLogoutSerializer,
    SsoAuthorizeSerializer,
    SsoRefreshSerializer,
    SsoTokenExchangeSerializer,
    TenantLogoutSerializer,
)
from users.sso_utils import hash_value, verify_pkce_s256
from users.tenant_access import user_has_tenant_workspace_access


CENTRAL_SSO_COOKIE_NAMES = ("ezyschool_sso", "__Host-ezyschool_sso")
DEFAULT_SSO_CLIENT_ID = "ezyschool-web"


def is_ip_address(hostname: str) -> bool:
    if not hostname:
        return False
    if hostname.count(".") == 3 and all(part.isdigit() for part in hostname.split(".")):
        return True
    if ":" in hostname:
        allowed = set("0123456789abcdef:")
        return all(ch in allowed for ch in hostname.lower())
    return False


def is_valid_tenant_redirect_uri(redirect_uri: str, tenant_slug: str) -> bool:
    try:
        parsed = urlparse(redirect_uri)
    except Exception:
        return False

    if parsed.scheme not in {"http", "https"}:
        return False
    if parsed.path != "/auth/callback":
        return False

    host = (parsed.hostname or "").lower()
    tenant = (tenant_slug or "").strip().lower()
    if not host or not tenant:
        return False

    if is_ip_address(host) or host in {"localhost", "127.0.0.1"}:
        # Path-based local dev redirect, e.g. http://localhost:3000/auth/callback
        return True

    # Subdomain-based redirect, e.g. https://dujar.myezyschool.com/auth/callback
    return host.startswith(f"{tenant}.")


def resolve_sso_user(request):
    if getattr(request, "user", None) and getattr(request.user, "is_authenticated", False):
        return request.user, None

    sso_cookie = None
    for cookie_name in CENTRAL_SSO_COOKIE_NAMES:
        candidate = request.COOKIES.get(cookie_name)
        if candidate:
            sso_cookie = candidate
            break
    if not sso_cookie:
        return None, None

    now = timezone.now()
    central_session = (
        CentralAuthSession.objects.select_related("user")
        .filter(
            session_key_hash=hash_value(sso_cookie),
            revoked_at__isnull=True,
            expires_at__gt=now,
        )
        .first()
    )
    if not central_session:
        return None, None
    return central_session.user, central_session


def resolve_requested_tenant(requested_tenant: str):
    slug = (requested_tenant or "").strip().lower()
    if not slug:
        return None

    tenant = Tenant.objects.filter(schema_name__iexact=slug).first()
    if tenant:
        return tenant

    domain = (
        Domain.objects.select_related("tenant")
        .filter(domain__istartswith=f"{slug}.")
        .order_by("-is_primary")
        .first()
    )
    if domain and getattr(domain, "tenant", None):
        return domain.tenant

    return None


class SsoBootstrapView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [TenantAwareJWTAuthentication, TenantSessionAuthentication]

    def post(self, request):
        serializer = SsoBootstrapSerializer(data=request.data or {})
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data

        ttl_seconds = payload.get("ttl_seconds", 60 * 60 * 8)
        opaque_session_id = secrets.token_urlsafe(32)
        now = timezone.now()

        central_session = CentralAuthSession.objects.create(
            session_key_hash=hash_value(opaque_session_id),
            user=request.user,
            expires_at=now + timedelta(seconds=ttl_seconds),
            ip_address=request.META.get("REMOTE_ADDR") or None,
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
        )

        AuthenticationAuditEvent.objects.create(
            event_type="sso_central_session_created",
            user=request.user,
            metadata={"central_session_id": str(central_session.id)},
        )

        return Response(
            {
                "session_id": opaque_session_id,
                "expires_at": central_session.expires_at.isoformat(),
                "central_session_id": str(central_session.id),
            },
            status=status.HTTP_201_CREATED,
        )


class SsoAuthorizeView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = [TenantAwareJWTAuthentication]

    def get(self, request):
        serializer = SsoAuthorizeSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data

        client = OAuthClient.objects.filter(client_id=payload["client_id"], is_active=True).first()
        if not client and settings.DEBUG and payload["client_id"] == DEFAULT_SSO_CLIENT_ID:
            client = OAuthClient.objects.create(
                client_id=DEFAULT_SSO_CLIENT_ID,
                name="EzySchool Web",
                is_active=True,
                require_pkce=True,
            )
        if not client:
            return Response(
                {"detail": "Unknown OAuth client.", "error_code": "UNKNOWN_CLIENT"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        redirect_allowed = OAuthRedirectURI.objects.filter(
            client=client,
            redirect_uri=payload["redirect_uri"],
            is_active=True,
        ).exists()

        if (
            not redirect_allowed
            and settings.DEBUG
            and payload["client_id"] == DEFAULT_SSO_CLIENT_ID
            and is_valid_tenant_redirect_uri(payload["redirect_uri"], payload["tenant"])
        ):
            OAuthRedirectURI.objects.get_or_create(
                client=client,
                redirect_uri=payload["redirect_uri"],
                defaults={"is_active": True},
            )
            redirect_allowed = True

        if not redirect_allowed:
            return Response(
                {"detail": "Redirect URI is not allow-listed.", "error_code": "REDIRECT_URI_NOT_ALLOWED"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        tenant = resolve_requested_tenant(payload["tenant"])
        if not tenant:
            return Response(
                {"detail": "Requested tenant does not exist.", "error_code": "TENANT_NOT_FOUND"},
                status=status.HTTP_404_NOT_FOUND,
            )

        tenant_status = str(getattr(tenant, "status", "active") or "active").lower()
        if not getattr(tenant, "active", True) or tenant_status != "active":
            return Response(
                {"detail": "Requested tenant is inactive.", "error_code": "TENANT_INACTIVE"},
                status=status.HTTP_403_FORBIDDEN,
            )

        auth_user, central_session = resolve_sso_user(request)
        if not auth_user:
            return Response(
                {"detail": "Authentication required.", "error_code": "AUTH_REQUIRED"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        if not user_has_tenant_workspace_access(auth_user, tenant):
            return Response(
                {"detail": "No active membership for requested tenant.", "error_code": "TENANT_ACCESS_DENIED"},
                status=status.HTTP_403_FORBIDDEN,
            )

        return_to = payload.get("return_to") or "/"
        if not return_to.startswith("/") or return_to.startswith("//"):
            return_to = "/"

        plain_code = secrets.token_urlsafe(32)
        expires_at = timezone.now() + timedelta(seconds=60)

        AuthorizationCode.objects.create(
            code_hash=hash_value(plain_code),
            user=auth_user,
            tenant=tenant,
            client=client,
            redirect_uri=payload["redirect_uri"],
            code_challenge=payload["code_challenge"],
            code_challenge_method=payload["code_challenge_method"],
            requested_scopes=[],
            return_to=return_to,
            expires_at=expires_at,
            auth_session=central_session,
        )

        AuthenticationAuditEvent.objects.create(
            event_type="sso_authorize_success",
            user=auth_user,
            tenant=tenant,
            client=client,
            ip_address=request.META.get("REMOTE_ADDR") or None,
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
            metadata={"return_to": return_to},
        )

        query = urlencode({"code": plain_code, "state": payload["state"]})
        redirect_url = f"{payload['redirect_uri']}?{query}"
        return HttpResponseRedirect(redirect_url)


class SsoTokenExchangeView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = SsoTokenExchangeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data

        code_hash = hash_value(payload["code"])
        now = timezone.now()

        with transaction.atomic():
            code_obj = (
                AuthorizationCode.objects.select_for_update()
                .select_related("user", "tenant", "client", "auth_session")
                .filter(code_hash=code_hash)
                .first()
            )

            if not code_obj:
                return Response(
                    {"detail": "Invalid authorization code.", "error_code": "INVALID_GRANT"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if code_obj.consumed_at is not None:
                return Response(
                    {"detail": "Authorization code already used.", "error_code": "CODE_CONSUMED"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if code_obj.revoked_at is not None:
                return Response(
                    {"detail": "Authorization code revoked.", "error_code": "CODE_REVOKED"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if code_obj.expires_at <= now:
                return Response(
                    {"detail": "Authorization code expired.", "error_code": "CODE_EXPIRED"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if code_obj.client.client_id != payload["client_id"]:
                return Response(
                    {"detail": "Client mismatch.", "error_code": "CLIENT_ID_MISMATCH"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if code_obj.redirect_uri != payload["redirect_uri"]:
                return Response(
                    {"detail": "Redirect URI mismatch.", "error_code": "REDIRECT_URI_MISMATCH"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            redirect_allowed = OAuthRedirectURI.objects.filter(
                client=code_obj.client,
                redirect_uri=payload["redirect_uri"],
                is_active=True,
            ).exists()
            if not redirect_allowed:
                return Response(
                    {"detail": "Redirect URI is not allowed.", "error_code": "REDIRECT_URI_NOT_ALLOWED"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if code_obj.code_challenge_method != "S256":
                return Response(
                    {"detail": "Unsupported code challenge method.", "error_code": "UNSUPPORTED_PKCE_METHOD"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if not verify_pkce_s256(payload["code_verifier"], code_obj.code_challenge):
                return Response(
                    {"detail": "Invalid PKCE verifier.", "error_code": "INVALID_CODE_VERIFIER"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            user = code_obj.user
            tenant = code_obj.tenant

            if not user.is_active or getattr(user, "status", PersonStatus.ACTIVE) != PersonStatus.ACTIVE:
                return Response(
                    {"detail": "User account is inactive.", "error_code": "USER_INACTIVE"},
                    status=status.HTTP_403_FORBIDDEN,
                )

            tenant_status = str(getattr(tenant, "status", "active") or "active").lower()
            if not getattr(tenant, "active", True) or tenant_status != "active":
                return Response(
                    {"detail": "Tenant is inactive.", "error_code": "TENANT_INACTIVE"},
                    status=status.HTTP_403_FORBIDDEN,
                )

            if not user_has_tenant_workspace_access(user, tenant):
                return Response(
                    {"detail": "User has no active membership for this tenant.", "error_code": "TENANT_ACCESS_DENIED"},
                    status=status.HTTP_403_FORBIDDEN,
                )

            auth_session = code_obj.auth_session
            if auth_session and auth_session.revoked_at is not None:
                return Response(
                    {"detail": "Global session revoked.", "error_code": "GLOBAL_SESSION_REVOKED"},
                    status=status.HTTP_403_FORBIDDEN,
                )

            code_obj.consumed_at = now
            code_obj.save(update_fields=["consumed_at"])

            token_family = RefreshTokenFamily.objects.create(
                user=user,
                tenant=tenant,
                global_session=auth_session,
            )

            tenant_session = TenantSession.objects.create(
                session_key_hash=hash_value(secrets.token_urlsafe(48)),
                user=user,
                tenant=tenant,
                membership_id="",
                roles=[str(user.role)],
                permission_version=1,
                refresh_token_family=token_family,
                global_session=auth_session,
                expires_at=now + timedelta(days=7),
                ip_address=request.META.get("REMOTE_ADDR") or None,
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
            )

            refresh = RefreshToken.for_user(user)
            refresh["tenant_id"] = str(tenant.id)
            refresh["membership_id"] = ""
            refresh["session_id"] = str(tenant_session.id)
            refresh["token_version"] = 1
            access = refresh.access_token
            access["tenant_id"] = str(tenant.id)
            access["membership_id"] = ""
            access["session_id"] = str(tenant_session.id)
            access["token_version"] = 1

            refresh_token_value = str(refresh)
            RefreshTokenRecord.objects.create(
                family=token_family,
                tenant_session=tenant_session,
                token_hash=hash_value(refresh_token_value),
                expires_at=now + timedelta(days=7),
            )

            AuthenticationAuditEvent.objects.create(
                event_type="sso_token_exchange_success",
                user=user,
                tenant=tenant,
                client=code_obj.client,
                ip_address=request.META.get("REMOTE_ADDR") or None,
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
                metadata={"tenant_session_id": str(tenant_session.id)},
            )

        return Response(
            {
                "access": str(access),
                "refresh": refresh_token_value,
                "token_type": "Bearer",
                "expires_in": int(access.lifetime.total_seconds()),
                "tenant_session_id": str(tenant_session.id),
            },
            status=status.HTTP_200_OK,
        )


class SsoRefreshView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        serializer = SsoRefreshSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data

        now = timezone.now()
        provided_refresh = payload["refresh_token"]
        provided_hash = hash_value(provided_refresh)

        with transaction.atomic():
            refresh_record = (
                RefreshTokenRecord.objects.select_for_update()
                .select_related("family", "tenant_session", "tenant_session__user", "tenant_session__tenant")
                .filter(token_hash=provided_hash)
                .first()
            )

            if not refresh_record:
                return Response(
                    {"detail": "Invalid refresh token.", "error_code": "INVALID_REFRESH_TOKEN"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            family = refresh_record.family
            tenant_session = refresh_record.tenant_session
            user = tenant_session.user
            tenant = tenant_session.tenant

            if family.revoked_at is not None or tenant_session.revoked_at is not None:
                return Response(
                    {"detail": "Session revoked.", "error_code": "SESSION_REVOKED"},
                    status=status.HTTP_403_FORBIDDEN,
                )

            if refresh_record.reuse_detected or refresh_record.rotated_at is not None:
                family.revoked_at = now
                family.reuse_detected_at = now
                family.save(update_fields=["revoked_at", "reuse_detected_at"])
                tenant_session.revoked_at = now
                tenant_session.save(update_fields=["revoked_at"])
                RefreshTokenRecord.objects.filter(family=family, revoked_at__isnull=True).update(
                    revoked_at=now,
                    reuse_detected=True,
                )
                SessionRevocation.objects.create(
                    scope=SessionRevocation.Scope.TOKEN_FAMILY,
                    reason="refresh_token_reuse_detected",
                    tenant_session=tenant_session,
                    refresh_token_family=family,
                    central_auth_session=family.global_session,
                )
                AuthenticationAuditEvent.objects.create(
                    event_type="sso_refresh_reuse_detected",
                    user=user,
                    tenant=tenant,
                    metadata={"tenant_session_id": str(tenant_session.id)},
                )
                return Response(
                    {"detail": "Refresh token reuse detected.", "error_code": "REFRESH_TOKEN_REUSE"},
                    status=status.HTTP_403_FORBIDDEN,
                )

            if refresh_record.expires_at <= now or refresh_record.revoked_at is not None:
                return Response(
                    {"detail": "Refresh token expired.", "error_code": "REFRESH_TOKEN_EXPIRED"},
                    status=status.HTTP_403_FORBIDDEN,
                )

            refresh_record.rotated_at = now
            refresh_record.save(update_fields=["rotated_at"])

            rotated_refresh = RefreshToken.for_user(user)
            rotated_refresh["tenant_id"] = str(tenant.id)
            rotated_refresh["membership_id"] = tenant_session.membership_id or ""
            rotated_refresh["session_id"] = str(tenant_session.id)
            rotated_refresh["token_version"] = tenant_session.permission_version
            access = rotated_refresh.access_token
            access["tenant_id"] = str(tenant.id)
            access["membership_id"] = tenant_session.membership_id or ""
            access["session_id"] = str(tenant_session.id)
            access["token_version"] = tenant_session.permission_version

            rotated_refresh_value = str(rotated_refresh)
            RefreshTokenRecord.objects.create(
                family=family,
                tenant_session=tenant_session,
                token_hash=hash_value(rotated_refresh_value),
                expires_at=now + timedelta(days=7),
                rotated_from=refresh_record,
            )

            tenant_session.last_used_at = now
            tenant_session.save(update_fields=["last_used_at"])

            AuthenticationAuditEvent.objects.create(
                event_type="sso_refresh_rotated",
                user=user,
                tenant=tenant,
                metadata={"tenant_session_id": str(tenant_session.id)},
            )

        return Response(
            {
                "access": str(access),
                "refresh": rotated_refresh_value,
                "token_type": "Bearer",
                "expires_in": int(access.lifetime.total_seconds()),
                "tenant_session_id": str(tenant_session.id),
            },
            status=status.HTTP_200_OK,
        )


class TenantLogoutView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [TenantAwareJWTAuthentication]

    def post(self, request):
        serializer = TenantLogoutSerializer(data=request.data or {})
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data

        session_id = payload.get("tenant_session_id")
        query = TenantSession.objects.filter(user=request.user, revoked_at__isnull=True)
        if session_id:
            query = query.filter(id=session_id)

        tenant_session = query.order_by("-created_at").first()
        if not tenant_session:
            return Response({"detail": "No active tenant session found."}, status=status.HTTP_200_OK)

        now = timezone.now()
        tenant_session.revoked_at = now
        tenant_session.save(update_fields=["revoked_at"])
        RefreshTokenRecord.objects.filter(
            tenant_session=tenant_session,
            revoked_at__isnull=True,
        ).update(revoked_at=now)
        SessionRevocation.objects.create(
            scope=SessionRevocation.Scope.TENANT,
            reason="tenant_logout",
            tenant_session=tenant_session,
            refresh_token_family=tenant_session.refresh_token_family,
            central_auth_session=tenant_session.global_session,
        )
        AuthenticationAuditEvent.objects.create(
            event_type="tenant_logout",
            user=request.user,
            tenant=tenant_session.tenant,
            metadata={"tenant_session_id": str(tenant_session.id)},
        )

        return Response({"ok": True}, status=status.HTTP_200_OK)


class GlobalLogoutView(APIView):
    permission_classes = [IsAuthenticated]
    authentication_classes = [TenantAwareJWTAuthentication]

    def post(self, request):
        serializer = GlobalLogoutSerializer(data=request.data or {})
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data

        central_session_id = payload.get("central_session_id")
        central_query = CentralAuthSession.objects.filter(user=request.user, revoked_at__isnull=True)
        if central_session_id:
            central_query = central_query.filter(id=central_session_id)

        central_session = central_query.order_by("-created_at").first()
        if not central_session:
            return Response({"detail": "No active central session found."}, status=status.HTTP_200_OK)

        now = timezone.now()
        central_session.revoked_at = now
        central_session.save(update_fields=["revoked_at"])

        tenant_sessions = TenantSession.objects.filter(global_session=central_session, revoked_at__isnull=True)
        tenant_ids = [str(s.id) for s in tenant_sessions]
        tenant_sessions.update(revoked_at=now)

        RefreshTokenRecord.objects.filter(
            tenant_session__global_session=central_session,
            revoked_at__isnull=True,
        ).update(revoked_at=now)

        RefreshTokenFamily.objects.filter(
            global_session=central_session,
            revoked_at__isnull=True,
        ).update(revoked_at=now)

        SessionRevocation.objects.create(
            scope=SessionRevocation.Scope.GLOBAL,
            reason="global_logout",
            central_auth_session=central_session,
        )
        AuthenticationAuditEvent.objects.create(
            event_type="global_logout",
            user=request.user,
            metadata={"tenant_session_ids": tenant_ids},
        )

        return Response({"ok": True, "revoked_tenant_sessions": tenant_ids}, status=status.HTTP_200_OK)
