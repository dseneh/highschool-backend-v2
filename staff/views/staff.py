from django.db import connection
from django.db.models import Q
from django_tenants.utils import get_tenant_model
from rest_framework import viewsets, status, serializers
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination
from rest_framework.exceptions import NotFound

from common.utils import get_object_by_uuid_or_fields
from users.models import User
from ..models import Staff
from ..serializers import StaffSerializer, StaffDetailSerializer
from ..access_policies import StaffAccessPolicy

from business.staff.services import staff_service
from business.staff.adapters import (
    create_staff_in_db,
    update_staff_in_db,
    delete_staff_from_db,
    django_staff_to_data,
    staff_has_user_account,
    staff_has_teaching_sections,
    check_staff_exists_by_id,
    check_staff_exists_by_email,
    check_staff_exists_by_name_dob,
)


class StaffPageNumberPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class StaffViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Staff CRUD operations with maximum optimization.

    Endpoints:
    - GET staff/ - List staff
    - POST staff/ - Create staff
    - GET staff/<pk>/ - Get staff detail
    - PUT/PATCH staff/<pk>/ - Update staff
    - DELETE staff/<pk>/ - Delete staff
    - GET staff/teachers/ - List teachers (staff with teaching positions)
    """

    permission_classes = [StaffAccessPolicy]
    pagination_class = StaffPageNumberPagination
    serializer_class = StaffSerializer

    def get_queryset(self):
        """Get optimized queryset with all necessary relations"""
        queryset = Staff.objects.all().with_relations()

        # Apply filters
        search = self.request.query_params.get("search")
        if search:
            queryset = queryset.search(search)

        position = self.request.query_params.get("position")
        if position:
            queryset = queryset.by_position(position)

        status_filter = self.request.query_params.get("status")
        if status_filter:
            statuses = [status.strip() for status in status_filter.split(",") if status.strip()]
            if len(statuses) == 1:
                queryset = queryset.by_status(statuses[0])
            elif len(statuses) > 1:
                queryset = queryset.filter(status__in=statuses)

        department = self.request.query_params.get("department")
        if department:
            department_ids = [value.strip() for value in department.split(",") if value.strip()]
            if len(department_ids) == 1:
                queryset = queryset.filter(primary_department_id=department_ids[0])
            elif len(department_ids) > 1:
                queryset = queryset.filter(primary_department_id__in=department_ids)
        
        is_teacher = self.request.query_params.get("is_teacher")
        if is_teacher is not None:
            if is_teacher.lower() in ['true', '1']:
                f = Q(is_teacher=True) | Q(position__teaching_role=True)
                queryset = queryset.filter(f)
            elif is_teacher.lower() in ['false', '0']:
                f = Q(is_teacher=False) & (Q(position__teaching_role=False) | Q(position__isnull=True))
                queryset = queryset.filter(f)

        gender = self.request.query_params.get("gender")
        if gender:
            genders = [value.strip().lower() for value in gender.split(",") if value.strip()]
            if len(genders) == 1:
                queryset = queryset.filter(gender__iexact=genders[0])
            elif len(genders) > 1:
                queryset = queryset.filter(gender__in=genders)

        # Apply ordering
        ordering = self.request.query_params.get("ordering", "-created_at")
        queryset = queryset.order_by_default(ordering)

        return queryset

    def get_object(self):
        """
        Override to support lookup by both UUID id and id_number.
        The pk from URL can be either the staff's UUID or id_number.
        """
        lookup_value = self.kwargs.get("pk")
        
        try:
            return get_object_by_uuid_or_fields(
                Staff, 
                lookup_value, 
                fields=['id_number']
            )
        except Staff.DoesNotExist:
            raise NotFound("Staff does not exist with this id")

    def get_serializer_class(self):
        """Use detail serializer for retrieve, list serializer for list"""
        if self.action == "retrieve":
            return StaffDetailSerializer
        return StaffSerializer

    def create(self, request, *args, **kwargs):
        """Create staff using business logic"""
        # Validate using business logic
        is_valid, errors = staff_service.validate_staff_creation(request.data)
        if not is_valid:
            return Response({"errors": errors}, status=400)
        
        # Check for duplicates using business logic + adapter
        id_number = request.data.get('id_number')
        if id_number and check_staff_exists_by_id(id_number):
            return Response(
                {"error": "Staff with this ID number already exists"}, 
                status=400
            )
        
        email = request.data.get('email')
        if email and check_staff_exists_by_email(email):
            return Response(
                {"error": "Staff with this email already exists"},
                status=400
            )
        
        # Check name + DOB + gender combination
        if all(request.data.get(f) for f in ['first_name', 'last_name', 'date_of_birth', 'gender']):
            if check_staff_exists_by_name_dob(
                request.data['first_name'],
                request.data['last_name'],
                request.data['date_of_birth'],
                request.data['gender'],
            ):
                return Response(
                    {"error": "A staff with the same name and date of birth already exists"},
                    status=400
                )
        
        # Prepare data using business logic
        prepared_data = staff_service.prepare_staff_data_for_creation(request.data)
        
        # Create in database using adapter
        try:
            staff = create_staff_in_db(
                prepared_data,
                position_id=prepared_data.get('position_id'),
                department_id=prepared_data.get('primary_department_id'),
                user=request.user
            )
            
            # Handle photo if provided
            if 'photo' in request.FILES:
                from common.images import update_model_image
                update_model_image(
                    staff, 'photo', request.FILES['photo']
                )
            
            # Create user account if requested
            if staff_service.should_create_user_account(request.data.get('initialize_user')):
                self._create_user_account_for_staff(staff, request.data, request.user)
            
            serializer = self.get_serializer(staff)
            return Response(serializer.data, status=201)
            
        except Exception as e:
            return Response({"error": str(e)}, status=400)

    def update(self, request, *args, **kwargs):
        """Update staff using business logic"""
        staff = self.get_object()
        staff_data = django_staff_to_data(staff)
        
        # Validate using business logic
        is_valid, errors = staff_service.validate_staff_update(request.data, staff_data)
        if not is_valid:
            return Response({"errors": errors}, status=400)
        
        # Check for duplicate ID number if being updated
        new_id_number = request.data.get('id_number')
        if new_id_number and new_id_number != staff.id_number:
            if check_staff_exists_by_id(new_id_number):
                return Response(
                    {"error": "Staff with this ID number already exists"},
                    status=400
                )
        # Prepare data
        prepared_data = {k: v for k, v in request.data.items() 
                        if k in staff_service.get_allowed_update_fields()}
        
        # Update in database using adapter
        try:
            updated_staff = update_staff_in_db(
                str(staff.id),
                prepared_data,
                position_id=prepared_data.get('position'),
                department_id=prepared_data.get('primary_department'),
                manager_id=prepared_data.get('manager'),
                user=request.user
            )
            
            if not updated_staff:
                return Response({"error": "Staff not found"}, status=404)
            
            # Handle photo if provided
            if 'photo' in request.FILES:
                from common.images import update_model_image
                update_model_image(
                    updated_staff, 'photo', request.FILES['photo']
                )
            
            serializer = self.get_serializer(updated_staff)
            return Response(serializer.data)
            
        except Exception as e:
            return Response({"error": str(e)}, status=400)
    
    def destroy(self, request, *args, **kwargs):
        """Delete staff using business logic"""
        staff = self.get_object()
        staff_data = django_staff_to_data(staff)
        
        # Check business rules using business logic
        can_delete, error_msg = staff_service.can_delete_staff(
            staff_data,
            has_user_account=staff_has_user_account(str(staff.id)),
            has_teaching_sections=staff_has_teaching_sections(str(staff.id))
        )
        
        if not can_delete:
            return Response({"error": error_msg}, status=400)
        
        # Delete from database using adapter
        if delete_staff_from_db(str(staff.id)):
            return Response(status=204)
        else:
            return Response({"error": "Failed to delete staff"}, status=400)
    
    def _create_user_account_for_staff(self, staff, data, user):
        """Helper to create user account for staff"""
        from users.models import CustomUser
        from common.status import Roles, PersonStatus, UserAccountType
        
        username = data.get("username") or staff.id_number
        role = data.get("role", Roles.VIEWER)
        
        # Check if username already exists
        if CustomUser.objects.filter(username=username).exists():
            raise serializers.ValidationError(f"Username '{username}' already exists")
        
        # Check if id_number already exists as a user
        if CustomUser.objects.filter(id_number=staff.id_number).exists():
            raise serializers.ValidationError(
                f"User account with ID number '{staff.id_number}' already exists"
            )
        
        # Create user account
        user_account = User.objects.create_user(
            id_number=staff.id_number,
            username=username,
            email=staff.email or f"{username}@example.com",
            first_name=staff.first_name,
            last_name=staff.last_name,
            gender=staff.gender,
            role=role,
            account_type=UserAccountType.STAFF,
            status=PersonStatus.CREATED,
            created_by=user,
            updated_by=user,
            is_active=True,
        )
        
        # Set default password to id_number
        user_account.set_password(staff.id_number)
        user_account.save()

        tenant_schema_name = connection.schema_name
        if tenant_schema_name != "public":
            tenant_model = get_tenant_model()
            tenant = tenant_model.objects.filter(schema_name=tenant_schema_name).first()
            if tenant is not None:
                try:
                    tenant.add_user(user_account, is_staff=True, is_superuser=False)
                except Exception as exc:
                    if "already" not in str(exc).lower() and "exists" not in str(exc).lower():
                        raise
        
        # Link user account to staff (loose coupling via id_number)
        staff.user_account_id_number = user_account.id_number
        staff.save(update_fields=["user_account_id_number"])

    @action(detail=False, methods=["get"], url_path="teachers")
    def teachers(self, request):
        """
        Custom action to get all teachers (staff with teaching positions).

        GET staff/teachers/

        Supports same query parameters as list:
        - search: Search by name, email, etc.
        - status: Filter by employment status
        - ordering: Order results
        """
        # Get base queryset filtered for teachers
        # Teachers are staff with is_teacher=True OR position with teaching_role=True
        queryset = (
            Staff.objects.filter(Q(is_teacher=True) | Q(position__teaching_role=True))
        )

        # Apply filters (same as get_queryset)
        search = request.query_params.get("search")
        if search:
            queryset = queryset.search(search)

        status_filter = request.query_params.get("status")
        if status_filter:
            queryset = queryset.by_status(status_filter)

        # Apply ordering
        ordering = request.query_params.get("ordering", "-created_at")
        queryset = queryset.order_by_default(ordering)

        # Paginate
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        # If no pagination, return all results
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

