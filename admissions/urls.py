from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import AdmissionApplicationViewSet, AdmissionCycleViewSet, PublicAdmissionCycleListView
from .portal_views import (
    ApplicantApplicationView,
    ApplicantAccessRequestView,
    ApplicantDocumentDownloadView,
    ApplicantDocumentListCreateView,
    ApplicantInformationRequestListView,
    ApplicantInformationResponseView,
    ApplicantMessageListCreateView,
    ApplicantSubmitView,
    ApplicantVerificationView,
    PublicApplicationStartView,
    ReturningApplicationStartView,
)

router = DefaultRouter()
router.register("cycles", AdmissionCycleViewSet, basename="admission-cycle")
router.register("applications", AdmissionApplicationViewSet, basename="admission-application")

urlpatterns = [
    path("public/cycles/", PublicAdmissionCycleListView.as_view(), name="public-admission-cycles"),
    path("public/applications/start/", PublicApplicationStartView.as_view(), name="public-application-start"),
    path("public/applications/verify/", ApplicantVerificationView.as_view(), name="public-application-verify"),
    path("public/applications/access/", ApplicantAccessRequestView.as_view(), name="public-application-access"),
    path("returning/applications/start/", ReturningApplicationStartView.as_view(), name="returning-application-start"),
    path("portal/applications/<str:request_id>/", ApplicantApplicationView.as_view(), name="applicant-application"),
    path("portal/applications/<str:request_id>/submit/", ApplicantSubmitView.as_view(), name="applicant-submit"),
    path("portal/applications/<str:request_id>/messages/", ApplicantMessageListCreateView.as_view(), name="applicant-messages"),
    path("portal/applications/<str:request_id>/information-requests/", ApplicantInformationRequestListView.as_view(), name="applicant-information-requests"),
    path("portal/applications/<str:request_id>/information-requests/<uuid:information_request_id>/respond/", ApplicantInformationResponseView.as_view(), name="applicant-information-response"),
    path("portal/applications/<str:request_id>/documents/", ApplicantDocumentListCreateView.as_view(), name="applicant-documents"),
    path("portal/applications/<str:request_id>/documents/<uuid:document_id>/download/", ApplicantDocumentDownloadView.as_view(), name="applicant-document-download"),
    path("", include(router.urls)),
]
