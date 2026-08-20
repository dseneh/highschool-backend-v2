from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    BudgetEnrollmentAssumptionViewSet, BudgetLinePeriodViewSet, BudgetLineViewSet,
    BudgetRevisionLineDeltaViewSet, BudgetRevisionViewSet, BudgetSectionViewSet,
    BudgetViewSet,
)

router = DefaultRouter()
router.register("budgets", BudgetViewSet, basename="budget")
router.register("budget-sections", BudgetSectionViewSet, basename="budget-section")
router.register("budget-lines", BudgetLineViewSet, basename="budget-line")
router.register("budget-line-periods", BudgetLinePeriodViewSet, basename="budget-line-period")
router.register("budget-enrollment-assumptions", BudgetEnrollmentAssumptionViewSet, basename="budget-enrollment-assumption")
router.register("budget-revisions", BudgetRevisionViewSet, basename="budget-revision")
router.register("budget-revision-line-deltas", BudgetRevisionLineDeltaViewSet, basename="budget-revision-line-delta")

urlpatterns = [path("", include(router.urls))]
