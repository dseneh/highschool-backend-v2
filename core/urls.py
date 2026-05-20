"""
URL configuration for core app (Tenant management)
"""
from django.urls import path, include
from rest_framework.routers import DefaultRouter
from core.views import TenantViewSet, search_tenant_info, current_tenant, invalidate_cache, SignupRequestViewSet

router = DefaultRouter()
router.register(r'tenants', TenantViewSet, basename='tenant')
router.register(r'signup-requests', SignupRequestViewSet, basename='signup-request')

urlpatterns = [
    path('', include(router.urls)),
    path('current/', current_tenant, name='current-tenant'),
    path('search/', search_tenant_info, name='search-tenant-info'),
    path('cache/invalidate/', invalidate_cache, name='invalidate-cache'),
]

