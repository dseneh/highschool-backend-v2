from django.urls import include, path
from rest_framework.routers import DefaultRouter

from backups.views import (
    PlatformBackupViewSet,
    PlatformRestoreRequestViewSet,
    TenantBackupViewSet,
    TenantRestoreRequestViewSet,
)


router = DefaultRouter()
router.register("backups", TenantBackupViewSet, basename="tenant-backup")
router.register("restore-requests", TenantRestoreRequestViewSet, basename="tenant-restore-request")
router.register("platform/backups", PlatformBackupViewSet, basename="platform-backup")
router.register("platform/restore-requests", PlatformRestoreRequestViewSet, basename="platform-restore-request")

urlpatterns = [path("", include(router.urls))]
