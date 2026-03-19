from django.db.models import Q
from rest_framework import viewsets, serializers
from rest_framework.pagination import PageNumberPagination

from ..models import TeacherSubject, TeacherSection
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
                "section_subject",
                "section_subject__section",
                "section_subject__section__grade_level",
                "section_subject__subject",
            )
            .all()
        )

        # Apply filters
        teacher_id = self.request.query_params.get("teacher")
        if teacher_id:
            queryset = queryset.filter(
                Q(teacher__id=teacher_id) | Q(teacher__id_number=teacher_id)
            )

        section_subject_id = self.request.query_params.get("section_subject")
        if section_subject_id:
            queryset = queryset.filter(section_subject_id=section_subject_id)

        section_id = self.request.query_params.get("section")
        if section_id:
            queryset = queryset.filter(section_subject__section_id=section_id)

        subject_id = self.request.query_params.get("subject")
        if subject_id:
            queryset = queryset.filter(
                Q(subject_id=subject_id) | Q(section_subject__subject_id=subject_id)
            )

        # Apply ordering
        ordering = self.request.query_params.get("ordering", "-created_at")
        queryset = queryset.order_by(ordering)

        return queryset

    def perform_create(self, serializer):
        """Create teacher subject with validation"""
        teacher = serializer.validated_data.get("teacher")
        section_subject = serializer.validated_data.get("section_subject")
        subject = serializer.validated_data.get("subject")

        if not section_subject:
            raise serializers.ValidationError(
                {"detail": "section_subject is required for teacher subject assignment."}
            )

        # teacher_has_section = TeacherSection.objects.filter(
        #     teacher=teacher,
        #     section=section_subject.section,
        # ).exists()
        # if not teacher_has_section:
        #     raise serializers.ValidationError(
        #         {"detail": "Teacher must be assigned to the section before assigning its subjects"}
        #     )
        created, _ = TeacherSubject.objects.get_or_create(
            teacher=teacher,
            section_subject=section_subject,
            defaults={
                "subject": subject or section_subject.subject,
                "created_by": self.request.user,
                "updated_by": self.request.user,
            })

        # Check if assignment already exists
        # if TeacherSubject.objects.filter(
        #     teacher=teacher,
        #     section_subject=section_subject,
        # ).exists():
        #     raise serializers.ValidationError(
        #         {"detail": "Teacher is already assigned to this section subject"}
        #     )

        serializer.save(
            subject=subject or section_subject.subject,
            created_by=self.request.user,
            updated_by=self.request.user,
        )

