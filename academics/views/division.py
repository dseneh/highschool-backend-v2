from django.db.models import Q
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView
from ..access_policies import AcademicsAccessPolicy

from common.utils import update_model_fields
from common.cache_service import DataCache

from ..models import Division
from ..serializers import DivisionSerializer

# Business logic imports
from business.core.services import division_service
from business.core.adapters import division_adapter

class DivisionListView(APIView):
    permission_classes = [AcademicsAccessPolicy]
    # permission_classes = [AllowAny]

    def get(self, request):
        
        # Use cached divisions for better performance
        force_refresh = request.query_params.get('force_refresh', 'false').lower() == 'true'
        divisions = DataCache.get_divisions(force_refresh)
        
        return Response(divisions, status=status.HTTP_200_OK)

    def post(self, request):
        req_data: dict = request.data

        # Validate using business logic
        validation_result = division_service.validate_division_creation(
            name=req_data.get("name"),
            description=req_data.get("description")
        )
        
        if not validation_result["valid"]:
            return Response({"detail": validation_result["error"]}, status=400)
        
        # Check for duplicates
        if Division.objects.filter(name__iexact=validation_result["data"]["name"]).exists():
            return Response({"detail": "Division already exists"}, status=400)

        try:
            division = division_adapter.create_division_in_db(
                data=validation_result["data"],
                user=request.user
            )
            serializer = DivisionSerializer(division)
            return Response(serializer.data, status=201)
        except Exception as e:
            return Response({"detail": str(e)}, status=400)

class DivisionDetailView(APIView):
    permission_classes = [AcademicsAccessPolicy]
    # permission_classes = [IsAuthenticatedOrReadOnly, IsAdminOrSystemAdmin]
    def get_object(self, id):
        try:
            return Division.objects.filter(id=id).first()
        except Division.DoesNotExist:
            raise NotFound("Division does not exist with this id")

    def get(self, request, id):
        division = self.get_object(id)
        serializer = DivisionSerializer(division)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def put(self, request, id):
        division = self.get_object(id)

        allowed_fields = [
            "name",
            "description",
            "active",
        ]

        name = request.data.get("name")
        if name:
            if Division.objects.filter(name__iexact=name).exists():
                return Response(
                    {"detail": f"Division named '{name}' already exists"}, status=400
                )

        serializer = update_model_fields(
            request, division, allowed_fields, DivisionSerializer
        )
        return Response(serializer.data, status=status.HTTP_200_OK)

    def delete(self, request, id):
        division = self.get_object(id)
        
        # Check if division has grade levels using business logic
        if division_adapter.check_division_has_grade_levels(str(division.id)):
            return Response(
                {"detail": "Cannot delete division with associated grade levels."}, status=400
            )
        
        # Delete using adapter
        if division_adapter.delete_division_from_db(str(division.id)):
            return Response(status=status.HTTP_204_NO_CONTENT)
        else:
            return Response({"detail": "Division not found"}, status=404)
