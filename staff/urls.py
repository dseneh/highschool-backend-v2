from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    StaffViewSet,
    PositionViewSet,
    DepartmentViewSet,
    PositionCategoryViewSet,
    TeacherScheduleViewSet,
    TeacherSectionViewSet,
    TeacherSubjectViewSet,
)

# Create router for viewsets
router = DefaultRouter()
router.register(
    r"staff",
    StaffViewSet,
    basename="staff",
)
router.register(
    r"positions",
    PositionViewSet,
    basename="position",
)
router.register(
    r"departments",
    DepartmentViewSet,
    basename="department",
)
router.register(
    r"position-categories",
    PositionCategoryViewSet,
    basename="position-category",
)
router.register(
    r"teacher-schedules",
    TeacherScheduleViewSet,
    basename="teacher-schedule",
)
router.register(
    r"teacher-sections",
    TeacherSectionViewSet,
    basename="teacher-section",
)
router.register(
    r"teacher-subjects",
    TeacherSubjectViewSet,
    basename="teacher-subject",
)

urlpatterns = [
    # Include router URLs
    path("", include(router.urls)),
]

