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
from core.onboarding_views import (
    get_onboarding,
    save_onboarding_step,
    apply_onboarding,
    reset_onboarding,
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
    # IMPORTANT: explicit paths that overlap with the router's detail URLs
    # (e.g. /tenants/{schema_name}/, /platform-banners/{pk}/) MUST be
    # registered BEFORE `include(router.urls)`. Otherwise the router
    # captures them as detail lookups and returns 404 (or worse, tries to
    # parse "me"/"current" as a UUID/schema name).
    path('tenants/current/', current_tenant, name='current-tenant'),

    # Onboarding endpoints (must be before router so they aren't swallowed by
    # the TenantViewSet detail lookup on schema_name)
    path('tenants/<str:schema_name>/onboarding/', get_onboarding, name='tenant-onboarding-get'),
    path('tenants/<str:schema_name>/onboarding/step/', save_onboarding_step, name='tenant-onboarding-step'),
    path('tenants/<str:schema_name>/onboarding/apply/', apply_onboarding, name='tenant-onboarding-apply'),
    path('tenants/<str:schema_name>/onboarding/reset/', reset_onboarding, name='tenant-onboarding-reset'),

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
    path('', include(router.urls)),
    path('contact-inquiries/', ContactInquiryView.as_view(), name='contact-inquiry'),
    path('search/', search_tenant_info, name='search-tenant-info'),
    path('cache/invalidate/', invalidate_cache, name='invalidate-cache'),
]

