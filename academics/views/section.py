from django.core.cache import cache as django_cache
from django.db.models import Q
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView
from ..access_policies import AcademicsAccessPolicy
import logging

from common.utils import update_model_fields, get_tenant_from_request
from common.cache_service import DataCache

from ..models import GradeLevel, Section
from ..serializers import SectionSerializer

# Business logic imports
from business.core.services import section_service
from business.core.adapters import section_adapter

logger = logging.getLogger(__name__)

class SectionListView(APIView):
    permission_classes = [AcademicsAccessPolicy]
    # permission_classes = [AllowAny]
    def get_grade_level_object(self, id):
        try:
            f = Q(id=id) | Q(name=id)
            return GradeLevel.objects.get(f)
        except GradeLevel.DoesNotExist:
            raise NotFound("Grade level does not exist with this id")

    def get(self, request, grade_level_id):
        grade_level = self.get_grade_level_object(grade_level_id)
        
        # Use cached sections for better performance
        force_refresh = request.query_params.get('force_refresh', 'false').lower() == 'true'
        all_sections = DataCache.get_sections(force_refresh=force_refresh)
        
        # Filter sections by grade level ID (comparing strings since IDs are strings in cache)
        grade_level_sections = [
            s for s in all_sections 
            if s.get('grade_level', {}).get('id') == str(grade_level_id) or 
               s.get('grade_level_id') == str(grade_level_id)
        ]
        
        return Response(grade_level_sections, status=status.HTTP_200_OK)

    def post(self, request, grade_level_id):
        grade_level = self.get_grade_level_object(grade_level_id)
        req_data: dict = request.data

        # Validate using business logic
        validation_result = section_service.validate_section_creation(
            name=req_data.get("name"),
            max_capacity=req_data.get("max_capacity")
        )
        
        if not validation_result["valid"]:
            return Response({"detail": validation_result["error"]}, status=400)
        
        # Check for duplicates
        if grade_level.sections.filter(name__iexact=validation_result["data"]["name"]).exists():
            return Response({"detail": "Section already exists"}, status=400)
        
        data = {
            "name": validation_result["data"]["name"],
            "description": validation_result["data"].get("description"),
            "max_capacity": validation_result["data"].get("capacity"),
            "room_number": req_data.get("room_number"),
        }

        try:
            section = section_adapter.create_section_in_db(
                data=data,
                grade_level_id=str(grade_level.id),
                source_section_id=req_data.get("source_section_id"),
                user=request.user
            )
            # Invalidate sections and grade_levels cache after creation
            self._invalidate_cache(request)
            
            serializer = SectionSerializer(section, context={"request": request})
            return Response(serializer.data, status=201)
        except Exception as e:
            return Response({"detail": str(e)}, status=400)
    
    def _invalidate_cache(self, request=None):
        """Invalidate section and grade_levels caches after modifications."""
        DataCache.invalidate_sections(request=request)
        DataCache.invalidate_grade_levels(request=request)
        # Also clear the raw grade_levels:{tenant} key used by GradeLevelListView.get
        tenant = get_tenant_from_request(request)
        if tenant:
            django_cache.delete(f"grade_levels:{tenant}")
        logger.debug(f"Invalidated section + grade_levels cache for tenant {tenant}")

class SectionDetailView(APIView):
    permission_classes = [AcademicsAccessPolicy]
    # permission_classes = [IsAuthenticatedOrReadOnly, IsAdminOrSystemAdmin]
    def get_object(self, id):
        try:
            return Section.objects.get(id=id)
        except Section.DoesNotExist:
            raise NotFound("Section does not exist with this id")

    def get(self, request, id):
        section = self.get_object(id)
        serializer = SectionSerializer(section, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    def put(self, request, id):
        section = self.get_object(id)

        allowed_fields = [
            "name",
            "description",
            "active",
        ]

        serializer = update_model_fields(
            request, section, allowed_fields, SectionSerializer
        )
        
        # Invalidate sections and grade_levels cache after update
        self._invalidate_cache(request)
        
        return Response(serializer.data, status=status.HTTP_200_OK)

    def delete(self, request, id):
        section = self.get_object(id)
        
        # Check if there are students enrolled in the section
        if section.enrollments.exists():
            section.active = False
            section.save()
            
            # Invalidate cache even when deactivating
            self._invalidate_cache(request)
            
            return Response(
                {
                    "detail": "Cannot delete section, it is associated with students. Section has been deactivated."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        
        # Delete the section
        section.delete()
        
        self._invalidate_cache(request)
        
        return Response(status=status.HTTP_204_NO_CONTENT)
    
    def _invalidate_cache(self, request=None):
        """Invalidate section and grade_levels caches after modifications."""
        DataCache.invalidate_sections(request=request)
        DataCache.invalidate_grade_levels(request=request)
        # Also clear the raw grade_levels:{tenant} key used by GradeLevelListView.get
        tenant = get_tenant_from_request(request)
        if tenant:
            django_cache.delete(f"grade_levels:{tenant}")
        logger.debug(f"Invalidated section + grade_levels cache for tenant {tenant}")
