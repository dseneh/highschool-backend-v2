from django.db.models import Q
from rest_framework import viewsets
from rest_framework.response import Response
import re

from ..models import Position
from ..serializers import PositionSerializer
from ..access_policies import StaffAccessPolicy

# Import business logic (framework-agnostic)
from business.staff.services import staff_service
from business.staff.adapters import (
    create_position_in_db,
    update_position_in_db,
)


class PositionViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Position CRUD operations with maximum optimization.

    Endpoints:
    - GET /positions/ - List positions
    - POST /positions/ - Create position
    - GET /positions/<pk>/ - Get position detail
    - PUT/PATCH /positions/<pk>/ - Update position
    - DELETE /positions/<pk>/ - Delete position
    """

    permission_classes = [StaffAccessPolicy]
    pagination_class = None
    serializer_class = PositionSerializer

    def generate_position_code(self, title, exclude_id=None):
        """
        Generate a unique position code from title.
        Format: First letters of words in title, uppercase, max 30 chars.
        If code exists, append a number.
        """
        # Extract first letters of words, uppercase
        words = re.findall(r"\b\w", title)
        base_code = "".join(words).upper()[:25]  # Reserve space for number suffix

        # If base code is empty (no words), use a default
        if not base_code:
            base_code = "POS"

        # Check if code exists and generate unique one
        code = base_code
        counter = 1
        while True:
            lookup = Q(code=code)
            if exclude_id:
                lookup &= ~Q(id=exclude_id)

            if not Position.objects.filter(lookup).exists():
                break

            # Append number if code exists
            suffix = str(counter)
            # Ensure total length doesn't exceed 30
            max_base_length = 30 - len(suffix)
            code = base_code[:max_base_length] + suffix
            counter += 1

            if counter > 9999:
                import time

                code = f"POS{int(time.time()) % 100000}"
                break

        return code

    def get_queryset(self):
        """Get optimized queryset with all necessary relations"""
        queryset = (
            Position.objects
            .select_related("category", "department")
            .all()
        )

        # Apply filters
        search = self.request.query_params.get("search")
        if search:
            queryset = queryset.filter(
                Q(title__icontains=search) | Q(description__icontains=search)
            )

        category = self.request.query_params.get("category")
        if category:
            queryset = queryset.filter(category_id=category)

        department = self.request.query_params.get("department")
        if department:
            queryset = queryset.filter(department_id=department)

        teaching_role = self.request.query_params.get("teaching_role")
        if teaching_role is not None:
            teaching_role_bool = teaching_role.lower() in ["true", "1", "yes"]
            queryset = queryset.filter(teaching_role=teaching_role_bool)

        # Apply ordering
        ordering = self.request.query_params.get("ordering", "title")
        queryset = queryset.order_by(ordering)

        return queryset

    def create(self, request, *args, **kwargs):
        """Create position using business logic"""
        # Validate using business logic
        is_valid, errors = staff_service.validate_position_creation(request.data)
        if not is_valid:
            return Response({"errors": errors}, status=400)
        
        # Check for duplicate title in same department
        title = request.data.get('title')
        department_id = request.data.get('department')
        if Position.objects.filter(
            title=title, department_id=department_id
        ).exists():
            return Response(
                {"error": "Position with this title already exists for this department in this tenant"},
                status=400
            )
        
        # Prepare data
        data = {
            'title': request.data.get('title', '').strip(),
            'code': request.data.get('code', '').strip() or self.generate_position_code(title),
            'description': request.data.get('description', '').strip() or None,
            'level': request.data.get('level', 1),
            'employment_type': request.data.get('employment_type', 'full_time'),
            'compensation_type': request.data.get('compensation_type', 'salary'),
            'salary_min': request.data.get('salary_min'),
            'salary_max': request.data.get('salary_max'),
            'teaching_role': request.data.get('teaching_role', False),
            'can_delete': request.data.get('can_delete', True),
        }
        
        # Create using adapter
        try:
            position = create_position_in_db(
                data,
                category_id=request.data.get('category'),
                department_id=department_id,
                user=request.user
            )
            serializer = self.get_serializer(position)
            return Response(serializer.data, status=201)
        except Exception as e:
            return Response({"error": str(e)}, status=400)

    def update(self, request, *args, **kwargs):
        """Update position using business logic"""
        position = self.get_object()
        
        # Validate if core fields are being updated
        if any(f in request.data for f in ['title', 'salary_min', 'salary_max']):
            is_valid, errors = staff_service.validate_position_creation(request.data)
            if not is_valid:
                return Response({"errors": errors}, status=400)
        
        # Check for duplicate title if being updated
        title = request.data.get('title', position.title)
        department_id = request.data.get('department', position.department_id)
        
        if title != position.title or department_id != position.department_id:
            if Position.objects.filter(
                title=title, department_id=department_id
            ).exclude(id=position.id).exists():
                return Response(
                    {"error": "Position with this title already exists for this department in this tenant"},
                    status=400
                )
        
        # Prepare data
        data = {}
        allowed_fields = [
            'title', 'code', 'description', 'level', 'employment_type',
            'compensation_type', 'salary_min', 'salary_max', 'teaching_role'
        ]
        for field in allowed_fields:
            if field in request.data:
                data[field] = request.data[field]
        
        # Generate code if title changed but code not provided
        if 'title' in request.data and 'code' not in request.data:
            data['code'] = self.generate_position_code(title, exclude_id=position.id)
        
        # Update using adapter
        try:
            updated_position = update_position_in_db(str(position.id), data, request.user)
            if not updated_position:
                return Response({"error": "Position not found"}, status=404)
            
            serializer = self.get_serializer(updated_position)
            return Response(serializer.data)
        except Exception as e:
            return Response({"error": str(e)}, status=400)

