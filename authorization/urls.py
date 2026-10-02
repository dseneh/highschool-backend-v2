from django.urls import path
from rest_framework.routers import DefaultRouter

from authorization.views import (
    BulkUserRoleAssignmentView,
    PermissionCatalogView,
    RoleViewSet,
    UserRoleView,
    UserRoleRevokeView,
    MyRolesView,
)


router = DefaultRouter()
router.register("roles", RoleViewSet, basename="authorization-role")

urlpatterns = [
    path("me/roles/", MyRolesView.as_view(), name="my-roles"),
    path("users/<str:id_number>/roles/<uuid:assignment_id>/", UserRoleRevokeView.as_view(), name="revoke-user-role"),
    path("permissions/", PermissionCatalogView.as_view(), name="permission-catalog"),
    path("users/roles/bulk/", BulkUserRoleAssignmentView.as_view(), name="bulk-user-role"),
    path("users/<str:id_number>/role/", UserRoleView.as_view(), name="user-role"),
    *router.urls,
]
