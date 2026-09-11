from django.urls import include, path
from rest_framework.routers import DefaultRouter

from backups.history_views import (
    PlatformBackupHistoryView,
    PlatformRestoreHistoryView,
    TenantBackupHistoryView,
    TenantRestoreHistoryView,
)
from backups.policy_views import (
    PlatformBackupSettingsView,
    PlatformTenantBackupPolicyViewSet,
    TenantEffectiveBackupPolicyView,
)
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
router.register("platform/backup-policies", PlatformTenantBackupPolicyViewSet, basename="platform-backup-policy")

urlpatterns = [
    path("backup-policy/", TenantEffectiveBackupPolicyView.as_view(), name="tenant-backup-policy"),
    path("platform/backup-settings/", PlatformBackupSettingsView.as_view(), name="platform-backup-settings"),
    path("backups/<uuid:pk>/history/", TenantBackupHistoryView.as_view(), name="tenant-backup-history"),
    path("restore-requests/<uuid:pk>/history/", TenantRestoreHistoryView.as_view(), name="tenant-restore-history"),
    path("platform/backups/<uuid:pk>/history/", PlatformBackupHistoryView.as_view(), name="platform-backup-history"),
    path(
        "platform/restore-requests/<uuid:pk>/history/",
        PlatformRestoreHistoryView.as_view(),
        name="platform-restore-history",
    ),
    path("", include(router.urls)),
]
