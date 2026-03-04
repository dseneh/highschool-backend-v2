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

from ..models import Student, StudentContact
from ..serializers import StudentContactSerializer


class StudentContactListView(APIView):
    permission_classes = [StudentAccessPolicy]
    def get_student(self, student_id):
        return get_object_by_uuid_or_fields(Student, student_id, "id")

    def get(self, request, student_id):
        student = self.get_student(student_id)
        contacts = student.contacts.all()
        serializer = StudentContactSerializer(contacts, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request, student_id):
        student = self.get_student(student_id)

        # Guard: reject data entry for withdrawn / inactive students
        if student.status in (StudentStatus.WITHDRAWN, StudentStatus.GRADUATED, StudentStatus.TRANSFERRED, StudentStatus.DELETED):
            return Response(
                {"detail": f"Cannot add contacts for a student with status '{student.status}'."},
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
            "is_emergency": request.data.get("is_emergency", False),
            "is_primary": request.data.get("is_primary", False),
            "photo": request.data.get("photo"),
            "notes": request.data.get("notes"),
            "updated_by": request.user,
            "created_by": request.user,
        }

        return create_model_data(
            request, data, StudentContact, StudentContactSerializer
        )


class StudentContactDetailView(APIView):
    permission_classes = [StudentAccessPolicy]
    def get_object(self, id):
        return get_object_by_uuid_or_fields(StudentContact, id, "id")

    def get(self, request, id):
        contact = self.get_object(id)
        serializer = StudentContactSerializer(contact)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def put(self, request, id):
        contact = self.get_object(id)

        allowed_fields = [
            "first_name",
            "last_name",
            "relationship",
            "phone_number",
            "email",
            "address",
            "is_emergency",
            "is_primary",
            "photo",
            "notes",
        ]

        serializer = update_model_fields(
            request, contact, allowed_fields, StudentContactSerializer
        )
        return serializer

    def delete(self, request, id):
        contact = self.get_object(id)
        contact.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
