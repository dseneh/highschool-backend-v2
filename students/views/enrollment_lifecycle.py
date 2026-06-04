from datetime import datetime

from django.db import transaction
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView

from common.status import YearEndOutcome
from common.utils import get_object_by_uuid_or_fields
from students.access_policies import StudentAccessPolicy
from students.models import Student
from students.serializers import StudentDetailSerializer
from students.services.enrollment_lifecycle import (
    EnrollmentLifecycleError,
    close_enrollment_year,
    graduate_student,
    transfer_out_student,
)


class _StudentLifecycleMixin:
    permission_classes = [StudentAccessPolicy]

    def get_student(self, id):
        try:
            return get_object_by_uuid_or_fields(
                Student,
                id,
                fields=["id_number", "prev_id_number"],
            )
        except Student.DoesNotExist:
            raise NotFound("Student does not exist with this id")


def _parse_optional_date(value, field_name: str):
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError as exc:
        raise EnrollmentLifecycleError(
            f"{field_name} must be YYYY-MM-DD."
        ) from exc


class StudentCompleteYearView(_StudentLifecycleMixin, APIView):
    """POST /students/<id>/enrollments/current/complete-year/"""

    def post(self, request, id):
        student = self.get_student(id)
        outcome = (request.data.get("outcome") or "").lower().strip()
        if outcome not in YearEndOutcome.close_year_outcomes():
            return Response(
                {
                    "detail": "outcome is required and must be 'promoted' or 'repeated'."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            with transaction.atomic():
                close_enrollment_year(student, outcome)
        except EnrollmentLifecycleError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        serializer = StudentDetailSerializer(student, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)


class StudentGraduateView(_StudentLifecycleMixin, APIView):
    """POST /students/<id>/graduate/"""

    def post(self, request, id):
        student = self.get_student(id)
        try:
            graduation_date = _parse_optional_date(
                request.data.get("graduation_date"),
                "graduation_date",
            )
            with transaction.atomic():
                graduate_student(student, graduation_date=graduation_date)
        except EnrollmentLifecycleError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        serializer = StudentDetailSerializer(student, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)


class StudentTransferOutView(_StudentLifecycleMixin, APIView):
    """POST /students/<id>/transfer/"""

    def post(self, request, id):
        student = self.get_student(id)
        try:
            transfer_date = _parse_optional_date(
                request.data.get("transfer_date"),
                "transfer_date",
            )
            with transaction.atomic():
                transfer_out_student(
                    student,
                    transfer_date=transfer_date,
                    reason=request.data.get("reason"),
                )
        except EnrollmentLifecycleError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        serializer = StudentDetailSerializer(student, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)
