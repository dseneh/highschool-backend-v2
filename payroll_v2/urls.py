from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    EmployeeCompensationViewSet,
    EmployeePayrollItemViewSet,
    PayrollEmployeeItemViewSet,
    PayrollItemViewSet,
    PayrollItemRuleViewSet,
    PayrollPeriodViewSet,
    PayScheduleViewSet,
    PayrollRunViewSet,
    PayrollSchoolHeaderView,
    PayrollSettingsView,
    PayrollTableViewViewSet,
    PayrollPayslipTemplateViewSet,
)

router = DefaultRouter()
router.register("pay-schedules", PayScheduleViewSet, basename="payroll-v2-pay-schedule")
router.register("payroll-periods", PayrollPeriodViewSet, basename="payroll-v2-payroll-period")
router.register("compensations", EmployeeCompensationViewSet, basename="payroll-compensation")
router.register("items", PayrollItemViewSet, basename="payroll-item")
router.register("item-rules", PayrollItemRuleViewSet, basename="payroll-item-rule")
router.register("employee-items", EmployeePayrollItemViewSet, basename="employee-payroll-item")
router.register("runs", PayrollRunViewSet, basename="payroll-run")
router.register("employee-run-items", PayrollEmployeeItemViewSet, basename="payroll-employee-item")
router.register("table-views", PayrollTableViewViewSet, basename="payroll-table-view")
router.register("payslip-templates", PayrollPayslipTemplateViewSet, basename="payroll-payslip-template")

urlpatterns = [
    path("school-header/", PayrollSchoolHeaderView.as_view(), name="payroll-v2-school-header"),
    path("settings/", PayrollSettingsView.as_view(), name="payroll-v2-settings"),
    path("", include(router.urls)),
]
