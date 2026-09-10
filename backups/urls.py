from django.urls import include, path
from rest_framework.routers import DefaultRouter

from backups.views import TenantBackupViewSet, TenantRestoreRequestViewSet


router = DefaultRouter()
router.register("backups", TenantBackupViewSet, basename="tenant-backup")
router.register("restore-requests", TenantRestoreRequestViewSet, basename="tenant-restore-request")

urlpatterns = [path("", include(router.urls))]
