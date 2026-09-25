"""URL configuration for users app (authentication and user management)."""
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from users.security_auth import (
    EmailMFAResendView,
    EmailMFAVerifyView,
    SecurityTokenObtainPairView,
    SecurityTokenRefreshView,
)
from users.security_views import (
    ActiveSessionListView,
    EmailMFARecoveryStartView,
    EmailMFARecoveryVerifyView,
    RevokeAllSessionsView,
    RevokeSessionView,
    SecurityOverviewView,
)
from users.step_up_views import StepUpMFAStartView, StepUpMFAVerifyView
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
    path("mfa/verify/", EmailMFAVerifyView.as_view(), name="email_mfa_verify"),
    path("mfa/resend/", EmailMFAResendView.as_view(), name="email_mfa_resend"),
    path("token/refresh/", SecurityTokenRefreshView.as_view(), name="token_refresh"),
    path("verify/", VerifyTokenView.as_view(), name="verify_token"),
    path("security/revoke-sessions/", RevokeAllSessionsView.as_view(), name="revoke_all_sessions"),
    path("security/sessions/", ActiveSessionListView.as_view(), name="active_sessions"),
    path("security/sessions/<uuid:session_id>/", RevokeSessionView.as_view(), name="revoke_session"),
    path("security/overview/", SecurityOverviewView.as_view(), name="security_overview"),
    path("security/step-up/", StepUpMFAStartView.as_view(), name="step_up_start"),
    path("security/step-up/verify/", StepUpMFAVerifyView.as_view(), name="step_up_verify"),
    path("security/mfa-recovery/", EmailMFARecoveryStartView.as_view(), name="mfa_recovery_start"),
    path("security/mfa-recovery/verify/", EmailMFARecoveryVerifyView.as_view(), name="mfa_recovery_verify"),
    path("users/global/", GlobalUserCreateView.as_view(), name="global_user_create"),
    path("password/forgot/", PasswordResetRequestView.as_view(), name="password_reset_request"),
    path("account-activation/verify-code/", TenantOwnerActivationVerifyCodeView.as_view(), name="tenant_owner_activation_verify_code"),
    path("account-activation/resend-code/", TenantOwnerActivationResendCodeView.as_view(), name="tenant_owner_activation_resend_code"),
    path("password/reset/", PasswordResetConfirmView.as_view(), name="password_reset_confirm"),
    path("", include(router.urls)),
]
