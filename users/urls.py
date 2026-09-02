"""URL configuration for users app (authentication and user management)."""
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from users.security_auth import SecurityTokenObtainPairView, SecurityTokenRefreshView
from users.security_views import (
    MFAChallengeVerifyView,
    MFAConfirmView,
    MFADisableView,
    MFASetupView,
    RevokeAllSessionsView,
    SecurityStatusView,
)
from users.views import (
    VerifyTokenView,
    GlobalUserCreateView,
    PasswordResetConfirmView,
    PasswordResetRequestView,
    TenantOwnerActivationResendCodeView,
    TenantOwnerActivationVerifyCodeView,
)
from users.viewsets import UserViewSet

router = DefaultRouter()
router.register(r'users', UserViewSet, basename='user')

urlpatterns = [
    path("login/", SecurityTokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("token/refresh/", SecurityTokenRefreshView.as_view(), name="token_refresh"),
    path("verify/", VerifyTokenView.as_view(), name="verify_token"),

    # Account security
    path("security/", SecurityStatusView.as_view(), name="security_status"),
    path("security/mfa/setup/", MFASetupView.as_view(), name="mfa_setup"),
    path("security/mfa/confirm/", MFAConfirmView.as_view(), name="mfa_confirm"),
    path("security/mfa/disable/", MFADisableView.as_view(), name="mfa_disable"),
    path("security/mfa/challenge/", MFAChallengeVerifyView.as_view(), name="mfa_challenge"),
    path("security/revoke-sessions/", RevokeAllSessionsView.as_view(), name="revoke_all_sessions"),

    path("users/global/", GlobalUserCreateView.as_view(), name="global_user_create"),
    path("password/forgot/", PasswordResetRequestView.as_view(), name="password_reset_request"),
    path("account-activation/verify-code/", TenantOwnerActivationVerifyCodeView.as_view(), name="tenant_owner_activation_verify_code"),
    path("account-activation/resend-code/", TenantOwnerActivationResendCodeView.as_view(), name="tenant_owner_activation_resend_code"),
    path("password/reset/", PasswordResetConfirmView.as_view(), name="password_reset_confirm"),
    path("", include(router.urls)),
]
