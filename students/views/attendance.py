from datetime import datetime

from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView
from ..access_policies import StudentAccessPolicy

from common.status import AttendanceStatus
from common.status import StudentStatus
from common.utils import (
    create_model_data,
    update_model_fields,
    validate_required_fields,
)
from academics.models import MarkingPeriod

from ..models import Attendance, Enrollment
from ..serializers import AttendanceSerializer

class AttendanceListView(APIView):
    permission_classes = [StudentAccessPolicy]
    # permission_classes = [AllowAny]
    def get_object(self, id):
        try:
            return Enrollment.objects.get(id=id)
        except Enrollment.DoesNotExist:
            raise NotFound("Enrollment does not exist with this id")

    def get(self, request, enrollment_id):
        enrollment = self.get_object(enrollment_id)

        # 🔥 MEMORY FIX: Optimize attendance loading
        attendence = enrollment.attendence.select_related("enrollment__student")
        serializer = AttendanceSerializer(attendence, many=True)

        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request, enrollment_id):
        enrollment = self.get_object(enrollment_id)

        # Guard: reject attendance for withdrawn / inactive students
        student = enrollment.student
        if student.status in (StudentStatus.WITHDRAWN, StudentStatus.GRADUATED, StudentStatus.TRANSFERRED, StudentStatus.DELETED):
            return Response(
                {"detail": f"Cannot record attendance for a student with status '{student.status}'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        req: dict = request.data

        required_fields = [
            "marking_period",
            "date",
            "status",
        ]

        validate_required_fields(request, required_fields)

        if req.get("status") not in AttendanceStatus.all():
            return Response({"detail": "Invalid attendance status"}, 400)

        marking_period = MarkingPeriod.objects.filter(
            id=req.get("marking_period")
        ).first()

        if not marking_period:
            return Response(
                {"detail": "Marking period does not exist with this id"}, 400
            )

        data = {
            "marking_period": marking_period,
            "status": req.get("status", AttendanceStatus.PRESENT),
            "date": req.get("date", datetime.now().today()),
            "notes": req.get("notes"),
            "updated_by": request.user,
            "created_by": request.user,
        }

        return create_model_data(
            request, data, enrollment.attendence, AttendanceSerializer
        )

class AttendanceDetailView(APIView):
    permission_classes = [StudentAccessPolicy]
    # permission_classes = [IsAuthenticatedOrReadOnly, IsAdminOrSystemAdmin]
    def get_object(self, id):
        try:
            return Attendance.objects.get(id=id)
        except Attendance.DoesNotExist:
            raise NotFound("Attendance does not exist with this id")

    def get(self, request, id):
        attendence = self.get_object(id)
        serializer = AttendanceSerializer(attendence)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def put(self, request, id):
        attendence = self.get_object(id)

        allowed_fields = [
            "date",
            "status",
        ]

        validate_required_fields(request, allowed_fields)

        if request.data.get("status") not in AttendanceStatus.all():
            return Response({"detail": "Invalid attendance status"}, 400)

        serializer = update_model_fields(
            request, attendence, allowed_fields, AttendanceSerializer
        )
        return Response(serializer.data, status=status.HTTP_200_OK)

    def delete(self, request, id):
        attendence = self.get_object(id)
        attendence.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
