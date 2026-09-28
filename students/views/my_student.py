"""Minimal identity lookup for the signed-in user's own student record."""
from django.db import connection
from django.db.models import Q
from django_tenants.utils import get_public_schema_name
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from students.models import Student


class MyStudentView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        identifier = getattr(request.user, "id_number", None)
        if not identifier or connection.schema_name == get_public_schema_name():
            return Response(None)
        # Guardian links identify children, not the caller's student identity.
        student = Student.objects.filter(
            Q(user_account_id_number=identifier)
            | ((Q(user_account_id_number="") | Q(user_account_id_number__isnull=True))
               & Q(id_number=identifier))
        ).only("id", "id_number").first()
        return Response({"id": str(student.pk), "id_number": student.id_number} if student else None)
