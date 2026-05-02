from datetime import timedelta
from uuid import UUID

from django.db.models import Q
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .access_policies import HRAccessPolicy

from .models import (
    Employee,
    EmployeeDepartment,
    EmployeePosition,
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

    def get_queryset(self):
        queryset = LeaveRequest.objects.select_related("employee", "leave_type")

        search = self.request.query_params.get("search")
        if search:
            queryset = queryset.filter(
                Q(employee__first_name__icontains=search)
                | Q(employee__last_name__icontains=search)
                | Q(employee__employee_number__icontains=search)
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
                | Q(employee__employee_number__icontains=search)
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
                | Q(employee__employee_number__icontains=search)
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
        ).prefetch_related("contacts", "dependents", "performance_reviews", "leave_requests__leave_type")

        search = self.request.query_params.get("search")
        if search:
            queryset = queryset.filter(
                Q(first_name__icontains=search)
                | Q(last_name__icontains=search)
                | Q(middle_name__icontains=search)
                | Q(email__icontains=search)
                | Q(employee_number__icontains=search)
                | Q(job_title__icontains=search)
            )

        department = self.request.query_params.get("department") or self.request.query_params.get("department_id")
        if department:
            queryset = queryset.filter(department_id=department)

        employment_status = self.request.query_params.get("employment_status")
        if employment_status:
            queryset = queryset.filter(employment_status__iexact=employment_status)

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
        employee = self.get_queryset().filter(employee_number=employee_number).first()
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
