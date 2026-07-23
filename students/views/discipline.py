from django.db.models import Q
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from ..access_policies import StudentAccessPolicy
from common.status import EnrollmentStatus, StudentStatus
from ..models import (
    Student,
    StudentDisciplinaryAction,
    Enrollment,
    DisciplinaryActionType,
)
from ..serializers import (
    StudentDisciplinaryActionSerializer,
    DisciplinaryActionTypeSerializer,
)


class StudentDisciplinaryActionPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class DisciplinaryActionTypeListCreateView(APIView):
    permission_classes = [StudentAccessPolicy]

    def get(self, request):
        include_inactive = str(request.query_params.get("include_inactive", "false")).lower() in {
            "1",
            "true",
            "yes",
        }
        queryset = DisciplinaryActionType.objects.all()
        if not include_inactive:
            queryset = queryset.filter(active=True)

        serializer = DisciplinaryActionTypeSerializer(queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        serializer = DisciplinaryActionTypeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(created_by=request.user, updated_by=request.user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class DisciplinaryActionTypeDetailView(APIView):
    permission_classes = [StudentAccessPolicy]

    def get_object(self, action_type_id):
        action_type = DisciplinaryActionType.objects.filter(id=action_type_id).first()
        if not action_type:
            raise NotFound("Disciplinary action type does not exist with this id")
        return action_type

    def get(self, request, id):
        action_type = self.get_object(id)
        serializer = DisciplinaryActionTypeSerializer(action_type)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def put(self, request, id):
        action_type = self.get_object(id)
        serializer = DisciplinaryActionTypeSerializer(
            action_type,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save(updated_by=request.user)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def delete(self, request, id):
        action_type = self.get_object(id)
        action_type.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


ALLOWED_STUDENT_STATUS_UPDATES = {
    StudentStatus.ACTIVE,
    StudentStatus.SUSPENDED,
    StudentStatus.WITHDRAWN,
}

ALLOWED_ENROLLMENT_STATUS_UPDATES = {
    EnrollmentStatus.ENROLLED,
    EnrollmentStatus.PENDING,
    EnrollmentStatus.COMPLETED,
    EnrollmentStatus.CANCELED,
    EnrollmentStatus.WITHDRAWN,
}


def _extract_status_updates(payload):
    data = dict(payload)
    student_status_update = (data.pop("student_status_update", "") or "").strip().lower()
    enrollment_status_update = (data.pop("enrollment_status_update", "") or "").strip().lower()

    if student_status_update and student_status_update not in ALLOWED_STUDENT_STATUS_UPDATES:
        return None, None, None, Response(
            {"detail": "Invalid student_status_update value."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if enrollment_status_update and enrollment_status_update not in ALLOWED_ENROLLMENT_STATUS_UPDATES:
        return None, None, None, Response(
            {"detail": "Invalid enrollment_status_update value."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    return data, student_status_update, enrollment_status_update, None


def _apply_status_updates(student, student_status_update, enrollment_status_update, user):
    updates = {}

    if student_status_update and student.status != student_status_update:
        student.status = student_status_update
        student.updated_by = user
        student.save(update_fields=["status", "updated_by", "updated_at"])
        updates["student_status"] = student_status_update

    if enrollment_status_update:
        current_enrollment = (
            Enrollment.objects.filter(student=student, academic_year__current=True)
            .order_by("-created_at")
            .first()
        )
        if current_enrollment and current_enrollment.status != enrollment_status_update:
            current_enrollment.status = enrollment_status_update
            current_enrollment.updated_by = user
            current_enrollment.save(update_fields=["status", "updated_by", "updated_at"])
            updates["enrollment_status"] = enrollment_status_update

    return updates


def _ensure_action_text_from_type(serializer):
    action_type = serializer.validated_data.get("action_type")
    title = serializer.validated_data.get("title")
    action_taken = serializer.validated_data.get("action_taken")

    if action_type and not title:
        serializer.validated_data["title"] = action_type.name

    if action_type and not action_taken:
        serializer.validated_data["action_taken"] = (
            action_type.description or action_type.name
        )

    if action_type and not serializer.validated_data.get("severity"):
        serializer.validated_data["severity"] = action_type.default_severity

    if action_type and not serializer.validated_data.get("duration_days"):
        serializer.validated_data["duration_days"] = action_type.default_duration_days


class StudentDisciplinaryActionListCreateView(APIView):
    permission_classes = [StudentAccessPolicy]
    pagination_class = StudentDisciplinaryActionPagination

    def get(self, request):
        status_filter = (request.query_params.get("status") or "all").strip().lower()
        student_id = (request.query_params.get("student") or "").strip()
        search = (request.query_params.get("search") or "").strip()

        queryset = StudentDisciplinaryAction.objects.select_related("student").all()
        today = timezone.localdate()

        if student_id:
            queryset = queryset.filter(
                Q(student__id=student_id)
                | Q(student__id_number__iexact=student_id)
                | Q(student__prev_id_number__iexact=student_id)
            )

        if search:
            queryset = queryset.filter(
                Q(title__icontains=search)
                | Q(action_taken__icontains=search)
                | Q(description__icontains=search)
                | Q(student__first_name__icontains=search)
                | Q(student__last_name__icontains=search)
                | Q(student__id_number__icontains=search)
            )

        if status_filter == "active":
            queryset = queryset.filter(
                active=True,
                status=StudentDisciplinaryAction.Status.ACTIVE,
                start_date__lte=today,
                end_date__gte=today,
            )
        elif status_filter == "inactive":
            queryset = queryset.exclude(
                active=True,
                status=StudentDisciplinaryAction.Status.ACTIVE,
                start_date__lte=today,
                end_date__gte=today,
            )

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request)
        serializer = StudentDisciplinaryActionSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    def post(self, request):
        payload, student_status_update, enrollment_status_update, error_response = _extract_status_updates(
            request.data
        )
        if error_response:
            return error_response

        serializer = StudentDisciplinaryActionSerializer(data=payload)
        serializer.is_valid(raise_exception=True)
        _ensure_action_text_from_type(serializer)
        record = serializer.save(created_by=request.user, updated_by=request.user)

        updates = _apply_status_updates(
            record.student,
            student_status_update,
            enrollment_status_update,
            request.user,
        )

        response_data = StudentDisciplinaryActionSerializer(record).data
        response_data["status_updates_applied"] = updates
        return Response(response_data, status=status.HTTP_201_CREATED)


class StudentDisciplinaryActionDetailView(APIView):
    permission_classes = [StudentAccessPolicy]

    def get_object(self, record_id):
        record = (
            StudentDisciplinaryAction.objects.select_related("student")
            .filter(id=record_id)
            .first()
        )
        if not record:
            raise NotFound("Disciplinary action does not exist with this id")
        return record

    def get(self, request, id):
        record = self.get_object(id)
        serializer = StudentDisciplinaryActionSerializer(record)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def put(self, request, id):
        record = self.get_object(id)
        serializer = StudentDisciplinaryActionSerializer(
            record,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save(updated_by=request.user)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def delete(self, request, id):
        record = self.get_object(id)
        record.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class StudentDisciplinaryActionByStudentListCreateView(APIView):
    permission_classes = [StudentAccessPolicy]
    pagination_class = StudentDisciplinaryActionPagination

    def get_student(self, student_id):
        student = (
            Student.objects.filter(
                Q(id=student_id)
                | Q(id_number__iexact=student_id)
                | Q(prev_id_number__iexact=student_id)
            )
            .first()
        )
        if not student:
            raise NotFound("Student does not exist with this id")
        return student

    def get(self, request, student_id):
        student = self.get_student(student_id)
        status_filter = (request.query_params.get("status") or "all").strip().lower()
        today = timezone.localdate()

        queryset = StudentDisciplinaryAction.objects.select_related("student").filter(
            student=student
        )

        if status_filter == "active":
            queryset = queryset.filter(
                active=True,
                status=StudentDisciplinaryAction.Status.ACTIVE,
                start_date__lte=today,
                end_date__gte=today,
            )
        elif status_filter == "inactive":
            queryset = queryset.exclude(
                active=True,
                status=StudentDisciplinaryAction.Status.ACTIVE,
                start_date__lte=today,
                end_date__gte=today,
            )

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request)
        serializer = StudentDisciplinaryActionSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    def post(self, request, student_id):
        student = self.get_student(student_id)
        request_payload, student_status_update, enrollment_status_update, error_response = _extract_status_updates(
            request.data
        )
        if error_response:
            return error_response

        payload = {**request_payload, "student": str(student.id)}
        serializer = StudentDisciplinaryActionSerializer(data=payload)
        serializer.is_valid(raise_exception=True)
        _ensure_action_text_from_type(serializer)
        record = serializer.save(created_by=request.user, updated_by=request.user)

        updates = _apply_status_updates(
            student,
            student_status_update,
            enrollment_status_update,
            request.user,
        )

        response_data = StudentDisciplinaryActionSerializer(record).data
        response_data["status_updates_applied"] = updates
        return Response(response_data, status=status.HTTP_201_CREATED)
