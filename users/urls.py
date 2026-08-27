"""
URL configuration for users app (authentication and user management)
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView
from users.views import (
    MultiFieldTokenObtainPairView,
    VerifyTokenView,
    GlobalUserCreateView,
    PasswordResetConfirmView,
    PasswordResetRequestView,
    TenantOwnerActivationResendCodeView,
    TenantOwnerActivationVerifyCodeView,
)
from users.viewsets import UserViewSet
from users.access_views import PlatformAccessView, PlatformEmploymentView

router = DefaultRouter()
router.register(r'users', UserViewSet, basename='user')

urlpatterns = [
    path("login/", MultiFieldTokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("verify/", VerifyTokenView.as_view(), name="verify_token"),
    path("users/global/", GlobalUserCreateView.as_view(), name="global_user_create"),

    # Elevated identity/access lifecycle. These operate on the canonical public
    # User and preserve tenant persona/employment history.
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
