from django.shortcuts import get_object_or_404
from django.db.models import Prefetch
from django.core.cache import cache
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from ..access_policies import AcademicsAccessPolicy
import logging

from common.utils import get_tenant_from_request, update_model_fields
from common.cache_service import DataCache

from ..models import GradeLevel, Section
from ..serializers import GradeLevelSerializer

logger = logging.getLogger(__name__)

# Business logic imports
from business.core.services import grade_level_service
from business.core.adapters import grade_level_adapter

class GradeLevelListView(APIView):
    permission_classes = [AcademicsAccessPolicy]
    # permission_classes = [AllowAny]

    def get(self, request):
        academic_year_id = request.query_params.get('academic_year_id')
        tenant = get_tenant_from_request(request)
        
        # Generate cache key based on academic year
        cache_key = f"grade_levels:{tenant}"
        if academic_year_id:
            cache_key += f":ay:{academic_year_id}"
        
        # Try to get from cache first
        cached_data = cache.get(cache_key)
        if cached_data:
            logger.debug(f"Cache HIT: grade_levels for tenant {tenant}, academic_year={academic_year_id}")
            return Response(cached_data)
        
        logger.debug(f"Cache MISS: grade_levels for tenant {tenant}, academic_year={academic_year_id}")
        
        # Build optimized query with Prefetch objects
        # Conditionally prefetch sections based on academic year
        if academic_year_id:
            sections_prefetch = Prefetch(
                'sections',
                queryset=Section.objects.filter(active=True, academic_year_id=academic_year_id),
                to_attr='filtered_sections'
            )
        else:
            sections_prefetch = Prefetch(
                'sections',
                queryset=Section.objects.filter(active=True),
                to_attr='filtered_sections'
            )
        
        # Fetch grade levels with optimized related data loading
        grade_levels = GradeLevel.objects.all().select_related(
            'division',
        ).prefetch_related(
            'tuition_fees',
            sections_prefetch
        ).order_by('level')
        
        # Serialize the grade levels
        serializer = GradeLevelSerializer(
            grade_levels, 
            many=True, 
            context={'request': request, 'academic_year_id': academic_year_id}
        )
        
        data = serializer.data
        
        # Cache the result for 5 minutes (300 seconds)
        cache.set(cache_key, data, 300)
        
        return Response(data)

    def post(self, request):
        req_data: dict = request.data
        tenant = get_tenant_from_request(request)

        # Validate using business logic
        validation_result = grade_level_service.validate_grade_level_creation(
            name=req_data.get("name"),
            short_name=req_data.get("short_name"),
            level=req_data.get("level")
        )
        
        if not validation_result["valid"]:
            return Response({"detail": validation_result["error"]}, status=400)
        
        # Check for duplicates
        if GradeLevel.objects.filter(name__iexact=validation_result["data"]["name"]).exists():
            return Response(
                {"detail": f"Grade Level named '{validation_result['data']['name']}' already exists"}, status=400
            )
        
        # Calculate level if not provided
        level = validation_result["data"].get("level")
        if not level:
            last_level = GradeLevel.objects.all().order_by("-level").first()
            level = int(last_level.level) + 1 if last_level else 1
        
        data = {
            "name": validation_result["data"]["name"],
            "short_name": validation_result["data"]["short_name"],
            "description": validation_result["data"].get("description"),
            "level": level,
        }
        
        try:
            grade_level = grade_level_adapter.create_grade_level_in_db(
                data=data,
                user=request.user
            )
            
            # Invalidate cache for this tenant
            self._invalidate_cache(tenant, request)
            
            serializer = GradeLevelSerializer(grade_level, context={"request": request})
            return Response(serializer.data, status=201)
        except Exception as e:
            return Response({"detail": str(e)}, status=400)
    
    def _invalidate_cache(self, tenant, request):
        """Invalidate all grade level cache entries for a tenant"""
        # Invalidate base cache key and all academic year variations
        # Note: This is a simple approach. For production, consider using cache.delete_pattern
        # or maintaining a set of cache keys
        cache_keys = [
            f"grade_levels:{tenant}",  # Without academic year
        ]
        # Also invalidate ReferenceDataCache
        DataCache.invalidate_grade_levels(request=request)
        
        for key in cache_keys:
            cache.delete(key)
        logger.debug(f"Invalidated grade_levels cache for tenant {tenant}")

class GradeLevelDetailView(APIView):
    permission_classes = [AcademicsAccessPolicy]
    # permission_classes = [IsAuthenticatedOrReadOnly, IsAdminOrSystemAdmin]
    def get_object(self, id):
        return get_object_or_404(GradeLevel, id=id)

    def get(self, request, id):
        grade_level = self.get_object(id)
        serializer = GradeLevelSerializer(grade_level)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def put(self, request, id):
        grade_level = self.get_object(id)
        tenant = get_tenant_from_request(request)

        allowed_fields = [
            "name",
            "description",
            "active",
            "level",
            # "tuition_fee",
            "short_name",
        ]

        serializer = update_model_fields(
            request, grade_level, allowed_fields, GradeLevelSerializer
        )
        
        # Invalidate cache for this grade level's tenant
        self._invalidate_cache(tenant, request)
        
        return Response(serializer.data, status=status.HTTP_200_OK)

    def delete(self, request, id):
        grade_level = self.get_object(id)
        tenant = get_tenant_from_request(request)
        # Check if grade level has students using business logic
        if grade_level_adapter.check_grade_level_has_students(str(grade_level.id)):
            return Response(
                {"detail": "Cannot delete grade level with associated enrollments."}, status=400
            )
        
        tenant = get_tenant_from_request(request)
        
        # Delete using adapter
        if grade_level_adapter.delete_grade_level_from_db(str(grade_level.id)):
            self._invalidate_cache(tenant, request)
            return Response(status=status.HTTP_204_NO_CONTENT)
        else:
            return Response({"detail": "Grade level not found"}, status=404)
    
    def _invalidate_cache(self, tenant, request):
        """Invalidate all grade level cache entries for a tenant"""
        # Invalidate base cache key and all academic year variations
        cache_keys = [
            f"grade_levels:{tenant}",  # Without academic year
        ]
        # Also invalidate ReferenceDataCache
        DataCache.invalidate_grade_levels(request=request)
        
        for key in cache_keys:
            cache.delete(key)
        logger.debug(f"Invalidated grade_levels cache for tenant {tenant}")