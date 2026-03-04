"""
URL configuration for api project.
"""
from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.conf.urls.static import static
from django.views.static import serve
from django.http import JsonResponse
from django.db import connection
import os


# ---------------------------------------------------------------------------
# Health check  – lightweight, no auth, no tenant header required
# ---------------------------------------------------------------------------
def health_check(request):
    """
    Returns 200 if the application is running and the database is reachable.
    """
    try:
        connection.ensure_connection()
        db_ok = True
    except Exception:
        db_ok = False

    payload = {
        "status": "healthy" if db_ok else "degraded",
        "database": "connected" if db_ok else "unreachable",
    }
    status_code = 200 if db_ok else 503
    return JsonResponse(payload, status=status_code)


# API version prefix
_VERSION_1 = "v1"
api_base = f"api/{_VERSION_1}/"

urlpatterns = [
    path("health/", health_check, name="health-check"),
    path("admin/", admin.site.urls),
    path(api_base, include("core.urls")),
    path(f"{api_base}auth/", include("users.urls")),
    path(api_base, include("academics.urls")),
    path(api_base, include("students.urls")),
    path(api_base, include("finance.urls")),
    path(api_base, include("staff.urls")),
    path(api_base + "grading/", include("grading.urls")),
    path(api_base + "settings/", include("settings.urls")),
    path(api_base + "reports/", include("reports.urls")),
]

# Serve media files in development
if settings.DEBUG:
    # Custom media serving view that handles tenant subdirectories
    def serve_tenant_media(request, path):
        """Serve media files from tenant subdirectories"""
        document_root = settings.MEDIA_ROOT
        # The path already includes the tenant subdirectory (e.g., 'ldtc/images/photo.jpg')
        return serve(request, path, document_root=document_root)
    
    # Serve media files with tenant-aware path handling
    urlpatterns += [
        re_path(r'^media/(?P<path>.*)$', serve_tenant_media),
    ]
    
    # Also serve static files
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    
    # urlpatterns += [
    #     path("debug/", include("debug_toolbar.urls")),
    # ]
