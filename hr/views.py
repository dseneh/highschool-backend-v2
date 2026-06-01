from datetime import timedelta
from uuid import UUID

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import status, viewsets, serializers
from rest_framework.decorators import action
from rest_framework.response import Response

from .access_policies import HRAccessPolicy

from .models import (
    Employee,
    EmployeeDepartment,
    EmployeePosition,
    EmployeeSpecialization,
    EmployeeTeacherSection,
    EmployeeTeacherSubject,
    EmployeeAttendance,
    EmployeePerformanceReview,
    LeaveRequest,
    LeaveType,
)
from .serializers import (
    EmployeeContactSerializer,
    EmployeeDepartmentSerializer,
    EmployeeDependentSerializer,
    EmployeePositionSerializer,
    EmployeeSpecializationSerializer,
    EmployeeTeacherSectionSerializer,
    EmployeeTeacherSubjectSerializer,
    EmployeeSerializer,
    EmployeeAttendanceSerializer,
    EmployeePerformanceReviewSerializer,
    LeaveRequestSerializer,
    LeaveTypeSerializer,
)


class EmployeeDepartmentViewSet(viewsets.ModelViewSet):
    queryset = EmployeeDepartment.objects.all().order_by("name")
    serializer_class = EmployeeDepartmentSerializer
    permission_classes = [HRAccessPolicy]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user, updated_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)


class EmployeePositionViewSet(viewsets.ModelViewSet):
    queryset = EmployeePosition.objects.select_related("department").all().order_by("title")
    serializer_class = EmployeePositionSerializer
    permission_classes = [HRAccessPolicy]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user, updated_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)


class EmployeeSpecializationViewSet(viewsets.ModelViewSet):
    queryset = EmployeeSpecialization.objects.select_related("employee", "subject").all()
    serializer_class = EmployeeSpecializationSerializer
    permission_classes = [HRAccessPolicy]

    def get_queryset(self):
        qs = super().get_queryset()
        employee_id = self.request.query_params.get("employee")
        if employee_id:
            qs = qs.filter(employee_id=employee_id)
        return qs.order_by("subject__name")

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user, updated_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)


class EmployeeTeacherSectionViewSet(viewsets.ModelViewSet):
    serializer_class = EmployeeTeacherSectionSerializer
    permission_classes = [HRAccessPolicy]

    def get_queryset(self):
        queryset = EmployeeTeacherSection.objects.select_related(
            "teacher",
            "section",
            "section__grade_level",
        )

        teacher_id = self.request.query_params.get("teacher")
        if teacher_id:
            teacher_filter = Q(teacher__id=teacher_id) | Q(teacher__id_number=teacher_id)

            from staff.models import Staff

            staff = Staff.objects.filter(Q(id=teacher_id) | Q(id_number=teacher_id)).first()
            if staff:
                teacher_filter |= Q(teacher__id_number=staff.id_number)
                if staff.user_account_id_number:
                    teacher_filter |= Q(teacher__user_account_id_number=staff.user_account_id_number)

            queryset = queryset.filter(teacher_filter).distinct()

        section_id = self.request.query_params.get("section")
        if section_id:
            queryset = queryset.filter(section_id=section_id)

        ordering = self.request.query_params.get("ordering", "-created_at")
        return queryset.order_by(ordering)

    def perform_create(self, serializer):
        teacher = serializer.validated_data.get("teacher")
        section = serializer.validated_data.get("section")

        if EmployeeTeacherSection.objects.filter(teacher=teacher, section=section).exists():
            raise serializers.ValidationError("Teacher is already assigned to this section")

        serializer.save(created_by=self.request.user, updated_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)


class EmployeeTeacherSubjectViewSet(viewsets.ModelViewSet):
    serializer_class = EmployeeTeacherSubjectSerializer
    permission_classes = [HRAccessPolicy]

    def get_queryset(self):
        queryset = EmployeeTeacherSubject.objects.select_related(
            "teacher",
            "subject",
            "section_subject",
            "section_subject__section",
            "section_subject__section__grade_level",
            "section_subject__subject",
        )

        teacher_id = self.request.query_params.get("teacher")
        if teacher_id:
            teacher_filter = Q(teacher__id=teacher_id) | Q(teacher__id_number=teacher_id)

            from staff.models import Staff

            staff = Staff.objects.filter(Q(id=teacher_id) | Q(id_number=teacher_id)).first()
            if staff:
                teacher_filter |= Q(teacher__id_number=staff.id_number)
                if staff.user_account_id_number:
                    teacher_filter |= Q(teacher__user_account_id_number=staff.user_account_id_number)

            queryset = queryset.filter(teacher_filter).distinct()

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

        ordering = self.request.query_params.get("ordering", "-created_at")
        return queryset.order_by(ordering)

    def perform_create(self, serializer):
        teacher = serializer.validated_data.get("teacher")
        section_subject = serializer.validated_data.get("section_subject")
        subject = serializer.validated_data.get("subject")

        if not section_subject:
            raise serializers.ValidationError(
                {"detail": "section_subject is required for teacher subject assignment."}
            )

        with transaction.atomic():
            obj, _created = EmployeeTeacherSubject.objects.get_or_create(
                teacher=teacher,
                section_subject=section_subject,
                defaults={
                    "subject": subject or section_subject.subject,
                    "created_by": self.request.user,
                    "updated_by": self.request.user,
                },
            )

            # Keep section assignment in sync with subject assignment.
            EmployeeTeacherSection.objects.get_or_create(
                teacher=teacher,
                section=section_subject.section,
                defaults={
                    "created_by": self.request.user,
                    "updated_by": self.request.user,
                },
            )

            serializer.instance = obj

    def perform_update(self, serializer):
        with transaction.atomic():
            obj = serializer.save(updated_by=self.request.user)
            if obj.section_subject_id:
                EmployeeTeacherSection.objects.get_or_create(
                    teacher=obj.teacher,
                    section=obj.section_subject.section,
                    defaults={
                        "created_by": self.request.user,
                        "updated_by": self.request.user,
                    },
                )


class LeaveTypeViewSet(viewsets.ModelViewSet):
    queryset = LeaveType.objects.all().order_by("name")
    serializer_class = LeaveTypeSerializer
    permission_classes = [HRAccessPolicy]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user, updated_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)


class LeaveRequestViewSet(viewsets.ModelViewSet):
    serializer_class = LeaveRequestSerializer
    permission_classes = [HRAccessPolicy]

    def perform_create(self, serializer):
        leave_request = serializer.save(created_by=self.request.user, updated_by=self.request.user)
        if not leave_request.leave_type.requires_approval:
            leave_request.approve(review_note="Auto-approved by leave type configuration.")

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)

    def perform_destroy(self, instance):
        # Keep employee lifecycle consistent when deleting an already-approved leave.
        if (
            instance.status == LeaveRequest.Status.APPROVED
            and instance.employee.employment_status == Employee.EmploymentStatus.ON_LEAVE
        ):
            instance.employee.employment_status = Employee.EmploymentStatus.ACTIVE
            instance.employee.updated_by = self.request.user
            instance.employee.save(update_fields=["employment_status", "updated_by", "updated_at"])

        instance.delete()

    def get_queryset(self):
        queryset = LeaveRequest.objects.select_related("employee", "leave_type")

        search = self.request.query_params.get("search")
        if search:
            queryset = queryset.filter(
                Q(employee__first_name__icontains=search)
                | Q(employee__last_name__icontains=search)
                | Q(employee__id_number__icontains=search)
                | Q(leave_type__name__icontains=search)
            )

        employee_id = self.request.query_params.get("employee") or self.request.query_params.get("employee_id")
        if employee_id:
            queryset = queryset.filter(employee_id=employee_id)

        leave_type_id = self.request.query_params.get("leave_type") or self.request.query_params.get("leave_type_id")
        if leave_type_id:
            queryset = queryset.filter(leave_type_id=leave_type_id)

        status_param = self.request.query_params.get("status")
        if status_param:
            queryset = queryset.filter(status__iexact=status_param)

        return queryset.order_by("-start_date", "-created_at")

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        leave_request = self.get_object()
        leave_request.review_note = request.data.get("review_note") or request.data.get("note")
        leave_request.updated_by = request.user
        leave_request.approve(review_note=leave_request.review_note)
        return Response(self.get_serializer(leave_request).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        leave_request = self.get_object()
        leave_request.review_note = request.data.get("review_note") or request.data.get("note")
        leave_request.updated_by = request.user
        leave_request.reject(review_note=leave_request.review_note)
        return Response(self.get_serializer(leave_request).data)

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        leave_request = self.get_object()
        leave_request.review_note = request.data.get("review_note") or request.data.get("note")
        leave_request.updated_by = request.user
        leave_request.cancel(review_note=leave_request.review_note)
        return Response(self.get_serializer(leave_request).data)

    @action(detail=True, methods=["post"])
    def revert(self, request, pk=None):
        leave_request = self.get_object()

        leave_request.status = LeaveRequest.Status.PENDING
        leave_request.reviewed_at = None
        leave_request.review_note = request.data.get("review_note") or request.data.get("note") or None
        leave_request.updated_by = request.user
        leave_request.save(update_fields=["status", "reviewed_at", "review_note", "updated_by", "updated_at"])

        if leave_request.employee.employment_status == Employee.EmploymentStatus.ON_LEAVE:
            leave_request.employee.employment_status = Employee.EmploymentStatus.ACTIVE
            leave_request.employee.updated_by = request.user
            leave_request.employee.save(update_fields=["employment_status", "updated_by", "updated_at"])

        return Response(self.get_serializer(leave_request).data)


class EmployeeAttendanceViewSet(viewsets.ModelViewSet):
    serializer_class = EmployeeAttendanceSerializer
    permission_classes = [HRAccessPolicy]

    def get_queryset(self):
        queryset = EmployeeAttendance.objects.select_related("employee")

        search = self.request.query_params.get("search")
        if search:
            queryset = queryset.filter(
                Q(employee__first_name__icontains=search)
                | Q(employee__last_name__icontains=search)
                | Q(employee__id_number__icontains=search)
                | Q(notes__icontains=search)
            )

        employee_id = self.request.query_params.get("employee") or self.request.query_params.get("employee_id")
        if employee_id:
            queryset = queryset.filter(employee_id=employee_id)

        status_param = self.request.query_params.get("status")
        if status_param:
            queryset = queryset.filter(status__iexact=status_param)

        attendance_date = self.request.query_params.get("attendance_date")
        if attendance_date:
            queryset = queryset.filter(attendance_date=attendance_date)

        return queryset.order_by("-attendance_date", "employee__first_name", "employee__last_name")

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user, updated_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)


class EmployeePerformanceReviewViewSet(viewsets.ModelViewSet):
    serializer_class = EmployeePerformanceReviewSerializer
    permission_classes = [HRAccessPolicy]

    def get_queryset(self):
        queryset = EmployeePerformanceReview.objects.select_related("employee", "reviewer")

        search = self.request.query_params.get("search")
        if search:
            queryset = queryset.filter(
                Q(employee__first_name__icontains=search)
                | Q(employee__last_name__icontains=search)
                | Q(employee__id_number__icontains=search)
                | Q(review_title__icontains=search)
                | Q(review_period__icontains=search)
            )

        employee_id = self.request.query_params.get("employee") or self.request.query_params.get("employee_id")
        if employee_id:
            queryset = queryset.filter(employee_id=employee_id)

        status_param = self.request.query_params.get("status")
        if status_param:
            queryset = queryset.filter(status__iexact=status_param)

        rating_param = self.request.query_params.get("rating")
        if rating_param:
            queryset = queryset.filter(rating__iexact=rating_param)

        return queryset.order_by("-review_date", "employee__first_name", "employee__last_name")

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user, updated_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)


class EmployeeViewSet(viewsets.ModelViewSet):
    serializer_class = EmployeeSerializer
    permission_classes = [HRAccessPolicy]

    def get_queryset(self):
        queryset = Employee.objects.select_related(
            "department",
            "position",
            "manager",
        ).prefetch_related(
            "contacts",
            "dependents",
            "specializations__subject",
            "performance_reviews",
            "leave_requests__leave_type",
        )

        from hr.employee_filters import apply_employee_list_filters

        queryset = apply_employee_list_filters(queryset, self.request.query_params)
        return queryset.order_by("first_name", "last_name")

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user, updated_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)

    def get_object(self):
        """Look up employees by either UUID ``id`` or ``id_number``.

        The default router uses ``pk`` in the URL. Callers may pass either
        the UUID primary key or the human-readable ``id_number`` (e.g.
        ``EMP-000001``) and we resolve to the right record.
        """
        from django.http import Http404

        queryset = self.filter_queryset(self.get_queryset())
        lookup_value = self.kwargs.get(self.lookup_url_kwarg or self.lookup_field)

        obj = None
        if lookup_value:
            try:
                UUID(str(lookup_value))
                obj = queryset.filter(pk=lookup_value).first()
            except (ValueError, TypeError):
                obj = None
            if obj is None:
                obj = queryset.filter(id_number=lookup_value).first()

        if obj is None:
            raise Http404("Employee not found.")

        self.check_object_permissions(self.request, obj)
        return obj

    @action(detail=False, methods=["get"], url_path=r"number/(?P<employee_number>[^/.]+)")
    def by_number(self, request, employee_number=None):
        employee = self.get_queryset().filter(id_number=employee_number).first()
        if not employee:
            return Response({"detail": "Employee not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(self.get_serializer(employee).data)

    @action(detail=True, methods=["post"])
    def terminate(self, request, pk=None):
        employee = self.get_object()
        employee.termination_date = request.data.get("termination_date") or timezone.now().date()
        employee.termination_reason = request.data.get("reason") or request.data.get("termination_reason")
        employee.employment_status = Employee.EmploymentStatus.TERMINATED
        employee.updated_by = request.user
        employee.save(
            update_fields=[
                "termination_date",
                "termination_reason",
                "employment_status",
                "updated_by",
                "updated_at",
            ]
        )
        return Response(self.get_serializer(employee).data)

    @action(detail=True, methods=["post"], url_path="contacts")
    def add_contact(self, request, pk=None):
        employee = self.get_object()
        serializer = EmployeeContactSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        if serializer.validated_data.get("is_primary"):
            employee.contacts.update(is_primary=False)

        serializer.save(employee=employee, created_by=request.user, updated_by=request.user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="dependents")
    def add_dependent(self, request, pk=None):
        employee = self.get_object()
        serializer = EmployeeDependentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(employee=employee, created_by=request.user, updated_by=request.user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
