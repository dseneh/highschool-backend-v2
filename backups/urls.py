from django.urls import include, path
from rest_framework.routers import DefaultRouter

from backups.views import TenantBackupViewSet


router = DefaultRouter()
router.register("backups", TenantBackupViewSet, basename="tenant-backup")

urlpatterns = [path("", include(router.urls))]
