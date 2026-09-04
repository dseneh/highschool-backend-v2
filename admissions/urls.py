from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import AdmissionApplicationViewSet, AdmissionCycleViewSet, PublicAdmissionCycleListView

router = DefaultRouter()
router.register("cycles", AdmissionCycleViewSet, basename="admission-cycle")
router.register("applications", AdmissionApplicationViewSet, basename="admission-application")

urlpatterns = [
    path("public/cycles/", PublicAdmissionCycleListView.as_view(), name="public-admission-cycles"),
    path("", include(router.urls)),
]
