from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    EmployeeCompensationViewSet,
    EmployeePayrollItemViewSet,
    EmployeeWardViewSet,
    PayrollDeductionInstallmentViewSet,
    PayrollDeductionScheduleViewSet,
    PayrollEmployeeItemViewSet,
    PayrollItemViewSet,
    PayrollItemRuleViewSet,
    PayrollPeriodViewSet,
    PayScheduleViewSet,
    PayrollRunViewSet,
    PayrollSchoolHeaderView,
    PayrollSettingsView,
    PayrollObligationEligibilityPreviewView,
    WardSponsorshipWindowPreviewView,
    PayrollTableViewViewSet,
    PayrollPayslipTemplateViewSet,
    SalaryAdvanceViewSet,
    StaffWardSponsorshipPolicyViewSet,
    StaffWardSponsorshipStudentViewSet,
    StaffWardSponsorshipViewSet,
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
router.register("staff-ward-sponsorship-policies", StaffWardSponsorshipPolicyViewSet, basename="staff-ward-sponsorship-policy")
router.register("employee-wards", EmployeeWardViewSet, basename="employee-ward")
router.register("staff-ward-sponsorships", StaffWardSponsorshipViewSet, basename="staff-ward-sponsorship")
router.register("staff-ward-sponsorship-students", StaffWardSponsorshipStudentViewSet, basename="staff-ward-sponsorship-student")
router.register("salary-advances", SalaryAdvanceViewSet, basename="salary-advance")
router.register("deduction-schedules", PayrollDeductionScheduleViewSet, basename="payroll-deduction-schedule")
router.register("deduction-installments", PayrollDeductionInstallmentViewSet, basename="payroll-deduction-installment")

urlpatterns = [
    path("school-header/", PayrollSchoolHeaderView.as_view(), name="payroll-v2-school-header"),
    path("settings/", PayrollSettingsView.as_view(), name="payroll-v2-settings"),
    path("obligation-eligibility/", PayrollObligationEligibilityPreviewView.as_view(), name="payroll-v2-obligation-eligibility"),
    path("ward-sponsorship-window-preview/", WardSponsorshipWindowPreviewView.as_view(), name="payroll-v2-ward-sponsorship-window-preview"),
    path("", include(router.urls)),
]
