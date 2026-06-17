"""Historical / transferred transcript grade API views."""

from django.db import transaction
from django.db.models import Count, Max, Prefetch, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from academics.models import AcademicYear, GradeLevel, MarkingPeriod, Subject
from common.serializers import PhotoURLMixin
from common.utils import get_object_by_uuid_or_fields, serializer_errors_to_detail
from students.access_policies import HistoricalGradeAccessPolicy
from users.access_policies.access import BaseSchoolAccessPolicy

from ..models import Student
from ..models.enrollment import Enrollment
from ..models.historical_grade import HistoricalGradeRecord
from ..serializers.historical_grade import (
    HistoricalGradeRecordSerializer,
    HistoricalGradeRecordWriteSerializer,
    HistoricalGradeStudentSummarySerializer,
)


def _get_student(student_id: str) -> Student:
    try:
        return get_object_by_uuid_or_fields(
            Student,
            student_id,
            fields=["id_number", "prev_id_number"],
        )
    except Student.DoesNotExist as exc:
        raise NotFound("Student does not exist with this id") from exc


def _get_record(student_id: str, record_id: str) -> HistoricalGradeRecord:
    student = _get_student(student_id)
    return get_object_or_404(
        HistoricalGradeRecord.objects.select_related(
            "grade_level",
            "subject",
            "marking_period",
            "academic_year",
        ),
        pk=record_id,
        student=student,
    )


def _resolve_fk(model, value):
    if not value:
        return None
    if isinstance(value, dict):
        value = value.get("id") or value.get("pk")
    if not value:
        return None
    obj = model.objects.filter(id=value).first()
    if obj:
        return obj
    if isinstance(value, str) and hasattr(model, "name"):
        return model.objects.filter(name__iexact=value).first()
    return None


def _validation_error_response(serializer):
    return Response(
        {"detail": serializer_errors_to_detail(serializer.errors)},
        status=status.HTTP_400_BAD_REQUEST,
    )


def _require_admin(request, view) -> Response | None:
    policy = BaseSchoolAccessPolicy()
    if policy.is_role_in(request, view, "post", "admin"):
        return None
    return Response(
        {"detail": "Only administrators can unverify historical grades."},
        status=status.HTTP_403_FORBIDDEN,
    )


def _resolve_record_fks(data: dict) -> dict:
    resolved = dict(data)
    if "grade_level" in resolved:
        gl = _resolve_fk(GradeLevel, resolved.pop("grade_level"))
        if not gl:
            raise ValueError("Grade level does not exist.")
        resolved["grade_level"] = gl
    if "subject" in resolved:
        sub = _resolve_fk(Subject, resolved.pop("subject"))
        if not sub:
            raise ValueError("Subject does not exist.")
        resolved["subject"] = sub
    if "marking_period" in resolved:
        mp = _resolve_fk(MarkingPeriod, resolved.pop("marking_period"))
        resolved["marking_period"] = mp
    if "academic_year" in resolved:
        ay = _resolve_fk(AcademicYear, resolved.pop("academic_year"))
        resolved["academic_year"] = ay
    return resolved


def _student_verification_status(verified_count: int, draft_count: int) -> str:
    if draft_count == 0:
        return "all_verified"
    if verified_count == 0:
        return "draft_only"
    return "has_draft"


def _student_grade_context(student: Student):
    current_enrollment = None
    prefetched = getattr(student, "current_enrollments", None)
    if prefetched:
        current_enrollment = prefetched[0]

    grade_level = None
    section = None
    if current_enrollment:
        if current_enrollment.grade_level_id:
            grade_level = {
                "id": str(current_enrollment.grade_level_id),
                "name": current_enrollment.grade_level.name,
            }
        if current_enrollment.section_id:
            section = {
                "id": str(current_enrollment.section_id),
                "name": current_enrollment.section.name,
            }
    elif student.grade_level_id:
        grade_level = {
            "id": str(student.grade_level_id),
            "name": student.grade_level.name,
        }
    return grade_level, section


def _student_photo_url(student: Student, request) -> str | None:
    if not student.photo:
        return None
    photo_path = student.photo.url if hasattr(student.photo, "url") else str(student.photo)
    return PhotoURLMixin().build_photo_url(photo_path, request)


class HistoricalGradeStudentSummaryListView(APIView):
    permission_classes = [HistoricalGradeAccessPolicy]

    def get(self, request):
        search = (request.query_params.get("search") or "").strip()
        verification = (request.query_params.get("verification") or "").strip()
        grade_level_id = (request.query_params.get("grade_level_id") or "").strip()

        student_ids = HistoricalGradeRecord.objects.values_list(
            "student_id", flat=True
        ).distinct()

        students = (
            Student.objects.filter(id__in=student_ids)
            .select_related("grade_level")
            .prefetch_related(
                Prefetch(
                    "enrollments",
                    queryset=Enrollment.objects.filter(
                        academic_year__current=True
                    ).select_related("grade_level", "section", "academic_year"),
                    to_attr="current_enrollments",
                )
            )
            .order_by("last_name", "first_name")
        )

        if search:
            students = students.filter(
                Q(id_number__icontains=search)
                | Q(prev_id_number__icontains=search)
                | Q(first_name__icontains=search)
                | Q(last_name__icontains=search)
            )

        if grade_level_id:
            students = students.filter(
                Q(grade_level_id=grade_level_id)
                | Q(
                    enrollments__academic_year__current=True,
                    enrollments__grade_level_id=grade_level_id,
                )
            ).distinct()

        student_id_list = list(students.values_list("id", flat=True))
        if not student_id_list:
            return Response([])

        stats_rows = (
            HistoricalGradeRecord.objects.filter(student_id__in=student_id_list)
            .values("student_id")
            .annotate(
                record_count=Count("id"),
                verified_count=Count(
                    "id",
                    filter=Q(status=HistoricalGradeRecord.Status.VERIFIED),
                ),
                draft_count=Count(
                    "id",
                    filter=Q(status=HistoricalGradeRecord.Status.DRAFT),
                ),
                institution_count=Count("institution_name", distinct=True),
                last_updated=Max("updated_at"),
            )
        )
        stats_by_student = {row["student_id"]: row for row in stats_rows}

        institution_rows = (
            HistoricalGradeRecord.objects.filter(student_id__in=student_id_list)
            .values("student_id", "institution_name")
            .distinct()
            .order_by("institution_name")
        )
        institutions_by_student: dict = {}
        for row in institution_rows:
            institutions_by_student.setdefault(row["student_id"], []).append(
                row["institution_name"]
            )

        summaries = []
        for student in students:
            stat = stats_by_student.get(student.id)
            if not stat:
                continue

            verified_count = stat["verified_count"]
            draft_count = stat["draft_count"]
            verification_status = _student_verification_status(
                verified_count, draft_count
            )

            if verification == "all_verified" and draft_count > 0:
                continue
            if verification == "has_draft" and draft_count == 0:
                continue
            if verification == "draft_only" and verified_count > 0:
                continue

            grade_level, section = _student_grade_context(student)
            summaries.append(
                {
                    "id": student.id,
                    "id_number": student.id_number,
                    "first_name": student.first_name,
                    "last_name": student.last_name,
                    "full_name": student.get_full_name(),
                    "photo": _student_photo_url(student, request),
                    "status": student.status,
                    "grade_level": grade_level,
                    "section": section,
                    "record_count": stat["record_count"],
                    "verified_count": verified_count,
                    "draft_count": draft_count,
                    "institution_count": stat["institution_count"],
                    "institutions": institutions_by_student.get(student.id, []),
                    "last_updated": stat["last_updated"],
                    "verification_status": verification_status,
                }
            )

        summaries.sort(
            key=lambda row: row["last_updated"] or timezone.now(),
            reverse=True,
        )
        serializer = HistoricalGradeStudentSummarySerializer(summaries, many=True)
        return Response(serializer.data)


class HistoricalGradeRecordListView(APIView):
    permission_classes = [HistoricalGradeAccessPolicy]

    def get(self, request, student_id):
        student = _get_student(student_id)
        records = (
            HistoricalGradeRecord.objects.filter(student=student)
            .select_related("grade_level", "subject", "marking_period", "academic_year")
            .order_by("-created_at")
        )

        academic_year_id = request.query_params.get("academic_year_id")
        if academic_year_id:
            records = records.filter(academic_year_id=academic_year_id)

        serializer = HistoricalGradeRecordSerializer(records, many=True)
        return Response(serializer.data)

    @transaction.atomic
    def post(self, request, student_id):
        student = _get_student(student_id)
        payload = request.data
        items = payload if isinstance(payload, list) else [payload]
        created = []

        for item in items:
            try:
                data = _resolve_record_fks(dict(item))
            except ValueError as exc:
                return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

            serializer = HistoricalGradeRecordWriteSerializer(
                data=data,
                context={"student": student, "request": request},
            )
            if not serializer.is_valid():
                return _validation_error_response(serializer)

            record = serializer.save()
            if request.user and request.user.is_authenticated and not record.created_by_id:
                record.created_by = request.user
                record.save(update_fields=["created_by"])
            created.append(record)

        out = HistoricalGradeRecordSerializer(created, many=True)
        return Response(
            out.data[0] if len(out.data) == 1 else out.data,
            status=status.HTTP_201_CREATED,
        )


class HistoricalGradeRecordDetailView(APIView):
    permission_classes = [HistoricalGradeAccessPolicy]

    def get(self, request, student_id, record_id):
        record = _get_record(student_id, record_id)
        return Response(HistoricalGradeRecordSerializer(record).data)

    def patch(self, request, student_id, record_id):
        record = _get_record(student_id, record_id)
        if record.status == HistoricalGradeRecord.Status.VERIFIED:
            return Response(
                {"detail": "Verified grades cannot be edited. Unverify first."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            data = _resolve_record_fks(dict(request.data))
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        serializer = HistoricalGradeRecordWriteSerializer(
            record,
            data=data,
            partial=True,
            context={"student": record.student, "request": request},
        )
        if not serializer.is_valid():
            return _validation_error_response(serializer)
        record = serializer.save()
        if request.user and request.user.is_authenticated:
            record.updated_by = request.user
            record.save(update_fields=["updated_by", "updated_at"])
        return Response(HistoricalGradeRecordSerializer(record).data)

    def delete(self, request, student_id, record_id):
        record = _get_record(student_id, record_id)
        if record.status == HistoricalGradeRecord.Status.VERIFIED:
            return Response(
                {"detail": "Verified grades cannot be deleted. Unverify first."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        record.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class HistoricalGradeRecordVerifyView(APIView):
    permission_classes = [HistoricalGradeAccessPolicy]

    def post(self, request, student_id, record_id):
        record = _get_record(student_id, record_id)
        if record.final_percentage is None:
            return Response(
                {"detail": "Enter a year-end final grade before verifying."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        record.status = HistoricalGradeRecord.Status.VERIFIED
        record.verified_at = timezone.now()
        record.verified_by = request.user if request.user.is_authenticated else None
        record.updated_by = request.user if request.user.is_authenticated else None
        record.save(
            update_fields=["status", "verified_at", "verified_by", "updated_by", "updated_at"]
        )
        return Response(HistoricalGradeRecordSerializer(record).data)


class HistoricalGradeRecordUnverifyView(APIView):
    permission_classes = [HistoricalGradeAccessPolicy]

    def post(self, request, student_id, record_id):
        denied = _require_admin(request, self)
        if denied:
            return denied
        record = _get_record(student_id, record_id)
        if record.status != HistoricalGradeRecord.Status.VERIFIED:
            return Response(
                {"detail": "Only verified grades can be unverified."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        record.status = HistoricalGradeRecord.Status.DRAFT
        record.verified_at = None
        record.verified_by = None
        record.updated_by = request.user if request.user.is_authenticated else None
        record.save(
            update_fields=[
                "status",
                "verified_at",
                "verified_by",
                "updated_by",
                "updated_at",
            ]
        )
        return Response(HistoricalGradeRecordSerializer(record).data)


class StudentGradeHistoryView(APIView):
    permission_classes = [HistoricalGradeAccessPolicy]

    def get(self, request, student_id):
        student = _get_student(student_id)
        from students.services.student_grade_history import StudentGradeHistoryService

        return Response(StudentGradeHistoryService.serialize_for_student(student))
