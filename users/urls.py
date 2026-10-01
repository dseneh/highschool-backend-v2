"""URL configuration for users app (authentication and user management)."""
from users.parent_notifications import ParentNotificationsView
from users.account_setup_views import RetiredInvitationView, AccountSetupView, ContactPortalAccessView, ParentLinkRequestsView, ReviewParentRequestsView
from django.urls import path, include
from rest_framework.routers import DefaultRouter

from users.security_auth import SecurityTokenObtainPairView, SecurityTokenRefreshView
from users.security_views import RevokeAllSessionsView
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

from users.parent_views import ParentSummaryView, ParentSelectView, ParentStudentView, GuardianPortalView

from users.parent_workspace import ParentWorkspaceView, ParentWorkspaceContextView, ParentWorkspaceRolesView

urlpatterns = [
    path("parent/notifications/", ParentNotificationsView.as_view()),
    path("parent/notifications/<path:action>/", ParentNotificationsView.as_view()),
    path("parent/context/<uuid:link_id>/", ParentWorkspaceContextView.as_view()),
    path("parent/roles/", ParentWorkspaceRolesView.as_view()),
    path("parent/workspace/", ParentWorkspaceView.as_view()),
    path("account-setup/<str:action>/", AccountSetupView.as_view()),
    path("parent/contacts/<uuid:contact_id>/access/", ContactPortalAccessView.as_view()),
    path("parent/link-requests/", ParentLinkRequestsView.as_view()),
    path("parent/students/<uuid:student_id>/requests/", ReviewParentRequestsView.as_view()),
    path("parent/invitations/email/", RetiredInvitationView.as_view()),
    path("parent/invitations/register/", RetiredInvitationView.as_view()),
    path("parent/invitations/accept/", RetiredInvitationView.as_view()),
    path("parent/summary/", ParentSummaryView.as_view()),
    path("parent/links/<uuid:link_id>/select/", ParentSelectView.as_view()),
    path("parent/links/<uuid:link_id>/", ParentStudentView.as_view()),
    path("parent/guardians/<uuid:guardian_id>/", GuardianPortalView.as_view()),
    path("login/", SecurityTokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("token/refresh/", SecurityTokenRefreshView.as_view(), name="token_refresh"),
    path("verify/", VerifyTokenView.as_view(), name="verify_token"),
    path("security/revoke-sessions/", RevokeAllSessionsView.as_view(), name="revoke_all_sessions"),
    path("users/global/", GlobalUserCreateView.as_view(), name="global_user_create"),
    path("password/forgot/", PasswordResetRequestView.as_view(), name="password_reset_request"),
    path("account-activation/verify-code/", TenantOwnerActivationVerifyCodeView.as_view(), name="tenant_owner_activation_verify_code"),
    path("account-activation/resend-code/", TenantOwnerActivationResendCodeView.as_view(), name="tenant_owner_activation_resend_code"),
    path("password/reset/", PasswordResetConfirmView.as_view(), name="password_reset_confirm"),
    path("", include(router.urls)),
]
