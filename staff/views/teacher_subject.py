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
            staff_filter = Q(teacher__id=teacher_id) | Q(teacher__id_number=teacher_id)
            # Also resolve via hr.Employee UUID or id_number
            from hr.models import Employee

            emp = Employee.objects.filter(
                Q(id=teacher_id) | Q(id_number=teacher_id)
            ).first()
            if emp:
                staff_filter |= Q(teacher__id_number=emp.id_number)
                if emp.user_account_id_number:
                    staff_filter |= Q(teacher__user_account_id_number=emp.user_account_id_number)
            queryset = queryset.filter(staff_filter).distinct()

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

        # Use get_or_create to prevent duplicates – do NOT also call
        # serializer.save() because that would insert a second row.
        obj, created = TeacherSubject.objects.get_or_create(
            teacher=teacher,
            section_subject=section_subject,
            defaults={
                "subject": subject or section_subject.subject,
                "created_by": self.request.user,
                "updated_by": self.request.user,
            },
        )
        # Point the serializer at the (possibly existing) instance so
        # DRF's CreateModelMixin.create() can serialize the response.
        serializer.instance = obj

