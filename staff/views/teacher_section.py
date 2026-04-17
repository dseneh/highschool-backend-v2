from django.db.models import Q
from rest_framework import viewsets, serializers
from rest_framework.pagination import PageNumberPagination

from ..models import TeacherSection
from ..serializers import TeacherSectionSerializer
from ..access_policies import StaffAccessPolicy


class TeacherSectionPageNumberPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class TeacherSectionViewSet(viewsets.ModelViewSet):
    """
    ViewSet for TeacherSection CRUD operations with maximum optimization.

    Endpoints:
    - GET /teacher-sections/ - List teacher sections
    - POST /teacher-sections/ - Create teacher section
    - GET /teacher-sections/<pk>/ - Get teacher section detail
    - PUT/PATCH /teacher-sections/<pk>/ - Update teacher section
    - DELETE /teacher-sections/<pk>/ - Delete teacher section
    """

    permission_classes = [StaffAccessPolicy]
    pagination_class = TeacherSectionPageNumberPagination
    serializer_class = TeacherSectionSerializer

    def get_queryset(self):
        """Get optimized queryset with all necessary relations"""
        queryset = TeacherSection.objects.select_related(
            "teacher",
            "section",
            "section__grade_level",
        ).all()

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

        section_id = self.request.query_params.get("section")
        if section_id:
            queryset = queryset.filter(section_id=section_id)

        # Apply ordering
        ordering = self.request.query_params.get("ordering", "-created_at")
        queryset = queryset.order_by(ordering)

        return queryset

    def perform_create(self, serializer):
        """Create teacher section with validation"""
        teacher_id = serializer.validated_data.get("teacher")
        section_id = serializer.validated_data.get("section")

        # Check if assignment already exists
        if TeacherSection.objects.filter(
            teacher=teacher_id, section=section_id
        ).exists():
            raise serializers.ValidationError(
                "Teacher is already assigned to this section"
            )

        serializer.save(created_by=self.request.user, updated_by=self.request.user)

