from django.db.models import Q
from rest_framework import viewsets, serializers
from rest_framework.pagination import PageNumberPagination

from ..models import TeacherSubject
from ..serializers import TeacherSubjectSerializer
from ..access_policies import StaffAccessPolicy


class TeacherSubjectPageNumberPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class TeacherSubjectViewSet(viewsets.ModelViewSet):
    """
    ViewSet for TeacherSubject CRUD operations with maximum optimization.
    
    Endpoints:
    - GET /teacher-subjects/ - List teacher subjects
    - POST /teacher-subjects/ - Create teacher subject
    - GET /teacher-subjects/<pk>/ - Get teacher subject detail
    - PUT/PATCH /teacher-subjects/<pk>/ - Update teacher subject
    - DELETE /teacher-subjects/<pk>/ - Delete teacher subject
    """

    permission_classes = [StaffAccessPolicy]
    pagination_class = TeacherSubjectPageNumberPagination
    serializer_class = TeacherSubjectSerializer

    def get_queryset(self):
        """Get optimized queryset with all necessary relations"""
        queryset = (
            TeacherSubject.objects.select_related(
                "teacher",
                "subject",
            )
            .all()
        )

        # Apply filters
        teacher_id = self.request.query_params.get("teacher")
        if teacher_id:
            queryset = queryset.filter(
                Q(teacher__id=teacher_id) | Q(teacher__id_number=teacher_id)
            )

        subject_id = self.request.query_params.get("subject")
        if subject_id:
            queryset = queryset.filter(subject_id=subject_id)

        # Apply ordering
        ordering = self.request.query_params.get("ordering", "-created_at")
        queryset = queryset.order_by(ordering)

        return queryset

    def perform_create(self, serializer):
        """Create teacher subject with validation"""
        teacher_id = serializer.validated_data.get("teacher")
        subject_id = serializer.validated_data.get("subject")

        # Check if assignment already exists
        if TeacherSubject.objects.filter(
            teacher=teacher_id, subject=subject_id
        ).exists():
            raise serializers.ValidationError(
                "Teacher is already assigned to this subject"
            )

        serializer.save(created_by=self.request.user, updated_by=self.request.user)

