from django.db.models import Q
from rest_framework import viewsets, serializers
from rest_framework.pagination import PageNumberPagination

from ..models import TeacherSchedule
from ..serializers import TeacherScheduleSerializer
from ..access_policies import StaffAccessPolicy


class TeacherSchedulePageNumberPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class TeacherScheduleViewSet(viewsets.ModelViewSet):
    """
    ViewSet for TeacherSchedule CRUD operations with maximum optimization.

    Endpoints:
    - GET /teacher-schedules/ - List teacher schedules
    - POST /teacher-schedules/ - Create teacher schedule
    - GET /teacher-schedules/<pk>/ - Get teacher schedule detail
    - PUT/PATCH /teacher-schedules/<pk>/ - Update teacher schedule
    - DELETE /teacher-schedules/<pk>/ - Delete teacher schedule
    """

    permission_classes = [StaffAccessPolicy]
    pagination_class = TeacherSchedulePageNumberPagination
    serializer_class = TeacherScheduleSerializer

    def get_queryset(self):
        """Get optimized queryset with all necessary relations"""
        queryset = TeacherSchedule.objects.select_related(
            "teacher",
            "class_schedule",
            "class_schedule__section",
            "class_schedule__section__grade_level",
            "class_schedule__period",
        ).all()

        # Apply filters
        teacher_id = self.request.query_params.get("teacher")
        if teacher_id:
            queryset = queryset.filter(
                Q(teacher__id=teacher_id) | Q(teacher__id_number=teacher_id)
            )

        schedule_id = self.request.query_params.get("class_schedule")
        if schedule_id:
            queryset = queryset.filter(class_schedule_id=schedule_id)

        # Apply ordering
        ordering = self.request.query_params.get("ordering", "-created_at")
        queryset = queryset.order_by(ordering)

        return queryset

    def perform_create(self, serializer):
        """Create teacher schedule with validation"""
        teacher_id = serializer.validated_data.get("teacher")
        class_schedule_id = serializer.validated_data.get("class_schedule")

        # Check if assignment already exists
        if TeacherSchedule.objects.filter(
            teacher=teacher_id, class_schedule=class_schedule_id
        ).exists():
            raise serializers.ValidationError(
                "Teacher is already assigned to this schedule"
            )

        serializer.save(created_by=self.request.user, updated_by=self.request.user)

