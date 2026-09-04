from django.db.models import Prefetch
from django.utils import timezone
from rest_framework import filters, status, viewsets
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from authorization.drf import RBACPermission

from .models import AdmissionApplication, AdmissionCycle, ApplicationStatusHistory
from .serializers import AdmissionApplicationSerializer, AdmissionCycleSerializer, ApplicationTransitionSerializer, PublicAdmissionCycleSerializer
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
