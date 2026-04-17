from datetime import timedelta

from django.db.models import Q
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from common.utils import get_object_by_uuid_or_fields
from .access_policies import HRAccessPolicy

from .models import (
    Employee,
    EmployeeDepartment,
    EmployeePosition,
    EmployeeDocument,
    EmployeeAttendance,
    EmployeePerformanceReview,
    EmployeeWorkflowTask,
    LeaveRequest,
    LeaveType,
    PayrollComponent,
    EmployeeCompensation,
    PayrollRun,
)
from .serializers import (
    EmployeeContactSerializer,
    EmployeeDepartmentSerializer,
    EmployeeDependentSerializer,
    EmployeePositionSerializer,
    EmployeeSerializer,
    EmployeeDocumentSerializer,
    EmployeeAttendanceSerializer,
    EmployeePerformanceReviewSerializer,
    EmployeeWorkflowTaskSerializer,
    LeaveRequestSerializer,
    LeaveTypeSerializer,
    PayrollComponentSerializer,
    EmployeeCompensationSerializer,
    PayrollRunSerializer,
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


class EmployeeDocumentViewSet(viewsets.ModelViewSet):
    serializer_class = EmployeeDocumentSerializer
    permission_classes = [HRAccessPolicy]

    def get_queryset(self):
        queryset = EmployeeDocument.objects.select_related("employee")

        search = self.request.query_params.get("search")
        if search:
            queryset = queryset.filter(
                Q(employee__first_name__icontains=search)
                | Q(employee__last_name__icontains=search)
                | Q(employee__id_number__icontains=search)
                | Q(title__icontains=search)
                | Q(document_number__icontains=search)
                | Q(issuing_authority__icontains=search)
            )

        employee_id = self.request.query_params.get("employee") or self.request.query_params.get("employee_id")
        if employee_id:
            queryset = queryset.filter(employee_id=employee_id)

        document_type = self.request.query_params.get("document_type")
        if document_type:
            queryset = queryset.filter(document_type__iexact=document_type)

        compliance_status = self.request.query_params.get("compliance_status")
        if compliance_status == "expired":
            queryset = queryset.filter(expiry_date__lt=timezone.localdate())
        elif compliance_status == "expiring_soon":
            today = timezone.localdate()
            queryset = queryset.filter(expiry_date__gte=today, expiry_date__lte=today + timedelta(days=30))
        elif compliance_status == "valid":
            queryset = queryset.filter(Q(expiry_date__isnull=True) | Q(expiry_date__gt=timezone.localdate() + timedelta(days=30)))

        return queryset.order_by("employee__first_name", "employee__last_name", "title")

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user, updated_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)


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


class EmployeeWorkflowTaskViewSet(viewsets.ModelViewSet):
    serializer_class = EmployeeWorkflowTaskSerializer
    permission_classes = [HRAccessPolicy]

    def get_queryset(self):
        queryset = EmployeeWorkflowTask.objects.select_related("employee", "assigned_to")

        search = self.request.query_params.get("search")
        if search:
            queryset = queryset.filter(
                Q(employee__first_name__icontains=search)
                | Q(employee__last_name__icontains=search)
                | Q(employee__id_number__icontains=search)
                | Q(title__icontains=search)
                | Q(description__icontains=search)
            )

        employee_id = self.request.query_params.get("employee") or self.request.query_params.get("employee_id")
        if employee_id:
            queryset = queryset.filter(employee_id=employee_id)

        workflow_type = self.request.query_params.get("workflow_type")
        if workflow_type:
            queryset = queryset.filter(workflow_type__iexact=workflow_type)

        status_param = self.request.query_params.get("status")
        if status_param:
            queryset = queryset.filter(status__iexact=status_param)

        category_param = self.request.query_params.get("category")
        if category_param:
            queryset = queryset.filter(category__iexact=category_param)

        return queryset.order_by("workflow_type", "due_date", "employee__first_name", "employee__last_name")

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user, updated_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)

    @action(detail=True, methods=["post"], url_path="mark-complete")
    def mark_complete(self, request, pk=None):
        task = self.get_object()
        task.updated_by = request.user
        task.mark_completed()
        return Response(self.get_serializer(task).data)


class PayrollComponentViewSet(viewsets.ModelViewSet):
    queryset = PayrollComponent.objects.all().order_by("component_type", "name")
    serializer_class = PayrollComponentSerializer
    permission_classes = [HRAccessPolicy]

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user, updated_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)


class EmployeeCompensationViewSet(viewsets.ModelViewSet):
    serializer_class = EmployeeCompensationSerializer
    permission_classes = [HRAccessPolicy]

    def get_queryset(self):
        queryset = EmployeeCompensation.objects.select_related("employee").prefetch_related("items__component")
        employee_id = self.request.query_params.get("employee") or self.request.query_params.get("employee_id")
        if employee_id:
            queryset = queryset.filter(employee_id=employee_id)
        return queryset.order_by("employee__first_name", "employee__last_name")

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user, updated_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)


class PayrollRunViewSet(viewsets.ModelViewSet):
    serializer_class = PayrollRunSerializer
    permission_classes = [HRAccessPolicy]

    def get_queryset(self):
        queryset = PayrollRun.objects.all()

        search = self.request.query_params.get("search")
        if search:
            queryset = queryset.filter(name__icontains=search)

        status_param = self.request.query_params.get("status")
        if status_param:
            queryset = queryset.filter(status__iexact=status_param)

        return queryset.order_by("-run_date", "name")

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user, updated_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)

    @action(detail=True, methods=["post"], url_path="process")
    def process(self, request, pk=None):
        payroll_run = self.get_object()
        payroll_run.status = PayrollRun.Status.COMPLETED
        payroll_run.updated_by = request.user
        payroll_run.save(update_fields=["status", "updated_by", "updated_at"])
        return Response(self.get_serializer(payroll_run).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="mark-paid")
    def mark_paid(self, request, pk=None):
        payroll_run = self.get_object()
        payroll_run.status = PayrollRun.Status.PAID
        payroll_run.payment_date = request.data.get("payment_date") or payroll_run.payment_date or timezone.localdate()
        payroll_run.updated_by = request.user
        payroll_run.save(update_fields=["status", "payment_date", "updated_by", "updated_at"])
        return Response(self.get_serializer(payroll_run).data, status=status.HTTP_200_OK)


class EmployeeViewSet(viewsets.ModelViewSet):
    serializer_class = EmployeeSerializer
    permission_classes = [HRAccessPolicy]

    def get_queryset(self):
        queryset = Employee.objects.select_related(
            "department",
            "position",
            "manager",
        ).prefetch_related("contacts", "dependents", "documents", "performance_reviews", "workflow_tasks", "leave_requests__leave_type")

        search = self.request.query_params.get("search")
        if search:
            queryset = queryset.filter(
                Q(first_name__icontains=search)
                | Q(last_name__icontains=search)
                | Q(middle_name__icontains=search)
                | Q(email__icontains=search)
                | Q(id_number__icontains=search)
                | Q(job_title__icontains=search)
            )

        department = self.request.query_params.get("department") or self.request.query_params.get("department_id")
        if department:
            queryset = queryset.filter(department_id=department)

        employment_status = self.request.query_params.get("employment_status")
        if employment_status:
            queryset = queryset.filter(employment_status__iexact=employment_status)

        is_teacher = self.request.query_params.get("is_teacher")
        if is_teacher is not None:
            if is_teacher.lower() in ['true', '1']:
                queryset = queryset.filter(
                    Q(is_teacher=True) | Q(position__can_teach=True)
                )
            elif is_teacher.lower() in ['false', '0']:
                queryset = queryset.filter(
                    Q(is_teacher=False) & (Q(position__can_teach=False) | Q(position__isnull=True))
                )

        return queryset.order_by("first_name", "last_name")

    def get_object(self):
        """Support lookup by both UUID id and id_number."""
        lookup_value = self.kwargs.get("pk")
        try:
            return get_object_by_uuid_or_fields(
                Employee,
                lookup_value,
                fields=['id_number']
            )
        except Employee.DoesNotExist:
            raise NotFound("Employee does not exist with this id")

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user, updated_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)

    @action(detail=False, methods=["get"], url_path=r"number/(?P<id_number>[^/.]+)")
    def by_number(self, request, id_number=None):
        employee = self.get_queryset().filter(id_number=id_number).first()
        if not employee:
            return Response({"detail": "Employee not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(self.get_serializer(employee).data)

    @action(detail=False, methods=["get"], url_path="teachers")
    def teachers(self, request):
        queryset = self.get_queryset().filter(
            Q(is_teacher=True) | Q(position__can_teach=True)
        ).distinct()
        page = self.paginate_queryset(queryset)
        if page is not None:
            return self.get_paginated_response(self.get_serializer(page, many=True).data)
        return Response(self.get_serializer(queryset, many=True).data)

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
