from django.urls import path
from rest_framework.routers import DefaultRouter

from authorization.views import PermissionCatalogView, RoleViewSet, UserRoleView


router = DefaultRouter()
router.register("roles", RoleViewSet, basename="authorization-role")

urlpatterns = [
    path("permissions/", PermissionCatalogView.as_view(), name="permission-catalog"),
    path("users/<str:id_number>/role/", UserRoleView.as_view(), name="user-role"),
    *router.urls,
]
