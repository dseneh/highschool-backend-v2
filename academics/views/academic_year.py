
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from ..access_policies import AcademicsAccessPolicy
from common.cache_service import DataCache

from ..models import AcademicYear
from ..serializers import AcademicYearSerializer

# Business logic imports
from business.core.services import academic_year_service
from business.core.adapters import academic_year_adapter

class AcademicYearListView(APIView):
    permission_classes = [AcademicsAccessPolicy]

    def get(self, request):        
        # Use cached data for better performance
        force_refresh = request.query_params.get('force_refresh', 'false').lower() == 'true'
        academic_years = DataCache.get_academic_years(force_refresh)
        
        # Filter for active years only
        active_years = [year for year in academic_years if year.get('status') == 'active']
        
        return Response(active_years)

    def post(self, request):
        req_data: dict = request.data

        # Validate using business logic
        validation_result = academic_year_service.validate_academic_year_creation(
            start_date=req_data.get("start_date"),
            end_date=req_data.get("end_date"),
            name=req_data.get("name")
        )
        
        if not validation_result["valid"]:
            return Response({"detail": validation_result["error"]}, status=400)
        
        # Check date overlap using business logic
        existing_years = academic_year_adapter.get_existing_academic_years()
        
        overlap_result = academic_year_service.check_academic_year_overlap(
            start_date=validation_result["data"]["start_date"],
            end_date=validation_result["data"]["end_date"],
            existing_years=existing_years
        )
        
        if overlap_result["has_overlap"]:
            return Response({"detail": overlap_result["error"]}, status=400)
        
        # Generate name if not provided
        if not validation_result["data"].get("name"):
            validation_result["data"]["name"] = academic_year_service.generate_academic_year_name(
                validation_result["data"]["start_date"],
                validation_result["data"]["end_date"]
            )
        
        # Add current flag
        validation_result["data"]["current"] = req_data.get("current", False)

        try:
            academic_year = academic_year_adapter.create_academic_year_in_db(
                data=validation_result["data"],
                user=request.user
            )
            serializer = AcademicYearSerializer(
                academic_year, context={"request": request}
            )
            return Response(serializer.data, status=201)
        except Exception as e:
            return Response({"detail": str(e)}, status=400)

class AcademicYearDetailView(APIView):
    permission_classes = [AcademicsAccessPolicy]
    def get_object(self, id):
        # try:
        f = Q(id=id) | Q(name=id)
        # return AcademicYear.objects.get(f)
        return get_object_or_404(AcademicYear, f)
        # except AcademicYear.DoesNotExist:
        #     raise NotFound("Academic year does not exist with this id")

    def get(self, request, id):
        academic_year = self.get_object(id)
        include_stats = request.query_params.get('include_stats', 'false').lower() == 'true'
        serializer = AcademicYearSerializer(
            academic_year,
            context={"request": request, "include_stats": include_stats}
        )
        return Response(serializer.data, status=status.HTTP_200_OK)

    def put(self, request, id):
        academic_year = self.get_object(id)

        update_data = {}
        
        # Handle name update
        name = request.data.get("name")
        if name:
            if AcademicYear.objects.filter(name__iexact=name).exists():
                return Response(
                    {"detail": f"Academic year named '{name}' already exists"},
                    status=400,
                )
            update_data["name"] = name
        
        # Handle current flag update
        current = request.data.get("current", False)
        if current and not academic_year.current:
            update_data["current"] = True

        # Handle date updates
        s = str(academic_year.start_date)
        e = str(academic_year.end_date)
        start_date = request.data.get("start_date", s)
        end_date = request.data.get("end_date", e)

        if start_date != s or end_date != e:
            # Validate using business logic
            validation_result = academic_year_service.validate_academic_year_creation(
                start_date=start_date,
                end_date=end_date,
                name=name
            )
            
            if not validation_result["valid"]:
                return Response({"detail": validation_result["error"]}, status=400)
            
            # Check overlap using business logic
            existing_years = academic_year_adapter.get_existing_academic_years(
                exclude_id=str(academic_year.id)
            )
            
            overlap_result = academic_year_service.check_academic_year_overlap(
                start_date=validation_result["data"]["start_date"],
                end_date=validation_result["data"]["end_date"],
                existing_years=existing_years
            )
            
            if overlap_result["has_overlap"]:
                return Response({"detail": overlap_result["error"]}, status=400)
            
            update_data["start_date"] = validation_result["data"]["start_date"]
            update_data["end_date"] = validation_result["data"]["end_date"]
        
        # Handle status update
        status_value = request.data.get("status")
        if status_value:
            update_data["status"] = status_value

        # Update in database
        updated_year = academic_year_adapter.update_academic_year_in_db(
            year_id=str(academic_year.id),
            data=update_data,
            user=request.user
        )
        
        if not updated_year:
            return Response({"detail": "Academic year not found"}, status=404)
        
        serializer = AcademicYearSerializer(updated_year, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    def delete(self, request, id):
        academic_year = self.get_object(id)
        if academic_year.current:
            return Response(
                {"detail": "Cannot delete current academic year."}, status=400
            )
        academic_year.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

# create an endpoint to get the current academic year for an institution
class CurrentAcademicYearView(APIView):
    permission_classes = [AcademicsAccessPolicy]

    def get(self, request):
        from academics.serializers import AcademicYearSerializer
        from academics.models import AcademicYear

        # Check if stats are requested
        include_stats = request.query_params.get('include_stats', 'false').lower() == 'true'
        
        # Get the current academic year object
        academic_year = AcademicYear.objects.filter(current=True).first()
        
        if not academic_year:
            return Response(
                {"detail": "No current academic year found"},
                status=status.HTTP_404_NOT_FOUND,
            )
        
        # Serialize with appropriate context
        serializer = AcademicYearSerializer(
            academic_year,
            context={"request": request, "include_stats": include_stats}
        )
        
        return Response(serializer.data, status=status.HTTP_200_OK)
