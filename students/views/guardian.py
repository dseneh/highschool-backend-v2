from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView
from ..access_policies import StudentAccessPolicy

from common.utils import (
    create_model_data,
    get_object_by_uuid_or_fields,
    update_model_fields,
    validate_required_fields,
)
from common.status import StudentStatus

from ..models import Student, StudentGuardian
from ..serializers import StudentGuardianSerializer


class StudentGuardianListView(APIView):
    permission_classes = [StudentAccessPolicy]
    def get_student(self, student_id):
        return get_object_by_uuid_or_fields(Student, student_id, "id")

    def get(self, request, student_id):
        student = self.get_student(student_id)
        guardians = student.guardians.all()
        serializer = StudentGuardianSerializer(guardians, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request, student_id):
        student = self.get_student(student_id)

        # Guard: reject data entry for withdrawn / inactive students
        if student.status in (StudentStatus.WITHDRAWN, StudentStatus.GRADUATED, StudentStatus.TRANSFERRED, StudentStatus.DELETED):
            return Response(
                {"detail": f"Cannot add guardians for a student with status '{student.status}'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        required_fields = [
            "first_name",
            "last_name",
        ]
        validate_required_fields(request, required_fields)

        data = {
            "student": student,
            "first_name": request.data.get("first_name"),
            "last_name": request.data.get("last_name"),
            "relationship": request.data.get("relationship", "other"),
            "phone_number": request.data.get("phone_number"),
            "email": request.data.get("email"),
            "address": request.data.get("address"),
            "occupation": request.data.get("occupation"),
            "workplace": request.data.get("workplace"),
            "is_primary": request.data.get("is_primary", False),
            "photo": request.data.get("photo"),
            "notes": request.data.get("notes"),
            "updated_by": request.user,
            "created_by": request.user,
        }

        return create_model_data(
            request, data, StudentGuardian, StudentGuardianSerializer
        )


class StudentGuardianDetailView(APIView):
    permission_classes = [StudentAccessPolicy]
    def get_object(self, id):
        return get_object_by_uuid_or_fields(StudentGuardian, id, "id")

    def get(self, request, id):
        guardian = self.get_object(id)
        serializer = StudentGuardianSerializer(guardian)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def put(self, request, id):
        guardian = self.get_object(id)

        allowed_fields = [
            "first_name",
            "last_name",
            "relationship",
            "phone_number",
            "email",
            "address",
            "occupation",
            "workplace",
            "is_primary",
            "photo",
            "notes",
        ]

        serializer = update_model_fields(
            request, guardian, allowed_fields, StudentGuardianSerializer
        )
        return serializer

    def delete(self, request, id):
        guardian = self.get_object(id)
        guardian.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
