from django.db import transaction
from django.db.models import Prefetch
from django.utils import timezone
from rest_framework import filters, status, viewsets
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from authorization.drf import RBACPermission

from .models import AdmissionApplication, AdmissionCycle, ApplicationDocument, ApplicationInformationRequest, ApplicationMessage, ApplicationPlacement, ApplicationStatusHistory
from .serializers import (
    AdmissionApplicationSerializer, AdmissionCycleSerializer, ApplicationDocumentSerializer,
    ApplicationMessageSerializer, ApplicationPlacementSerializer, ApplicationTransitionSerializer,
    DocumentReviewSerializer, InformationRequestCreateSerializer, InformationRequestSerializer,
    PublicAdmissionCycleSerializer,
)
from .services import transition_application


class PublicAdmissionCycleListView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "admissions_public"

    def get(self, request):
        now = timezone.now()
        queryset = AdmissionCycle.objects.filter(active=True, opens_at__lte=now, closes_at__gte=now).prefetch_related("eligible_grade_levels")
        return Response(PublicAdmissionCycleSerializer(queryset, many=True).data)


class AdmissionCycleViewSet(viewsets.ModelViewSet):
    queryset = AdmissionCycle.objects.prefetch_related("eligible_grade_levels").all()
    serializer_class = AdmissionCycleSerializer
    permission_classes = [RBACPermission]
    permission_map = {"list": "admissions.view", "retrieve": "admissions.view", "create": "admissions.cycles.manage", "update": "admissions.cycles.manage", "partial_update": "admissions.cycles.manage", "destroy": "admissions.cycles.manage"}

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user, updated_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)


class AdmissionApplicationViewSet(viewsets.ModelViewSet):
    queryset = AdmissionApplication.objects.select_related("cycle", "returning_student", "requested_grade_level", "assigned_reviewer", "placement").prefetch_related(Prefetch("status_history", queryset=ApplicationStatusHistory.objects.select_related("created_by")))
    serializer_class = AdmissionApplicationSerializer
    permission_classes = [RBACPermission]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ["request_id", "applicant_name", "applicant_email", "applicant_phone"]
    ordering_fields = ["created_at", "updated_at", "submitted_at", "status"]
    permission_map = {
        "list": "admissions.view", "retrieve": "admissions.view",
        "update": "admissions.review", "partial_update": "admissions.review",
        "destroy": "admissions.review", "transition": "admissions.review",
        "messages": "admissions.message", "request_information": "admissions.request_information",
        "placement": "admissions.place", "documents": "admissions.documents.view",
        "review_document": "admissions.documents.review", "download_document": "admissions.documents.view",
    }

    def get_permissions(self):
        permission_map = dict(type(self).permission_map)
        if getattr(self, "action", None) == "transition":
            target = self.request.data.get("status")
            permission_map["transition"] = {
                "approved": "admissions.approve",
                "rejected": "admissions.reject",
                "enrollment_ready": "admissions.place",
                "enrolled": "admissions.enroll",
            }.get(target, "admissions.review")
        self.permission_map = permission_map
        return super().get_permissions()

    @action(detail=True, methods=["post"])
    def transition(self, request, pk=None):
        application = self.get_object()
        serializer = ApplicationTransitionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if serializer.validated_data["version"] != application.version:
            return Response({"detail": "This application was updated by another user. Refresh and try again.", "error_code": "VERSION_CONFLICT"}, status=status.HTTP_409_CONFLICT)
        application = transition_application(
            application=application, to_status=serializer.validated_data["status"],
            actor=request.user, reason=serializer.validated_data["reason"],
        )
        return Response(self.get_serializer(application).data)

    @action(detail=True, methods=["get", "post"])
    def messages(self, request, pk=None):
        application = self.get_object()
        if request.method == "GET":
            application.messages.filter(author_type=ApplicationMessage.AuthorType.APPLICANT, school_read_at__isnull=True).update(school_read_at=timezone.now())
            return Response(ApplicationMessageSerializer(application.messages.all(), many=True).data)
        serializer = ApplicationMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        message = serializer.save(
            application=application, author_type=ApplicationMessage.AuthorType.SCHOOL,
            created_by=request.user, updated_by=request.user,
        )
        return Response(ApplicationMessageSerializer(message).data, status=201)

    @action(detail=True, methods=["post"], url_path="request-information")
    @transaction.atomic
    def request_information(self, request, pk=None):
        application = self.get_object()
        if application.status != "under_review":
            return Response({"detail": "Information can only be requested while an application is under review."}, status=400)
        serializer = InformationRequestCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        item = serializer.save(application=application, created_by=request.user, updated_by=request.user)
        if application.status != "information_requested":
            application = transition_application(
                application=application, to_status="information_requested",
                actor=request.user, reason=f"Information requested: {item.title}",
            )
        ApplicationMessage.objects.create(
            application=application, author_type=ApplicationMessage.AuthorType.SYSTEM,
            body=f"Information requested: {item.title}\n\n{item.instructions}",
            created_by=request.user, updated_by=request.user,
        )
        return Response(InformationRequestSerializer(item).data, status=201)

    @action(detail=True, methods=["get", "put"])
    def placement(self, request, pk=None):
        application = self.get_object()
        current = ApplicationPlacement.objects.filter(application=application).first()
        if request.method == "GET":
            if current is None:
                return Response({"detail": "Placement has not been assigned."}, status=404)
            return Response(ApplicationPlacementSerializer(current).data)
        if application.status not in {"approved", "enrollment_ready"}:
            return Response({"detail": "Placement can only be assigned after approval."}, status=400)
        serializer = ApplicationPlacementSerializer(current, data=request.data)
        serializer.is_valid(raise_exception=True)
        grade_level = serializer.validated_data["grade_level"]
        section = serializer.validated_data["section"]
        if section.grade_level_id != grade_level.id:
            return Response({"section": ["Section must belong to the selected grade level."]}, status=400)
        placement = serializer.save(application=application, updated_by=request.user, **({} if current else {"created_by": request.user}))
        return Response(ApplicationPlacementSerializer(placement).data)

    @action(detail=True, methods=["get"])
    def documents(self, request, pk=None):
        application = self.get_object()
        return Response(ApplicationDocumentSerializer(application.documents.select_related("requirement"), many=True).data)

    @action(detail=True, methods=["post"], url_path=r"documents/(?P<document_id>[^/.]+)/review")
    def review_document(self, request, pk=None, document_id=None):
        application = self.get_object()
        document = application.documents.filter(pk=document_id).first()
        if document is None:
            return Response({"detail": "Document not found."}, status=404)
        if document.scan_status != ApplicationDocument.ScanStatus.CLEAN:
            return Response({"detail": "Document cannot be reviewed until its security scan is complete."}, status=423)
        serializer = DocumentReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        document.review_status = serializer.validated_data["review_status"]
        document.review_note = serializer.validated_data["review_note"]
        document.updated_by = request.user
        document.save(update_fields=["review_status", "review_note", "updated_by", "updated_at"])
        return Response(ApplicationDocumentSerializer(document).data)

    @action(detail=True, methods=["get"], url_path=r"documents/(?P<document_id>[^/.]+)/download")
    def download_document(self, request, pk=None, document_id=None):
        application = self.get_object()
        document = application.documents.filter(pk=document_id).first()
        if document is None:
            return Response({"detail": "Document not found."}, status=404)
        if document.scan_status != ApplicationDocument.ScanStatus.CLEAN:
            return Response({"detail": "Document security scan is not complete."}, status=423)
        return Response({"url": document.file.storage.url(document.file.name, expire=300), "expires_in": 300})
