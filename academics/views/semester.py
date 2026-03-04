from django.db.models import Q
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView
from ..access_policies import AcademicsAccessPolicy

from common.utils import update_model_fields
from common.cache_service import DataCache

from ..models import AcademicYear, Semester
from ..serializers import SemesterSerializer

# Business logic imports
from business.core.services import semester_service
from business.core.adapters import semester_adapter

class SemesterListView(APIView):
    permission_classes = [AcademicsAccessPolicy]
    # permission_classes = [AllowAny]
    def get_academic_year_object(self, id):
        try:
            f = Q(id=id) | Q(name=id)
            return AcademicYear.objects.get(f)
        except AcademicYear.DoesNotExist:
            raise NotFound("Academic year does not exist with this id")

    def get(self, request):        
        # Use cached semesters for better performance
        force_refresh = request.query_params.get('force_refresh', 'false').lower() == 'true'
        academic_year_id = request.query_params.get('academic_year_id')
        semesters = DataCache.get_semesters(academic_year_id, force_refresh)
        
        return Response(semesters, status=status.HTTP_200_OK)

    def post(self, request, school_id):
        req_data: dict = request.data

        # Validate using business logic
        validation_result = semester_service.validate_semester_creation(
            name=req_data.get("name"),
            start_date=req_data.get("start_date"),
            end_date=req_data.get("end_date")
        )
        
        if not validation_result["valid"]:
            return Response({"detail": validation_result["error"]}, status=400)
        
        if Semester.objects.filter(name__iexact=validation_result["data"]["name"]).exists():
            return Response({"detail": "Semester already exists"}, status=400)

        try:
            semester = semester_adapter.create_semester_in_db(
                data=validation_result["data"],
                user=request.user
            )
            serializer = SemesterSerializer(semester, context={"request": request})
            return Response(serializer.data, status=201)
        except Exception as e:
            return Response({"detail": str(e)}, status=400)

class SemesterDetailView(APIView):
    permission_classes = [AcademicsAccessPolicy]
    # permission_classes = [IsAuthenticatedOrReadOnly, IsAdminOrSystemAdmin]
    def get_object(self, id):
        try:
            f = Q(id=id) | Q(name=id)
            return Semester.objects.get(f)
        except Semester.DoesNotExist:
            raise NotFound("Semester does not exist with this id")

    def get(self, request, id):
        semester = self.get_object(id)
        serializer = SemesterSerializer(semester, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    def put(self, request, id):
        semester = self.get_object(id)

        allowed_fields = [
            "name",
            "start_date",
            "end_date",
            "current",
            "active",
        ]

        serializer = update_model_fields(
            request, semester, allowed_fields, SemesterSerializer
        )
        return Response(serializer.data, status=status.HTTP_200_OK)

    def delete(self, request, id):
        semester = self.get_object(id)

        # Check if there are any marking periods associated with this semester
        if semester.marking_periods.exists():
            return Response(
                {
                    "detail": "Cannot delete semester with associated marking periods, please delete those marking periods first."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        semester.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
