from django.urls import include, path
from rest_framework.routers import DefaultRouter

from notifications.views import (
    AnnouncementListView,
    CampaignViewSet,
    InboxViewSet,
    NotificationRuleViewSet,
    TenantNotificationSettingsView,
    UserPreferenceView,
)

router = DefaultRouter()
router.register(r"inbox", InboxViewSet, basename="notification-inbox")
router.register(r"campaigns", CampaignViewSet, basename="notification-campaign")
router.register(r"rules", NotificationRuleViewSet, basename="notification-rule")

urlpatterns = [
    path("", include(router.urls)),
    path("announcements/", AnnouncementListView.as_view(), name="notification-announcements"),
    path("preferences/me/", UserPreferenceView.as_view(), name="notification-preferences-me"),
    path(
        "settings/",
        TenantNotificationSettingsView.as_view(),
        name="notification-tenant-settings",
    ),
]
