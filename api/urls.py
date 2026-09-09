"""
URL configuration for api project.
"""
from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.conf.urls.static import static
from django.views.static import serve
from django.http import JsonResponse
import os

from payroll_v2.views import PayrollSettingsView


# ---------------------------------------------------------------------------
# Health check  – lightweight, no auth, no tenant header required
# ---------------------------------------------------------------------------
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

@csrf_exempt
def health_check(request):
    """
    Lightweight liveness probe endpoint.
    Must always return quickly with 200 once the app process is running.
    Handles CORS for all methods including OPTIONS preflight.
    """
    origin = request.META.get('HTTP_ORIGIN', '')
    if request.method == 'OPTIONS':
        response = JsonResponse({}, status=200)
    else:
        response = JsonResponse({"status": "ok", "service": "backend"}, status=200)
    return response


_VERSION_1 = "v1"
api_base = f"api/{_VERSION_1}/"

urlpatterns = [
    path("", health_check, name="root-health-check"),
    path("health", health_check, name="health-check-no-slash"),
    path("health/", health_check, name="health-check"),
    path("admin/", admin.site.urls),
    path(api_base, include("core.urls")),
    path(f"{api_base}auth/", include("users.urls")),
    path(f"{api_base}authorization/", include("authorization.urls")),
    path(f"{api_base}sso/", include("users.sso_urls")),
    path(api_base, include("academics.urls")),
    path(api_base, include("students.urls")),
    path(api_base, include("finance.urls")),
    path(api_base, include("accounting.urls")),
    path(api_base, include("hr.urls")),
    path(api_base, include("staff.urls")),
    path(f"{api_base}payroll/settings/", PayrollSettingsView.as_view(), name="payroll-settings"),
    path(f"{api_base}payroll-v2/", include("payroll_v2.urls")),
    path(f"{api_base}employee-benefits/", include("employee_benefits.urls")),
    path(f"{api_base}employee-disbursements/", include("employee_disbursements.urls")),
    path(api_base + "grading/", include("grading.urls")),
    path(api_base + "settings/", include("settings.urls")),
    path(api_base + "reports/", include("reports.urls")),
    path(api_base, include("common.urls")),
    path(api_base + "notifications/", include("notifications.urls")),
    path(api_base, include("backups.urls")),
]

if settings.DEBUG:
    def serve_tenant_media(request, path):
        document_root = settings.MEDIA_ROOT
        return serve(request, path, document_root=document_root)

    urlpatterns += [re_path(r'^media/(?P<path>.*)$', serve_tenant_media)]
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
