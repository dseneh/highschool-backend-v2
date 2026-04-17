from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    EmployeeDepartmentViewSet,
    EmployeePositionViewSet,
    EmployeeViewSet,
    EmployeeDocumentViewSet,
    EmployeeAttendanceViewSet,
    EmployeePerformanceReviewViewSet,
    EmployeeWorkflowTaskViewSet,
    LeaveRequestViewSet,
    LeaveTypeViewSet,
    PayrollComponentViewSet,
    EmployeeCompensationViewSet,
    PayrollRunViewSet,
)

router = DefaultRouter()
router.register(r"employees", EmployeeViewSet, basename="employee")
router.register(r"employee-departments", EmployeeDepartmentViewSet, basename="employee-department")
router.register(r"employee-positions", EmployeePositionViewSet, basename="employee-position")
router.register(r"leave-types", LeaveTypeViewSet, basename="leave-type")
router.register(r"leave-requests", LeaveRequestViewSet, basename="leave-request")
router.register(r"employee-documents", EmployeeDocumentViewSet, basename="employee-document")
router.register(r"employee-attendance", EmployeeAttendanceViewSet, basename="employee-attendance")
router.register(r"employee-performance-reviews", EmployeePerformanceReviewViewSet, basename="employee-performance-review")
router.register(r"employee-workflow-tasks", EmployeeWorkflowTaskViewSet, basename="employee-workflow-task")
router.register(r"payroll-components", PayrollComponentViewSet, basename="payroll-component")
router.register(r"employee-compensations", EmployeeCompensationViewSet, basename="employee-compensation")
router.register(r"payroll-runs", PayrollRunViewSet, basename="payroll-run")

urlpatterns = [
    path("", include(router.urls)),
]
