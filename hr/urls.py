from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    EmployeeAttendanceViewSet,
    EmployeeDepartmentViewSet,
    EmployeePerformanceReviewViewSet,
    EmployeePositionViewSet,
    EmployeeSpecializationViewSet,
    EmployeeViewSet,
    LeaveRequestViewSet,
    LeaveTypeViewSet,
)

router = DefaultRouter()
router.register(r"employees", EmployeeViewSet, basename="employee")
router.register(r"employee-departments", EmployeeDepartmentViewSet, basename="employee-department")
router.register(r"employee-positions", EmployeePositionViewSet, basename="employee-position")
router.register(r"employee-specializations", EmployeeSpecializationViewSet, basename="employee-specialization")
router.register(r"leave-types", LeaveTypeViewSet, basename="leave-type")
router.register(r"leave-requests", LeaveRequestViewSet, basename="leave-request")
router.register(r"employee-attendance", EmployeeAttendanceViewSet, basename="employee-attendance")
router.register(
    r"employee-performance-reviews",
    EmployeePerformanceReviewViewSet,
    basename="employee-performance-review",
)

urlpatterns = [
    path("", include(router.urls)),
]
