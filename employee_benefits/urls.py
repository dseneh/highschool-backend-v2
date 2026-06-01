from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    BenefitRequestLineViewSet,
    BenefitRequestViewSet,
    BenefitSettingsView,
    BenefitTypeRuleViewSet,
    BenefitTypeViewSet,
    EmployeeBenefitViewSet,
)

router = DefaultRouter()
router.register("types", BenefitTypeViewSet, basename="benefit-type")
router.register("type-rules", BenefitTypeRuleViewSet, basename="benefit-type-rule")
router.register("employee-benefits", EmployeeBenefitViewSet, basename="employee-benefit")
router.register("requests", BenefitRequestViewSet, basename="benefit-request")
router.register("request-lines", BenefitRequestLineViewSet, basename="benefit-request-line")

urlpatterns = [
    path("settings/", BenefitSettingsView.as_view(), name="employee-benefit-settings"),
    path("", include(router.urls)),
]
