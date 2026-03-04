from django.db.models import Count, Sum, Q, Avg
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from ..access_policies import StudentAccessPolicy

from academics.models import AcademicYear
from common.utils import get_object_by_uuid_or_fields
from students.models import Student, StudentConcession
from students.serializers.concession import StudentConcessionSerializer


class StudentConcessionListCreateView(APIView):
    permission_classes = [StudentAccessPolicy]
    """List and create concessions for a student."""

    def _get_student(self, student_id):
        return get_object_by_uuid_or_fields(
            Student,
            student_id,
            fields=["id_number", "prev_id_number"],
        )

    def get(self, request, academic_year_id='current'):
        student_id = request.query_params.get("student_id")
        if student_id:
            try:
                student = self._get_student(student_id)
            except Student.DoesNotExist:
                return Response({"detail": "Student not found"}, status=status.HTTP_404_NOT_FOUND)

        # academic_year_id = request.query_params.get("academic_year_id")
        active = request.query_params.get("active")

        queryset = StudentConcession.objects.select_related(
            "student", "academic_year"
        )
        if student_id:
            queryset = queryset.filter(student_id=student.id)

        if not academic_year_id or academic_year_id == "current":
            queryset = queryset.filter(academic_year__current=True)
        elif academic_year_id:
            queryset = queryset.filter(academic_year_id=academic_year_id)

        if active is not None:
            queryset = queryset.filter(active=str(active).lower() in ["true", "1", "yes"])

        serializer = StudentConcessionSerializer(queryset.order_by("-created_at"), many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request, academic_year_id='current'):
        student_id = request.data.get("student")
        print(request.data)
        if not student_id:
            return Response({"detail": "student_id is required"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            student = self._get_student(student_id)
        except Student.DoesNotExist:
            return Response({"detail": "Student not found"}, status=status.HTTP_404_NOT_FOUND)

        payload = request.data.copy()
        academic_year_id = payload.get("academic_year") or payload.get("academic_year_id")

        if academic_year_id == "current" or not academic_year_id:
            academic_year = AcademicYear.objects.filter(active=True).first()
        else:
            academic_year = AcademicYear.objects.filter(id=academic_year_id).first()

        if not academic_year:
            return Response(
                {"detail": "Academic year not found"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        payload["academic_year"] = str(academic_year.id)

        serializer = StudentConcessionSerializer(data=payload)
        serializer.is_valid(raise_exception=True)
        serializer.save(student=student, created_by=request.user, updated_by=request.user)

        return Response(serializer.data, status=status.HTTP_201_CREATED)


class StudentConcessionDetailView(APIView):
    permission_classes = [StudentAccessPolicy]
    """Retrieve, update, or soft-disable a concession."""

    def _get_concession(self, id):
        return StudentConcession.objects.select_related("student", "academic_year").filter(id=id).first()

    def get(self, request, id):
        concession = self._get_concession(id)
        if not concession:
            return Response({"detail": "Concession not found"}, status=status.HTTP_404_NOT_FOUND)

        serializer = StudentConcessionSerializer(concession)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def put(self, request, id):
        concession = self._get_concession(id)
        if not concession:
            return Response({"detail": "Concession not found"}, status=status.HTTP_404_NOT_FOUND)

        serializer = StudentConcessionSerializer(concession, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save(updated_by=request.user)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def delete(self, request, id):
        concession = self._get_concession(id)
        if not concession:
            return Response({"detail": "Concession not found"}, status=status.HTTP_404_NOT_FOUND)

        # concession.active = False
        # concession.updated_by = request.user
        concession.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class StudentConcessionStatsView(APIView):
    permission_classes = [StudentAccessPolicy]
    """Get concession statistics."""

    def get(self, request, academic_year_id='current'):
        # Filter by academic year
        queryset = StudentConcession.objects.select_related("student", "academic_year")
        
        if not academic_year_id or academic_year_id == "current":
            queryset = queryset.filter(academic_year__current=True)
        elif academic_year_id:
            queryset = queryset.filter(academic_year_id=academic_year_id)

        # Total concessions
        total_concessions = queryset.count()

        # Total students with concessions (distinct)
        total_students = queryset.values('student').distinct().count()

        # Concessions by type
        by_type = queryset.values('concession_type').annotate(
            count=Count('id')
        ).order_by('-count')

        # Concessions by target
        by_target = queryset.values('target').annotate(
            count=Count('id')
        ).order_by('-count')

        # Total amount of concessions (sum of all calculated amounts)
        total_amount = queryset.aggregate(total=Sum('amount'))['total'] or 0

        # Average concession amount
        avg_amount = queryset.aggregate(avg=Avg('amount'))['avg'] or 0

        stats = {
            "total_concessions": total_concessions,
            "total_students": total_students,
            "total_amount": float(total_amount),
            "average_amount": float(avg_amount),
            "by_type": list(by_type),
            "by_target": list(by_target),
        }

        return Response(stats, status=status.HTTP_200_OK)
