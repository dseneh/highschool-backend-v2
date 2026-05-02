from rest_framework.routers import DefaultRouter

from .views import (
    PayrollItemTypeViewSet,
    PayrollItemViewSet,
    PayrollPeriodViewSet,
    PayrollRunViewSet,
    PayScheduleViewSet,
    PayslipViewSet,
    TaxRuleViewSet,
    EmployeeTaxRuleOverrideViewSet,
)

router = DefaultRouter()
router.register(r"pay-schedules", PayScheduleViewSet, basename="pay-schedule")
router.register(r"payroll-periods", PayrollPeriodViewSet, basename="payroll-period")
router.register(r"payroll-runs", PayrollRunViewSet, basename="payroll-run")
router.register(r"payslips", PayslipViewSet, basename="payslip")
router.register(r"payroll-items", PayrollItemViewSet, basename="payroll-item")
router.register(r"payroll-item-types", PayrollItemTypeViewSet, basename="payroll-item-type")
router.register(r"tax-rules", TaxRuleViewSet, basename="tax-rule")
router.register(
    r"employee-tax-rule-overrides",
    EmployeeTaxRuleOverrideViewSet,
    basename="employee-tax-rule-override",
)

urlpatterns = router.urls
