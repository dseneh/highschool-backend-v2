"""
Views for core models (Tenant management)
"""

from django.db import connection
from django.core.cache import cache
from rest_framework.permissions import IsAuthenticated, IsAdminUser, AllowAny
from rest_framework.viewsets import ModelViewSet
from rest_framework.exceptions import ValidationError, NotFound
from rest_framework.decorators import (
    api_view,
    permission_classes,
    authentication_classes,
    action,
)
from rest_framework.response import Response
from rest_framework import status
from rest_framework.parsers import MultiPartParser, FormParser
from django_tenants.utils import schema_context
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from PIL import Image
from io import BytesIO

from core.models import Tenant
from core.serializers import (
    TenantSerializer,
    CreateTenantSerializer,
    PublicTenantSerializer,
    TenantListSerializer,
    TenantInfoSearchResultSerializer,
)
from common.utils import update_model_fields
from common.audit_utils import log_tenant_control_change
from common.permissions import IsSuperAdmin
from students.models import Student
from staff.models import Staff

User = get_user_model()


def validate_tenant_is_in_public_schema():
    """
    Validate that the tenant is in the public schema.
    """
    if connection.schema_name != "public":
        raise ValidationError(
            {"detail": "Tenant operations must be performed in the public schema"}
        )
    return True


@api_view(["GET"])
@permission_classes([AllowAny])
def current_tenant(request):
    """
    Get the current tenant information based on the request schema.
    """
    if connection.schema_name == "public":
        return Response(
            {"detail": "No tenant context found (public schema)"}, status=400
        )

    try:
        tenant = Tenant.objects.get(schema_name=connection.schema_name)
        serializer = PublicTenantSerializer(tenant, context={"request": request})
        return Response(serializer.data)
    except Tenant.DoesNotExist:
        return Response({"detail": "Tenant not found"}, status=404)


class TenantViewSet(ModelViewSet):
    """
    ViewSet for Tenant management.

    Provides standard CRUD operations:
    - list: GET /api/v1/tenants/
    - create: POST /api/v1/tenants/
    - retrieve: GET /api/v1/tenants/{schema_name}/
    - update: PUT /api/v1/tenants/{schema_name}/
    - partial_update: PATCH /api/v1/tenants/{schema_name}/
    - destroy: DELETE /api/v1/tenants/{schema_name}/

    All operations must be performed in the public schema context.
    Only superusers or staff can perform tenant management operations.
    """

    queryset = Tenant.objects.all().order_by("name")
    lookup_field = "schema_name"
    lookup_url_kwarg = "schema_name"
    # Permissions are set dynamically in get_permissions() method

    # Fields allowed to be updated (filters out unwanted fields for performance)
    # NOTE: schema_name, id_number, and id are NOT in this list - they should NEVER be changed after creation
    # Changing schema_name would break tenant data access since django-tenants doesn't rename the PostgreSQL schema
    ALLOWED_UPDATE_FIELDS = [
        "name",
        "short_name",
        "funding_type",
        "school_type",
        "slogan",
        "emis_number",
        "description",
        "date_est",
        "address",
        "city",
        "state",
        "country",
        "postal_code",
        "phone",
        "email",
        "website",
        "status",
        "logo",
        "logo_shape",
        "theme_color",
        "theme_config",
        "active",
        "maintenance_mode",
        "login_access_policy",
        "disabled_access_allow_tenant_admins",
        "disabled_access_allowed_paths",
        "disabled_access_allowed_users",
    ]
    AUDITED_CONTROL_FIELDS = [
        "status",
        "active",
        "maintenance_mode",
        "login_access_policy",
        "disabled_access_allow_tenant_admins",
        "disabled_access_allowed_paths",
        "disabled_access_allowed_users",
    ]

    def _capture_control_state(self, instance):
        return {
            "status": getattr(instance, "status", None),
            "active": getattr(instance, "active", None),
            "maintenance_mode": getattr(instance, "maintenance_mode", None),
            "login_access_policy": getattr(instance, "login_access_policy", None),
            "disabled_access_allow_tenant_admins": getattr(instance, "disabled_access_allow_tenant_admins", None),
            "disabled_access_allowed_paths": getattr(instance, "disabled_access_allowed_paths", None),
            "disabled_access_allowed_users": getattr(instance, "disabled_access_allowed_users", None),
        }

    def _log_control_change_if_needed(self, request, instance, before_state, response):
        if response.status_code < 200 or response.status_code >= 300:
            return response

        if not any(field in request.data for field in self.AUDITED_CONTROL_FIELDS):
            return response

        instance.refresh_from_db()
        after_state = self._capture_control_state(instance)
        log_tenant_control_change(request, request.user, instance, before_state, after_state)
        return response

    def get_permissions(self):
        """
        Allow public access (no authentication) for list and retrieve actions.
        Require authentication and superadmin permissions for create, update, delete.

        Superadmin users can perform any operation in the system.
        """
        if self.action in ["list", "retrieve"]:
            return [AllowAny()]
        return [IsAuthenticated(), IsSuperAdmin()]

    def get_serializer_class(self):
        """
        Use appropriate serializer based on action and authentication status.
        """
        if self.action == "create":
            return CreateTenantSerializer
        elif self.action == "list":
            # Use lightweight list serializer for better performance
            return TenantListSerializer
        elif self.action == "retrieve":
            # Use public serializer for unauthenticated users (public endpoints)
            if not self.request.user.is_authenticated:
                return PublicTenantSerializer
        return TenantSerializer

    def get_queryset(self):
        """
        Ensure we're in the public schema and return appropriate tenants.
        Excludes public tenant and deleted tenants.
        For public endpoints (list/retrieve), only show active tenants.
        """
        from django_tenants.utils import get_public_schema_name

        if connection.schema_name != "public":
            return Tenant.objects.none()

        public_schema = get_public_schema_name()
        queryset = super().get_queryset()

        # Exclude public tenant (always)
        queryset = queryset.exclude(schema_name=public_schema)
        # Exclude deleted tenants (always)
        queryset = queryset.exclude(status="deleted")

        # For public endpoints, only show active tenants
        if (
            self.action in ["list", "retrieve"]
            and not self.request.user.is_authenticated
        ):
            queryset = queryset.filter(active=True)

        return queryset

    def get_object(self):
        """
        Resolve "admin" or "public" workspace alias to the public tenant on retrieve.

        This allows public lookup endpoints like:
        GET /api/v1/tenants/admin/
        GET /api/v1/tenants/public/
        to return the public schema tenant metadata.
        """
        from django_tenants.utils import get_public_schema_name

        lookup_kwarg = self.lookup_url_kwarg or self.lookup_field
        lookup_value = self.kwargs.get(lookup_kwarg)

        if (
            self.action == "retrieve"
            and isinstance(lookup_value, str)
            and lookup_value.lower() in ["admin", "public"]
        ):
            try:
                obj = Tenant.objects.get(schema_name=get_public_schema_name())
            except Tenant.DoesNotExist:
                raise NotFound("Public tenant not found")

            self.check_object_permissions(self.request, obj)
            return obj

        return super().get_object()

    def perform_create(self, serializer):
        """
        Create tenant - custom logic is handled in CreateTenantSerializer.create().
        """
        # Ensure we're in the public schema
        validate_tenant_is_in_public_schema()
        serializer.save()

    def update(self, request, *args, **kwargs):
        """
        Update tenant using field filtering for performance.
        Only updates fields that are in the request and in allowed_fields list.
        """
        validate_tenant_is_in_public_schema()

        instance = self.get_object()
        before_state = self._capture_control_state(instance)

        response = update_model_fields(
            request,
            instance,
            self.ALLOWED_UPDATE_FIELDS,
            TenantSerializer,
            context={"request": request},
        )
        return self._log_control_change_if_needed(request, instance, before_state, response)

    def partial_update(self, request, *args, **kwargs):
        """
        Partially update tenant using field filtering for performance.
        Only updates fields that are in the request and in allowed_fields list.
        """
        validate_tenant_is_in_public_schema()

        instance = self.get_object()
        before_state = self._capture_control_state(instance)

        response = update_model_fields(
            request,
            instance,
            self.ALLOWED_UPDATE_FIELDS,
            TenantSerializer,
            context={"request": request},
        )
        return self._log_control_change_if_needed(request, instance, before_state, response)

    def perform_destroy(self, instance):
        """
        Delete tenant - ensure we're in the public schema.

        Performs a soft delete: sets status to 'deleted' and active to False.
        The tenant record and schema remain in the database but are marked as deleted.

        To permanently delete a tenant (drop schema and remove record), use a separate
        hard delete operation (not implemented via API for safety).
        """
        from django_tenants.utils import get_public_schema_name

        validate_tenant_is_in_public_schema()

        # Prevent public tenant deletion
        if instance.schema_name == get_public_schema_name():
            raise ValidationError({"detail": "Cannot delete public tenant"})

        # Soft delete: Set status to 'deleted' and active to False
        # The save() method will automatically sync active with status
        instance.status = "deleted"
        instance.active = False  # Explicitly set, but save() will sync it anyway
        instance.save(update_fields=["status", "active"])

    @action(
        detail=True,
        methods=["put", "patch"],
        url_path="logo",
        parser_classes=[MultiPartParser, FormParser],
    )
    def update_logo(self, request, *args, **kwargs):
        """
        Upload/update tenant logo.

        Endpoint:
        - PUT /api/v1/tenants/{schema_name}/logo/
        """
        validate_tenant_is_in_public_schema()

        instance = self.get_object()
        logo_file = request.FILES.get("logo")
        if not logo_file:
            raise ValidationError({"logo": "Logo file is required."})

        # Resize raster images to reduce storage while keeping original format
        if logo_file.content_type != "image/svg+xml":
            max_dimension = 512
            image = Image.open(logo_file)
            image_format = image.format or "PNG"

            if image.mode in ("P", "RGBA") and image_format.upper() == "JPEG":
                image = image.convert("RGB")

            image.thumbnail((max_dimension, max_dimension))

            buffer = BytesIO()
            save_kwargs = {}
            if image_format.upper() == "JPEG":
                save_kwargs = {"quality": 85, "optimize": True}
            elif image_format.upper() == "PNG":
                save_kwargs = {"optimize": True}

            image.save(buffer, format=image_format, **save_kwargs)
            buffer.seek(0)

            content = ContentFile(buffer.read())
            instance.logo.save(logo_file.name, content, save=False)
        else:
            instance.logo = logo_file

        logo_shape = request.data.get("logo_shape")
        if logo_shape:
            instance.logo_shape = logo_shape

        instance.save()

        serializer = TenantSerializer(instance, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)


@api_view(["GET"])
@authentication_classes([])  # Disable authentication - this is a public endpoint
@permission_classes([AllowAny])
def search_tenant_info(request):
    """
    Search for tenant information by email, phone, username, or id_number.

    Public endpoint - no authentication or tenant header required.
    Searches across User (public schema), Student and Staff (tenant schemas).
    Returns all matching records since email and phone_number are not unique.

    Query Parameters:
    - email: Email address to search for
    - phone: Phone number to search for
    - username: Username to search for
    - id_number: ID number to search for

    At least one parameter is required.

    Returns:
    List of matching records with the following structure:
    {
        "user_type": "user|student|staff",
        "tenant": {tenant info} (schema_name: "admin" for users, specific tenant for students/staff),
        "data": {user/student/staff data}
    }
    """
    from django.db.models import Q
    from django_tenants.utils import get_public_schema_name

    email = request.query_params.get("email")
    phone = request.query_params.get("phone")
    username = request.query_params.get("username")
    id_number = request.query_params.get("id_number")

    # Validate that at least one search parameter is provided
    if not any([email, phone, username, id_number]):
        return Response(
            {
                "error": "At least one search parameter (email, phone, username, or id_number) is required"
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    results = []

    # Ensure we're operating from the public schema context regardless of any tenant header
    with schema_context(get_public_schema_name()):
        # Get public tenant info for user results (for consistency with student/staff structure)
        # Display as "admin" schema for better clarity
        try:
            public_tenant = Tenant.objects.get(schema_name=get_public_schema_name())
            public_tenant_info = {
                "id": str(public_tenant.id),
                "schema_name": "admin",  # Display as "admin" instead of "public" for clarity
                "name": public_tenant.name,
                "short_name": public_tenant.short_name,
            }
        except Tenant.DoesNotExist:
            public_tenant_info = {
                "id": None,
                "schema_name": "admin",  # Display as "admin" for user-facing consistency
                "name": "Admin",
                "short_name": "Admin",
            }

        # Get all active tenants (optimized query)
        tenants = (
            Tenant.objects.exclude(schema_name=get_public_schema_name())
            .filter(active=True)
            .exclude(status="deleted", active=False)
            .only("id", "schema_name", "name", "short_name")
        )

        # Search in User model (public schema) - Users don't have phone field
        if email or username or id_number:
            # Build Q object for OR conditions
            user_filters = Q()
            if email:
                user_filters |= Q(email__iexact=email)
            if username:
                user_filters |= Q(username__iexact=username)
            if id_number:
                user_filters |= Q(id_number=id_number)

            # Apply filters and select only needed fields
            users = User.objects.filter(user_filters).only(
                "id",
                "id_number",
                "email",
                "first_name",
                "last_name",
                "username",
                "account_type",
                "is_active",
            )

            for user in users:
                tenant_infos = []

                # Include admin workspace for superusers.
                if user.is_superuser:
                    tenant_infos.append(public_tenant_info)

                # Include tenant workspaces where this user has tenant permissions.
                try:
                    from tenant_users.permissions.models import UserTenantPermissions

                    for tenant in tenants:
                        with schema_context(tenant.schema_name):
                            if UserTenantPermissions.objects.filter(
                                profile_id=user.id
                            ).exists():
                                tenant_infos.append(
                                    {
                                        "id": str(tenant.id),
                                        "schema_name": tenant.schema_name,
                                        "name": tenant.name,
                                        "short_name": tenant.short_name,
                                    }
                                )
                except Exception:
                    # Fallback to admin/public tenant when permission lookup fails.
                    if not tenant_infos:
                        tenant_infos.append(public_tenant_info)

                if not tenant_infos:
                    tenant_infos.append(public_tenant_info)

                for tenant_info in tenant_infos:
                    results.append(
                        {
                            "user_type": "user",
                            "tenant": tenant_info,
                            "data": {
                                "id": str(user.id),
                                "id_number": user.id_number,
                                "email": user.email,
                                "first_name": user.first_name,
                                "last_name": user.last_name,
                                "full_name": user.get_full_name(),
                                "username": user.username,
                                "account_type": user.account_type,
                                "is_active": user.is_active,
                            },
                        }
                    )

        # Search in each tenant's schema
        for tenant in tenants:
            with schema_context(tenant.schema_name):
                tenant_info = {
                    "id": str(tenant.id),
                    "schema_name": tenant.schema_name,
                    "name": tenant.name,
                    "short_name": tenant.short_name,
                }

                # Build Q object for Student/Staff filters (supports OR logic)
                filters = Q()
                if email:
                    filters |= Q(email__iexact=email)
                if phone:
                    filters |= Q(phone_number__icontains=phone)
                if id_number:
                    filters |= Q(id_number=id_number)

                # Search Students with optimized query
                students = (
                    Student.objects.filter(filters)
                    .select_related("grade_level")
                    .only(
                        "id",
                        "id_number",
                        "email",
                        "phone_number",
                        "first_name",
                        "middle_name",
                        "last_name",
                        "gender",
                        "status",
                        "grade_level",
                    )
                )

                for student in students:
                    results.append(
                        {
                            "user_type": "student",
                            "tenant": tenant_info,
                            "data": {
                                "id": str(student.id),
                                "id_number": student.id_number,
                                "email": student.email,
                                "phone_number": student.phone_number,
                                "first_name": student.first_name,
                                "middle_name": student.middle_name,
                                "last_name": student.last_name,
                                "full_name": student.get_full_name(),
                                "gender": student.gender,
                                "status": student.status,
                                "grade_level": student.grade_level.name
                                if student.grade_level
                                else None,
                            },
                        }
                    )

                # Search Staff with optimized query
                staff_members = (
                    Staff.objects.filter(filters)
                    .select_related("position")
                    .only(
                        "id",
                        "id_number",
                        "email",
                        "phone_number",
                        "first_name",
                        "middle_name",
                        "last_name",
                        "gender",
                        "status",
                        "position",
                        "is_teacher",
                    )
                )

                for staff_member in staff_members:
                    results.append(
                        {
                            "user_type": "staff",
                            "tenant": tenant_info,
                            "data": {
                                "id": str(staff_member.id),
                                "id_number": staff_member.id_number,
                                "email": staff_member.email,
                                "phone_number": staff_member.phone_number,
                                "first_name": staff_member.first_name,
                                "middle_name": staff_member.middle_name,
                                "last_name": staff_member.last_name,
                                "full_name": staff_member.get_full_name(),
                                "gender": staff_member.gender,
                                "status": staff_member.status,
                                "position": staff_member.position.title
                                if staff_member.position
                                else None,
                                "is_teacher": staff_member.is_teacher,
                            },
                        }
                    )

    # Deduplicate results by (id_number + workspace)
    # Priority: student > staff > user (prefer actual records over user accounts)
    # This ensures parents using shared emails see unique workspace entries
    unique_results = {}
    priority_order = {"student": 3, "staff": 2, "user": 1}

    for result in results:
        result_id_number = result["data"].get("id_number")
        result_workspace = result.get("tenant", {}).get("schema_name")
        result_user_type = result["user_type"]

        # Skip if no id_number (shouldn't happen, but be safe)
        if not result_id_number or not result_workspace:
            continue

        unique_key = f"{result_id_number}:{result_workspace}"

        # If this id_number hasn't been seen, add it
        if unique_key not in unique_results:
            unique_results[unique_key] = result
        else:
            # If already seen, keep the one with higher priority
            existing_priority = priority_order.get(
                unique_results[unique_key]["user_type"], 0
            )
            current_priority = priority_order.get(result_user_type, 0)

            if current_priority > existing_priority:
                unique_results[unique_key] = result

    # Convert unique results back to list
    deduplicated_results = list(unique_results.values())

    # Serialize the deduplicated results
    serializer = TenantInfoSearchResultSerializer(deduplicated_results, many=True)

    return Response(
        {
            "count": len(deduplicated_results),
            "total_matches": len(results),  # Original count before deduplication
            "search_params": {
                "email": email,
                "phone": phone,
                "username": username,
                "id_number": id_number,
            },
            "results": serializer.data,
        },
        status=status.HTTP_200_OK,
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def invalidate_cache(request):
    """
    Invalidate cache entries for a specific data type.

    Expected payload:
    {
        "data_type": "theme|branding|organization|schools|all"
    }
    """
    data_type = request.data.get("data_type", "all")

    # Define cache key patterns for different data types
    cache_patterns = {
        "theme": "theme_*",
        "branding": "branding_*",
        "organization": "org_*",
        "schools": "school_*",
        "all": "*",
    }

    pattern = cache_patterns.get(data_type, "all")

    if pattern == "*":
        # Clear all cache
        cache.clear()
        message = "All cache cleared"
    else:
        # For now, just clear all cache (locmem doesn't support pattern-based deletion)
        # In production with Redis, you could use pattern-based deletion
        cache.clear()
        message = f"Cache cleared for data_type: {data_type}"

    return Response(
        {"status": "success", "message": message, "data_type": data_type},
        status=status.HTTP_200_OK,
    )
