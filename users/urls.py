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
)
from users.viewsets import UserViewSet

# Create router for viewset
router = DefaultRouter()
router.register(r'users', UserViewSet, basename='user')

urlpatterns = [
    # JWT Token endpoints
    path("login/", MultiFieldTokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    
    # User info and verification endpoints (stateless JWT authentication)
    path("verify/", VerifyTokenView.as_view(), name="verify_token"),
    
    # Global user creation (kept as APIView for now)
    path("users/global/", GlobalUserCreateView.as_view(), name="global_user_create"),
    
    # Password reset confirm (public endpoint)
    path("password/reset/", PasswordResetConfirmView.as_view(), name="password_reset_confirm"),
    
    # ViewSet routes (includes all user CRUD + custom actions)
    # - GET /users/ - list users
    # - POST /users/ - create/attach user to tenant
    # - GET /users/current/ - get current user
    # - POST /users/recreate/ - create from source record
    # - GET /users/{id_number}/ - retrieve user
    # - PUT /users/{id_number}/ - update user
    # - PATCH /users/{id_number}/ - partial update user
    # - DELETE /users/{id_number}/ - delete user
    # - POST /users/{id_number}/password/change/ - change password
    # - POST /users/password/forgot/ - request password reset
    path("", include(router.urls)),
]

