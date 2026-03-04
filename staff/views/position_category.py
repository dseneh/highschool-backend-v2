from django.db.models import Q
from rest_framework import viewsets

from ..models import PositionCategory
from ..serializers import PositionCategorySerializer
from ..access_policies import StaffAccessPolicy
from ..utils import filter_allowed_fields


class PositionCategoryViewSet(viewsets.ModelViewSet):
    """
    ViewSet for PositionCategory CRUD operations with maximum optimization.

    Endpoints:
    - GET /position-categories/ - List position categories
    - POST /position-categories/ - Create position category
    - GET /position-categories/<pk>/ - Get position category detail
    - PUT/PATCH /position-categories/<pk>/ - Update position category
    - DELETE /position-categories/<pk>/ - Delete position category
    """

    permission_classes = [StaffAccessPolicy]
    pagination_class = None
    serializer_class = PositionCategorySerializer

    def get_queryset(self):
        """Get optimized queryset with all necessary relations"""
        queryset = PositionCategory.objects.all()

        # Apply filters
        search = self.request.query_params.get("search")
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) | Q(description__icontains=search)
            )

        # Apply ordering
        ordering = self.request.query_params.get("ordering", "name")
        queryset = queryset.order_by(ordering)

        return queryset

    def perform_create(self, serializer):
        """Create position category with field filtering"""
        # Define allowed fields for creation
        allowed_fields = ["name", "description", "active"]
        
        # Filter validated_data to only include allowed fields
        filtered_data = filter_allowed_fields(serializer.validated_data, allowed_fields)
        
        # Update serializer with filtered data
        for key, value in filtered_data.items():
            serializer.validated_data[key] = value
        
        serializer.save(created_by=self.request.user, updated_by=self.request.user)

    def perform_update(self, serializer):
        """Update position category with field filtering"""
        # Define allowed fields for update
        allowed_fields = ["name", "description", "active"]
        
        # Filter validated_data to only include allowed fields
        filtered_data = filter_allowed_fields(serializer.validated_data, allowed_fields)
        
        # Update serializer with filtered data
        for key, value in filtered_data.items():
            serializer.validated_data[key] = value
        
        serializer.save(updated_by=self.request.user)

