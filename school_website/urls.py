from django.urls import include, path
from rest_framework.routers import DefaultRouter

from school_website.views import PublicWebsiteView, WebsiteMediaViewSet, WebsiteNavigationViewSet, WebsitePageViewSet, WebsiteSectionViewSet, WebsiteSettingsViewSet

router = DefaultRouter()
router.register("settings", WebsiteSettingsViewSet, basename="website-settings")
router.register("pages", WebsitePageViewSet, basename="website-page")
router.register("sections", WebsiteSectionViewSet, basename="website-section")
router.register("navigation", WebsiteNavigationViewSet, basename="website-navigation")
router.register("media", WebsiteMediaViewSet, basename="website-media")

urlpatterns = [path("public/", PublicWebsiteView.as_view(), name="website-public"), path("", include(router.urls))]
