from django.db.models import Q
from rest_framework import viewsets
from rest_framework.response import Response

from ..models import Department
from ..serializers import DepartmentSerializer
from ..access_policies import StaffAccessPolicy

# Import business logic (framework-agnostic)
from business.staff.services import staff_service
from business.staff.adapters import (
    create_department_in_db,
    update_department_in_db,
    delete_department_from_db,
)


class DepartmentViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Department CRUD operations with maximum optimization.

    Endpoints:
    - GET /departments/ - List departments
    - POST /departments/ - Create department
    - GET /departments/<pk>/ - Get department detail
    - PUT/PATCH /departments/<pk>/ - Update department
    - DELETE /departments/<pk>/ - Delete department
    """

    permission_classes = [StaffAccessPolicy]
    pagination_class = None
    serializer_class = DepartmentSerializer

    def get_queryset(self):
        """Get optimized queryset with all necessary relations"""
        queryset = (
            Department.objects.all()
        )

        # Apply filters
        search = self.request.query_params.get("search")
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search)
                | Q(code__icontains=search)
                | Q(description__icontains=search)
            )

        # Apply ordering
        ordering = self.request.query_params.get("ordering", "name")
        queryset = queryset.order_by(ordering)

        return queryset

    def create(self, request, *args, **kwargs):
        """Create department using business logic"""
        # Validate using business logic
        is_valid, errors = staff_service.validate_department_creation(request.data)
        if not is_valid:
            return Response({"errors": errors}, status=400)
        
        # Prepare data
        data = {
            'name': request.data.get('name', '').strip(),
            'code': request.data.get('code', '').strip(),
            'description': request.data.get('description', '').strip() or None,
        }
        
        # Create using adapter
        try:
            department = create_department_in_db(data, request.user)
            serializer = self.get_serializer(department)
            return Response(serializer.data, status=201)
        except Exception as e:
            return Response({"error": str(e)}, status=400)

    def update(self, request, *args, **kwargs):
        """Update department using business logic"""
        department = self.get_object()
        
        # Validate if name is being updated
        if 'name' in request.data:
            is_valid, errors = staff_service.validate_department_creation(request.data)
            if not is_valid:
                return Response({"errors": errors}, status=400)
        
        # Prepare data
        data = {}
        for field in ['name', 'code', 'description']:
            if field in request.data:
                data[field] = request.data[field]
        
        # Update using adapter
        try:
            updated_dept = update_department_in_db(str(department.id), data, request.user)
            if not updated_dept:
                return Response({"error": "Department not found"}, status=404)
            
            serializer = self.get_serializer(updated_dept)
            return Response(serializer.data)
        except Exception as e:
            return Response({"error": str(e)}, status=400)

    def destroy(self, request, *args, **kwargs):
        """Delete department using business logic"""
        department = self.get_object()
        try:
            delete_department_from_db(str(department.id), request.user)
            return Response(status=204)
        except Exception as e:
            return Response({"error": str(e)}, status=400)