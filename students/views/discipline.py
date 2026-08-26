from django.db.models import Q
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from ..access_policies import StudentDisciplineAccessPolicy
from students.authorization import (
    filter_students_for_permission_scope,
    permission_scope,
    user_can_access_student_for_permission,
)
from ..services.discipline_attendance import (
    ALLOWED_RESOLUTIONS,
    apply_attendance_effect_for_discipline,
    count_unresolved_attendance_impacts_after,
    resolve_attendance_impacts_after,
)
from ..models import (
    Student,
    StudentDisciplinaryAction,
    DisciplinaryActionType,
)
from ..serializers import (
    StudentDisciplinaryActionSerializer,
    DisciplinaryActionTypeSerializer,
)
from ..services.student_status import compute_is_enrolled


def _ensure_currently_enrolled_for_discipline(student):
    if not compute_is_enrolled(student):
        raise PermissionDenied({
            "code": "discipline_restricted_not_enrolled",
            "detail": "Disciplinary actions can only be created or changed for students currently enrolled in this academic year.",
        })


def _require_discipline_student_access(student, request, permission_code):
    if not user_can_access_student_for_permission(
        student,
        request,
        permission_code,
    ):
        raise PermissionDenied("You cannot access discipline records for this student.")


def _require_all_discipline_manage_scope(request):
    if permission_scope(request, "students.discipline.manage") != "all":
        raise PermissionDenied("Discipline configuration requires students.discipline.manage:all.")


class StudentDisciplinaryActionPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class DisciplinaryActionTypeListCreateView(APIView):
    permission_classes = [StudentDisciplineAccessPolicy]
    policy_action_map = {"get": "get", "post": "manage"}

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
        _require_all_discipline_manage_scope(request)
        serializer = DisciplinaryActionTypeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(created_by=request.user, updated_by=request.user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class DisciplinaryActionTypeDetailView(APIView):
    permission_classes = [StudentDisciplineAccessPolicy]
    policy_action_map = {"get": "get", "put": "manage", "delete": "manage"}

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
        _require_all_discipline_manage_scope(request)
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
        _require_all_discipline_manage_scope(request)
        action_type = self.get_object(id)
        action_type.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


def _extract_status_updates(payload):
    data = dict(payload)
    student_status_update = (data.pop("student_status_update", "") or "").strip().lower()
    enrollment_status_update = (data.pop("enrollment_status_update", "") or "").strip().lower()

    if student_status_update:
        return None, None, Response(
            {
                "detail": (
                    "student_status_update is no longer supported in discipline actions. "
                    "Use dedicated student lifecycle endpoints for student status changes."
                )
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    if enrollment_status_update:
        return None, None, Response(
            {
                "detail": (
                    "enrollment_status_update is no longer supported in discipline actions. "
                    "Use enrollment lifecycle endpoints for enrollment status changes."
                )
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    return data, (student_status_update or None), None


def _extract_attendance_resolution(payload):
    data = dict(payload)
    attendance_resolution = (data.pop("attendance_resolution", "") or "").strip().lower()

    if attendance_resolution and attendance_resolution not in ALLOWED_RESOLUTIONS:
        return None, None, Response(
            {
                "detail": "Invalid attendance_resolution value.",
                "allowed_values": sorted(ALLOWED_RESOLUTIONS),
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    return data, (attendance_resolution or None), None


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
    permission_classes = [StudentDisciplineAccessPolicy]
    policy_action_map = {"get": "get", "post": "manage"}
    pagination_class = StudentDisciplinaryActionPagination

    def get(self, request):
        status_filter = (request.query_params.get("status") or "all").strip().lower()
        student_id = (request.query_params.get("student") or "").strip()
        search = (request.query_params.get("search") or "").strip()

        accessible_students = filter_students_for_permission_scope(
            Student.objects.all(),
            request,
            "students.discipline.view",
        )
        queryset = StudentDisciplinaryAction.objects.select_related("student").filter(
            student__in=accessible_students
        )
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
        payload, _student_status_update, error_response = _extract_status_updates(
            request.data
        )
        if error_response:
            return error_response

        payload, attendance_resolution, error_response = _extract_attendance_resolution(
            payload
        )
        if error_response:
            return error_response
        if attendance_resolution:
            return Response(
                {"detail": "attendance_resolution is only supported when ending a discipline action."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = StudentDisciplinaryActionSerializer(data=payload)
        serializer.is_valid(raise_exception=True)
        _require_discipline_student_access(
            serializer.validated_data["student"],
            request,
            "students.discipline.manage",
        )
        _ensure_currently_enrolled_for_discipline(serializer.validated_data["student"])
        _ensure_action_text_from_type(serializer)
        record = serializer.save(created_by=request.user, updated_by=request.user)

        updates = {}
        attendance_effect_updates = apply_attendance_effect_for_discipline(
            record,
            request.user,
        )

        response_data = StudentDisciplinaryActionSerializer(record).data
        response_data["status_updates_applied"] = updates
        response_data["attendance_effect_updates"] = attendance_effect_updates
        return Response(response_data, status=status.HTTP_201_CREATED)


class StudentDisciplinaryActionDetailView(APIView):
    permission_classes = [StudentDisciplineAccessPolicy]
    policy_action_map = {"get": "get", "put": "manage", "delete": "manage"}

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
        _require_discipline_student_access(
            record.student,
            request,
            "students.discipline.view",
        )
        serializer = StudentDisciplinaryActionSerializer(record)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def put(self, request, id):
        record = self.get_object(id)
        _require_discipline_student_access(
            record.student,
            request,
            "students.discipline.manage",
        )
        _ensure_currently_enrolled_for_discipline(record.student)
        payload, _student_status_update, error_response = _extract_status_updates(
            request.data
        )
        if error_response:
            return error_response

        payload, attendance_resolution, error_response = _extract_attendance_resolution(
            payload
        )
        if error_response:
            return error_response

        serializer = StudentDisciplinaryActionSerializer(
            record,
            data=payload,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)

        next_end_date = serializer.validated_data.get("end_date", record.end_date)
        is_early_end = next_end_date < record.end_date
        unresolved_impacts = 0
        attendance_resolution_applied = 0

        if record.action_type and record.action_type.attendance_effect_enabled and is_early_end:
            unresolved_impacts = count_unresolved_attendance_impacts_after(record, next_end_date)
            if unresolved_impacts > 0 and not attendance_resolution:
                return Response(
                    {
                        "detail": (
                            "Ending this discipline action now will affect attendance rows that were auto-updated "
                            "for future school days. Choose how to treat those attendance records."
                        ),
                        "code": "attendance_resolution_required",
                        "affected_attendance_rows": unresolved_impacts,
                        "allowed_resolutions": sorted(ALLOWED_RESOLUTIONS),
                    },
                    status=status.HTTP_409_CONFLICT,
                )

            if unresolved_impacts > 0 and attendance_resolution:
                attendance_resolution_applied = resolve_attendance_impacts_after(
                    record,
                    next_end_date,
                    resolution=attendance_resolution,
                    user=request.user,
                )

        updated_record = serializer.save(updated_by=request.user)

        updates = {}
        attendance_effect_updates = {
            "unresolved_impacts_detected": unresolved_impacts,
            "resolved_impacts": attendance_resolution_applied,
        }

        response_data = StudentDisciplinaryActionSerializer(updated_record).data
        response_data["status_updates_applied"] = updates
        response_data["attendance_effect_updates"] = attendance_effect_updates
        return Response(response_data, status=status.HTTP_200_OK)

    def delete(self, request, id):
        record = self.get_object(id)
        _require_discipline_student_access(
            record.student,
            request,
            "students.discipline.manage",
        )
        _ensure_currently_enrolled_for_discipline(record.student)
        record.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class StudentDisciplinaryActionByStudentListCreateView(APIView):
    permission_classes = [StudentDisciplineAccessPolicy]
    policy_action_map = {"get": "get", "post": "manage"}
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
        _require_discipline_student_access(
            student,
            request,
            "students.discipline.view",
        )
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
        _require_discipline_student_access(
            student,
            request,
            "students.discipline.manage",
        )
        _ensure_currently_enrolled_for_discipline(student)
        request_payload, _student_status_update, error_response = _extract_status_updates(
            request.data
        )
        if error_response:
            return error_response

        request_payload, attendance_resolution, error_response = _extract_attendance_resolution(
            request_payload
        )
        if error_response:
            return error_response
        if attendance_resolution:
            return Response(
                {"detail": "attendance_resolution is only supported when ending a discipline action."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        payload = {**request_payload, "student": str(student.id)}
        serializer = StudentDisciplinaryActionSerializer(data=payload)
        serializer.is_valid(raise_exception=True)
        _ensure_action_text_from_type(serializer)
        record = serializer.save(created_by=request.user, updated_by=request.user)

        updates = {}
        attendance_effect_updates = apply_attendance_effect_for_discipline(
            record,
            request.user,
        )

        response_data = StudentDisciplinaryActionSerializer(record).data
        response_data["status_updates_applied"] = updates
        response_data["attendance_effect_updates"] = attendance_effect_updates
        return Response(response_data, status=status.HTTP_201_CREATED)
