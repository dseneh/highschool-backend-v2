"""
URL configuration for core app (Tenant management)
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from core.views import (
    TenantViewSet,
    search_tenant_info,
    current_tenant,
    invalidate_cache,
    SignupRequestViewSet,
    ContactInquiryView,
)
from core.platform_banner_views import (
    DismissPlatformBannerView,
    MyPlatformBannersView,
    PlatformBannerTargetingMetaView,
    PlatformBannerViewSet,
)

router = DefaultRouter()
router.register(r'tenants', TenantViewSet, basename='tenant')
router.register(r'signup-requests', SignupRequestViewSet, basename='signup-request')
router.register(
    r"platform-banners",
    PlatformBannerViewSet,
    basename="platform-banner",
)

urlpatterns = [
    path('', include(router.urls)),
    path('contact-inquiries/', ContactInquiryView.as_view(), name='contact-inquiry'),
    path('current/', current_tenant, name='current-tenant'),
    path('search/', search_tenant_info, name='search-tenant-info'),
    path('cache/invalidate/', invalidate_cache, name='invalidate-cache'),
    path(
        "platform-banners/me/",
        MyPlatformBannersView.as_view(),
        name="platform-banner-me",
    ),
    path(
        "platform-banners/<uuid:pk>/dismiss/",
        DismissPlatformBannerView.as_view(),
        name="platform-banner-dismiss",
    ),
    path(
        "platform-banners/meta/targeting/",
        PlatformBannerTargetingMetaView.as_view(),
        name="platform-banner-targeting-meta",
    ),
]

