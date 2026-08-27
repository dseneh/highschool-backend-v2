"""URL configuration for users app (authentication and user management)."""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView
from users.views import (
    MultiFieldTokenObtainPairView,
    VerifyTokenView,
    PasswordResetConfirmView,
    PasswordResetRequestView,
    TenantOwnerActivationResendCodeView,
    TenantOwnerActivationVerifyCodeView,
)
from users.scoped_viewset import ScopedUserViewSet
from users.access_views import (
    PlatformUserCreateView,
    PlatformAccessView,
    PlatformEmploymentView,
)

router = DefaultRouter()
router.register(r'users', ScopedUserViewSet, basename='user')

urlpatterns = [
    path("login/", MultiFieldTokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("verify/", VerifyTokenView.as_view(), name="verify_token"),
    # Keep the existing URL temporarily for frontend/backward compatibility,
    # but its semantics are now "create platform user", not account_type=global.
    path("users/global/", PlatformUserCreateView.as_view(), name="platform_user_create"),

    path(
        "users/<str:id_number>/platform-access/",
        PlatformAccessView.as_view(),
        name="user_platform_access",
    ),
    path(
        "users/<str:id_number>/platform-employment/",
        PlatformEmploymentView.as_view(),
        name="user_platform_employment",
    ),

    path("password/forgot/", PasswordResetRequestView.as_view(), name="password_reset_request"),
    path("account-activation/verify-code/", TenantOwnerActivationVerifyCodeView.as_view(), name="tenant_owner_activation_verify_code"),
    path("account-activation/resend-code/", TenantOwnerActivationResendCodeView.as_view(), name="tenant_owner_activation_resend_code"),
    path("password/reset/", PasswordResetConfirmView.as_view(), name="password_reset_confirm"),
    path("", include(router.urls)),
]
