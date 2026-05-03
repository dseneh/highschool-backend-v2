"""
Views for authentication and user management
"""
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.authentication import JWTStatelessUserAuthentication
from rest_framework.pagination import PageNumberPagination
from django.conf import settings
from django.db.models import Q
from django.db import connection
from django_tenants.utils import schema_context

from users.serializers import (
    MultiFieldTokenObtainPairSerializer, 
    UserSerializer,
    UserCreateSerializer,
    UserUpdateSerializer,
    PasswordChangeSerializer,
    PasswordForgotSerializer,
    UserRecreateSerializer,
)
from users.models import User
from users.access_policies import UserAccessPolicy
from common.status import UserAccountType, Roles


def build_unique_username(base_username: str) -> str:
    """
    Generate a unique username by appending a numeric suffix if the base username already exists.
    
    Args:
        base_username: The desired username base (e.g., 'id_number' or 'student_id_123')
    
    Returns:
        A unique username guaranteed not to exist in the database
    
    Examples:
        build_unique_username('john_doe')      -> 'john_doe' (if available)
        build_unique_username('john_doe')      -> 'john_doe_1' (if 'john_doe' exists)
        build_unique_username('john_doe')      -> 'john_doe_2' (if both above exist)
    """
    candidate = base_username
    index = 1
    while User.objects.filter(username=candidate).exists():
        candidate = f"{base_username}_{index}"
        index += 1
    return candidate


class MultiFieldTokenObtainPairView(TokenObtainPairView):
    """
    Custom token view that accepts username, email, or id_number in the username field for login.
    
    Usage:
    POST /api/v1/auth/token/
    {
        "username": "admin01",  // Can be username, id_number, or email
        "password": "your_password"
    }
    
    Note: The username field accepts username, id_number, or email.
    """
    serializer_class = MultiFieldTokenObtainPairSerializer

    def post(self, request, *args, **kwargs):
        from common.audit_utils import log_auth_event

        identifier = request.data.get("username", "")
        try:
            response = super().post(request, *args, **kwargs)
        except Exception:
            log_auth_event(
                request,
                None,
                "login_failed",
                details={"identifier": identifier},
            )
            raise

        user_data = response.data.get("user", {})
        user_id = user_data.get("id")
        if user_id:
            try:
                user = User.objects.get(pk=user_id)
                log_auth_event(request, user, "login_success")
            except User.DoesNotExist:
                pass
        return response


class CurrentUserView(APIView):
    """
    Get current authenticated user information from JWT token.
    
    This endpoint uses stateless JWT authentication - it doesn't hit the database
    to verify the user, instead it validates the JWT token and constructs the user
    object from the token payload.
    
    Usage:
    GET /api/v1/auth/current-user/
    Headers:
        Authorization: Bearer <access_token>
    
    Response:
    {
        "id": 1,
        "username": "admin01",
        "email": "admin@example.com",
        "id_number": "12345",
        "first_name": "Admin",
        "last_name": "User",
        "account_type": "SUPERADMIN",
        "role": "SUPERADMIN",
        "photo": "http://...",
        "is_active": true,
        "tenants": [
            {"id": "1", "schema_name": "school1", "name": "School 1"}
        ],
        "workspace": "school1"
    }
    """
    authentication_classes = [JWTStatelessUserAuthentication]
    permission_classes = [UserAccessPolicy]
    
    def get(self, request):
        """Return current user information from JWT token."""
        serializer = UserSerializer(request.user, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)


class VerifyTokenView(APIView):
    """
    Verify if the provided JWT token is valid.
    
    This endpoint only checks if the token is valid and not expired.
    It uses stateless JWT validation (no database query).
    
    Usage:
    GET /api/v1/auth/verify/
    Headers:
        Authorization: Bearer <access_token>
    
    Response (valid token):
    {
        "valid": true,
        "user_id": 1,
        "username": "admin01",
        "role": "SUPERADMIN"
    }
    
    Response (invalid token):
    HTTP 401 Unauthorized
    """
    authentication_classes = [JWTStatelessUserAuthentication]
    permission_classes = [UserAccessPolicy]
    
    def get(self, request):
        """Verify token validity and return basic user info."""
        return Response({
            "valid": True,
            "user_id": request.user.id,
            "username": request.user.username,
            "role": request.user.role,
            "account_type": request.user.account_type,
        }, status=status.HTTP_200_OK)


class TenantUserPagination(PageNumberPagination):
    """
    Pagination for tenant users list.
    """
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


class TenantUsersView(APIView):
    """
    Get all users for the current tenant (identified by x-tenant header).
    Also supports creating new users in the tenant.
    
    GET: Returns users who have access to this tenant via UserTenantPermissions.
    POST: Create a user from source record and add them to the current tenant.
         Username defaults to id_number if not provided. Users can change their username later.
         Password defaults to id_number with is_default_password=True flag.
    
    Supports filtering (GET only):
    - search: search across name, email, username, id_number
    - role: filter by user role (supports multiple: ?role=ADMIN&role=TEACHER)
    - account_type: filter by account type (supports multiple: ?account_type=STUDENT&account_type=STAFF)
    - is_active: filter by active status (true/false)
    - is_staff: filter by staff status (true/false)
    - is_superuser: filter by superuser status (true/false)
    - is_default_password: filter by default password status (true/false)
    - ordering: sort results (default: -date_joined)
    
    POST payload requires:
    - account_type: STUDENT, STAFF, or PARENT
    - id_number: required to lookup source record
    - date_of_birth: required to match source record
    - username: optional, defaults to id_number
    
    Example:
        GET /api/v1/users/?search=john&role=TEACHER&is_active=true&account_type=STAFF
        POST /api/v1/users/ {
            "account_type": "STUDENT",
            "id_number": "123456",
            "date_of_birth": "2005-01-15",
            "username": "john_doe"  # optional
        }
    """
    permission_classes = [UserAccessPolicy]
    pagination_class = TenantUserPagination
    
    def get(self, request):
        """
        Get all users who have access to the current tenant.
        """
        # Ensure we're in a tenant schema (not public)
        if connection.schema_name == 'public':
            return Response(
                {"detail": "This endpoint must be accessed from a tenant context (with x-tenant header)"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            from tenant_users.permissions.models import UserTenantPermissions
            
            # Get user IDs who have permissions in this tenant (current schema)
            user_ids = UserTenantPermissions.objects.values_list('profile_id', flat=True).distinct()
            print(f"Tenant {connection.schema_name} has {len(user_ids)} users with permissions.")
            # Get User objects from public schema
            with schema_context('public'):
                users_queryset = User.objects.filter(id__in=list(user_ids))
                
                # Apply search filter
                search = request.query_params.get('search')
                if search:
                    users_queryset = users_queryset.filter(
                        Q(first_name__icontains=search) |
                        Q(last_name__icontains=search) |
                        Q(username__icontains=search) |
                        Q(email__icontains=search) |
                        Q(id_number__icontains=search)
                    )
                
                # Apply role filter (multi-value support)
                roles = request.query_params.getlist('role')
                if roles:
                    users_queryset = users_queryset.filter(role__in=roles)
                
                # Apply account_type filter (multi-value support)
                account_types = request.query_params.getlist('account_type')
                if account_types:
                    users_queryset = users_queryset.filter(account_type__in=account_types)
                
                # Apply boolean filters
                for field in ['is_active', 'is_staff', 'is_superuser', 'is_default_password']:
                    value = request.query_params.get(field)
                    if value is not None:
                        bool_value = value.lower() in ['true', '1', 'yes']
                        users_queryset = users_queryset.filter(**{field: bool_value})
                
                # Apply ordering
                ordering = request.query_params.get('ordering', '-id')
                valid_orderings = [
                    'first_name', '-first_name',
                    'last_name', '-last_name',
                    'username', '-username',
                    'email', '-email',
                    'role', '-role',
                    'id', '-id',
                    'last_login', '-last_login',
                    'id_number', '-id_number',
                ]
                
                if ordering in valid_orderings:
                    users_queryset = users_queryset.order_by(ordering)
                else:
                    users_queryset = users_queryset.order_by('-id')
                
                # Paginate results
                paginator = TenantUserPagination()
                page = paginator.paginate_queryset(users_queryset, request)
                
                if page is not None:
                    serializer = UserSerializer(page, many=True, context={'request': request})
                    return paginator.get_paginated_response(serializer.data)
                
                serializer = UserSerializer(users_queryset, many=True, context={'request': request})
                return Response(serializer.data)
                
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error getting users for tenant {connection.schema_name}: {e}")
            return Response(
                {"detail": f"Error retrieving users: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def post(self, request):
        """Create/attach a tenant user from source records using id_number + DOB + account_type."""
        # Ensure we're in a tenant context
        if connection.schema_name == 'public':
            return Response(
                {"detail": "This endpoint must be accessed from a tenant context (with x-tenant header)"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Capture tenant schema name BEFORE switching to public schema
        tenant_schema_name = connection.schema_name
        request_data = request.data.copy()
        request_data['account_type'] = request_data.get('account_type', '').lower()  # Normalize account_type to lowercase

        lookup_serializer = UserRecreateSerializer(data=request_data)
        if not lookup_serializer.is_valid():
            return Response(lookup_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        account_type = lookup_serializer.validated_data['account_type']
        id_number = lookup_serializer.validated_data['id_number']
        date_of_birth = lookup_serializer.validated_data['date_of_birth']
        notify_user = lookup_serializer.validated_data.get('notify_user', True)

        def resolve_role() -> str:
            if account_type == UserAccountType.STUDENT:
                return Roles.STUDENT
            if account_type == UserAccountType.PARENT:
                return Roles.PARENT
            if account_type == UserAccountType.STAFF:
                return Roles.TEACHER
            return Roles.VIEWER

        source_first_name = ""
        source_last_name = ""
        source_gender = "male"
        source_email = None
        source_record = None
        student_for_parent = None

        request_data = request.data.copy()

        try:
            if account_type == UserAccountType.STUDENT:
                from students.models import Student
                source_record = Student.objects.filter(
                    id_number=id_number,
                    date_of_birth=date_of_birth,
                ).first()
                if source_record:
                    source_first_name = source_record.first_name or ""
                    source_last_name = source_record.last_name or ""
                    source_gender = source_record.gender or "male"
                    source_email = source_record.email

            elif account_type == UserAccountType.STAFF:
                from staff.models import Staff
                source_record = Staff.objects.filter(
                    id_number=id_number,
                    date_of_birth=date_of_birth,
                ).first()
                if not source_record:
                        # In public schema, hr tenant tables may not exist.
                        if "employee" in connection.introspection.table_names():
                            from hr.models import Employee

                            source_record = Employee.objects.filter(
                                id_number=id_number,
                                date_of_birth=date_of_birth,
                            ).first()
                if source_record:
                    source_first_name = source_record.first_name or ""
                    source_last_name = source_record.last_name or ""
                    source_gender = source_record.gender or "male"
                    source_email = source_record.email

            elif account_type == UserAccountType.PARENT:
                from students.models import Student
                student_for_parent = Student.objects.filter(
                    id_number=id_number,
                    date_of_birth=date_of_birth,
                ).first()
                if student_for_parent:
                    source_record = student_for_parent.guardians.filter(is_primary=True).first() or student_for_parent.guardians.first()
                    if source_record:
                        source_first_name = source_record.first_name or ""
                        source_last_name = source_record.last_name or ""
                        source_email = source_record.email

        except Exception as e:
            return Response(
                {"detail": f"Error resolving source record: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        if not source_record:
            return Response(
                {
                    "detail": (
                        f"No {account_type} record found for id_number={id_number} "
                        f"and date_of_birth={date_of_birth}"
                    )
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        with schema_context('public'):
            existing_user = User.objects.filter(id_number=id_number).first()

            if existing_user:
                user = existing_user
                created = False
            else:
                email = source_email or f"{account_type}.{id_number}@local.user"
                if User.objects.filter(email=email).exists():
                    email = f"{account_type}.{id_number}@local.user"

                # Default username to id_number, allow override via request data
                username = request_data.get('username') or build_unique_username(str(id_number))
                user_data = {
                    'username': username,
                    'id_number': id_number,
                    'email': email,
                    'first_name': source_first_name,
                    'last_name': source_last_name,
                    'gender': source_gender,
                    'account_type': account_type,
                    'role': resolve_role(),
                    'is_active': True,
                }

                create_serializer = UserCreateSerializer(data=user_data)
                if not create_serializer.is_valid():
                    return Response(create_serializer.errors, status=status.HTTP_400_BAD_REQUEST)
                user = create_serializer.save()
                created = True

            try:
                from core.models import Tenant
                tenant = Tenant.objects.get(schema_name=tenant_schema_name)
                is_staff = account_type == UserAccountType.STAFF
                tenant.add_user(user, is_staff=is_staff, is_superuser=False)
            except Exception as e:
                # If user is already added, continue with success payload
                if "already" not in str(e).lower() and "exists" not in str(e).lower():
                    return Response(
                        {"detail": f"User resolved but tenant assignment failed: {str(e)}"},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    )

            if created and notify_user:
                from common.email_service import send_account_created_email
                from users.utils import build_frontend_url

                login_url = build_frontend_url(tenant_schema_name, "/login")
                email_sent = send_account_created_email(
                    user=user,
                    temporary_password=str(id_number),
                    login_url=login_url,
                    school=tenant,
                )
                if not email_sent:
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.warning(
                        "Account-created email could not be sent to user %s",
                        user.username,
                    )

            try:
                if account_type == UserAccountType.STUDENT:
                    source_record.user_account_id_number = user.id_number
                    source_record.save(update_fields=['user_account_id_number'])
                elif account_type == UserAccountType.STAFF:
                    source_record.user_account_id_number = user.id_number
                    source_record.save(update_fields=['user_account_id_number'])
            except Exception:
                pass

            response_serializer = UserSerializer(user, context={'request': request})
            source_summary = {
                "account_type": account_type,
                "source_id": str(getattr(source_record, 'id', '')),
                "first_name": getattr(source_record, 'first_name', None),
                "last_name": getattr(source_record, 'last_name', None),
                "email": getattr(source_record, 'email', None),
                "matched_student_id": str(student_for_parent.id) if student_for_parent else None,
            }

            return Response(
                {
                    "detail": "Tenant user created successfully" if created else "Tenant user already exists; attached to tenant",
                    "user": response_serializer.data,
                    "source": source_summary,
                },
                status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
            )


class GlobalUserCreateView(APIView):
    """
    Create a user in the public schema only (no tenant membership).
    
    This endpoint creates a user that exists globally but is not assigned to any tenant.
    Use the TenantUserCreateView to create a user and add them to a tenant.

    Username defaults to id_number if not provided. Users can change their username later.
    Password defaults to id_number with is_default_password=True flag.
    
    POST /api/v1/auth/users/global/
    {
        "id_number": "123456",
        "email": "student@example.com",
        "first_name": "John",
        "last_name": "Doe",
        "gender": "M",
        "account_type": "STUDENT",
        "role": "STUDENT",
        "username": "student01"  # Optional - defaults to id_number
    }
    
    Response:
    HTTP 201 Created
    {
        "id": 1,
        "username": "123456",  # Auto-generated from id_number if not provided
        "id_number": "123456",
        "email": "student@example.com",
        ...
        "is_default_password": true
    }
    """
    permission_classes = [UserAccessPolicy]
    
    def post(self, request):
        """Create a global user (public schema only)."""
        with schema_context('public'):
            # Default username to id_number if not provided
            data = request.data.copy()
            if not data.get('username') and data.get('id_number'):
                data['username'] = build_unique_username(str(data['id_number']))
            
            serializer = UserCreateSerializer(data=data)
            if serializer.is_valid():
                user = serializer.save()
                response_serializer = UserSerializer(user, context={'request': request})
                return Response(response_serializer.data, status=status.HTTP_201_CREATED)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)




class UserDetailView(APIView):
    """
    Retrieve, update, or delete a specific user by id_number.
    
    GET /api/v1/auth/users/{id_number}/
    Returns user details
    
    PUT /api/v1/auth/users/{id_number}/
    {
        "first_name": "Updated Name",
        "email": "updated@example.com",
        ...
    }
    
    DELETE /api/v1/auth/users/{id_number}/
    Soft deletes by setting is_active=False (or hard deletes if specified)
    """
    permission_classes = [UserAccessPolicy]
    
    def get(self, request, id_number):
        """Retrieve a user by id_number."""
        with schema_context('public'):
            try:
                user = User.objects.get(id_number=id_number)
                serializer = UserSerializer(user, context={'request': request})
                return Response(serializer.data, status=status.HTTP_200_OK)
            except User.DoesNotExist:
                return Response(
                    {"detail": f"User with id_number {id_number} not found"},
                    status=status.HTTP_404_NOT_FOUND
                )
    
    def put(self, request, id_number):
        """Update a user."""
        with schema_context('public'):
            try:
                user = User.objects.get(id_number=id_number)
                serializer = UserUpdateSerializer(user, data=request.data, partial=True)
                if serializer.is_valid():
                    serializer.save()
                    response_serializer = UserSerializer(user, context={'request': request})
                    return Response(response_serializer.data, status=status.HTTP_200_OK)
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
            except User.DoesNotExist:
                return Response(
                    {"detail": f"User with id_number {id_number} not found"},
                    status=status.HTTP_404_NOT_FOUND
                )
    
    def delete(self, request, id_number):
        """Delete a user (soft delete by default, hard delete if ?hard=true)."""
        with schema_context('public'):
            try:
                user = User.objects.get(id_number=id_number)
                
                # Check if hard delete requested
                hard_delete = request.query_params.get('hard', 'false').lower() == 'true'
                
                if hard_delete:
                    # Hard delete: remove from all tenants first, then delete user
                    from core.models import Tenant
                    from tenant_users.permissions.models import UserTenantPermissions
                    
                    # Get all tenants the user belongs to
                    tenant_permissions = UserTenantPermissions.objects.filter(profile=user)
                    for perm in tenant_permissions:
                        try:
                            # Get tenant and remove user
                            tenant = Tenant.objects.get(schema_name=perm.tenant.schema_name)
                            tenant.remove_user(user)
                        except Exception as e:
                            import logging
                            logger = logging.getLogger(__name__)
                            logger.warning(f"Failed to remove user from tenant {perm.tenant.schema_name}: {e}")
                    
                    username = user.username
                    # tenant_users overrides delete() to block accidental deletion;
                    # use force_drop=True for an actual hard delete after unlinking tenants.
                    user.delete(force_drop=True)
                    return Response(
                        {"detail": f"User {username} permanently deleted"},
                        status=status.HTTP_204_NO_CONTENT
                    )
                else:
                    # Soft delete: use the manager's delete_user() which unlinks tenants
                    # and sets is_active=False (per django-tenant-users contract).
                    User.objects.delete_user(user)
                    return Response(
                        {"detail": f"User {user.username} deactivated"},
                        status=status.HTTP_200_OK
                    )
                    
            except User.DoesNotExist:
                return Response(
                    {"detail": f"User with id_number {id_number} not found"},
                    status=status.HTTP_404_NOT_FOUND
                )


class PasswordChangeView(APIView):
    """
    Change password for a user (requires current password).
    
    POST /api/v1/auth/users/{id_number}/password/change/
    {
        "current_password": "old_password",
        "new_password": "new_password",
        "confirm_password": "new_password"
    }
    
    Response:
    {
        "detail": "Password changed successfully",
        "is_default_password": false
    }
    """
    permission_classes = [UserAccessPolicy]
    
    def post(self, request, id_number):
        """Change user password."""
        with schema_context('public'):
            try:
                user = User.objects.get(id_number=id_number)
                
                serializer = PasswordChangeSerializer(data=request.data)
                if serializer.is_valid():
                    # Validate current password
                    if not user.check_password(serializer.validated_data['current_password']):
                        return Response(
                            {"detail": "Current password is incorrect"},
                            status=status.HTTP_400_BAD_REQUEST
                        )
                    
                    # Set new password
                    user.set_password(serializer.validated_data['new_password'])
                    user.is_default_password = False
                    from django.utils import timezone
                    user.last_password_updated = timezone.now()
                    user.save()

                    from common.audit_utils import log_auth_event
                    log_auth_event(request, user, "password_changed")
                    
                    return Response(
                        {
                            "detail": "Password changed successfully",
                            "is_default_password": False
                        },
                        status=status.HTTP_200_OK
                    )
                
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
                
            except User.DoesNotExist:
                return Response(
                    {"detail": f"User with id_number {id_number} not found"},
                    status=status.HTTP_404_NOT_FOUND
                )


class PasswordResetRequestView(APIView):
    """
    Request a password reset (forgot password).

    POST /api/v1/auth/password/forgot/
    {
        "user_identifier": "username_or_email_or_id_number"
    }

    Always returns 200 to avoid leaking whether an account exists.
    When a matching user with a valid email is found, a reset link is sent.
    """
    permission_classes = []  # Public endpoint
    authentication_classes = []

    def post(self, request):
        """Request password reset."""
        import logging
        from django.contrib.auth.tokens import PasswordResetTokenGenerator
        from django.core.cache import cache
        from django.utils.encoding import force_bytes
        from django.utils.http import urlsafe_base64_encode

        from common.email_service import send_password_reset_email
        from users.utils import build_password_reset_url

        logger = logging.getLogger(__name__)

        # Generic response – never reveal whether the account exists
        _safe_response = Response(
            {"detail": "If a user with that identifier exists, a password reset link has been sent to their email."},
            status=status.HTTP_200_OK,
        )

        serializer = PasswordForgotSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        user_identifier = serializer.validated_data['user_identifier']

        with schema_context('public'):
            try:
                user = User.objects.filter(
                    Q(username=user_identifier) |
                    Q(email=user_identifier) |
                    Q(id_number=user_identifier)
                ).first()

                if not user:
                    return _safe_response

                if not user.email:
                    logger.warning(
                        "Password reset requested for user %s but no email address is set",
                        user.username,
                    )
                    return _safe_response

                if not user.is_active:
                    return _safe_response

                cooldown_seconds = max(
                    1,
                    int(getattr(settings, "PASSWORD_RESET_REQUEST_COOLDOWN_SECONDS", 60)),
                )
                tenant_schema = getattr(getattr(request, "tenant", None), "schema_name", "public")
                rate_limit_key = f"pwd-reset-cooldown:{tenant_schema}:{user.id}"

                # cache.add is atomic: it returns False when key already exists.
                if not cache.add(rate_limit_key, "1", timeout=cooldown_seconds):
                    logger.info(
                        "Password reset request throttled for user %s (%ss cooldown)",
                        user.username,
                        cooldown_seconds,
                    )
                    return _safe_response

                # Generate a secure, single-use token
                token_generator = PasswordResetTokenGenerator()
                uid = urlsafe_base64_encode(force_bytes(user.pk))
                token = token_generator.make_token(user)

                # Use tenant workspace if available (for subdomain URL building)
                school_workspace = getattr(request, 'tenant', None)
                if school_workspace and hasattr(school_workspace, 'schema_name'):
                    school_workspace = school_workspace.schema_name
                else:
                    school_workspace = None

                reset_url = build_password_reset_url(school_workspace, uid, token)

                if settings.DEBUG:
                    logger.debug("Password reset URL for %s: %s", user.username, reset_url)

                sent = send_password_reset_email(user, reset_url)
                if not sent:
                    logger.error("Failed to send password reset email to user %s", user.username)

                from common.audit_utils import log_auth_event
                log_auth_event(request, user, "password_reset_requested")

                return _safe_response

            except Exception as exc:
                logger.error("Error processing password reset request: %s", exc)
                return Response(
                    {"detail": "An error occurred while processing your request."},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )


class PasswordResetConfirmView(APIView):
    """
    Confirm password reset with token.

    POST /api/v1/auth/password/reset/
    {
        "uid":          "base64-encoded user PK",   ← preferred
        "token":        "reset-token",
        "new_password": "NewSecurePass1"
    }

    The uid/token pair comes from the reset URL sent by PasswordResetRequestView.
    """
    permission_classes = []  # Public endpoint
    authentication_classes = []

    def post(self, request):
        """Confirm password reset."""
        import re
        import logging
        from django.contrib.auth.tokens import PasswordResetTokenGenerator
        from django.utils import timezone
        from django.utils.encoding import force_str
        from django.utils.http import urlsafe_base64_decode
        from common.email_service import send_password_reset_success_email
        from users.utils import build_frontend_url

        logger = logging.getLogger(__name__)

        uid_b64 = request.data.get('uid') or request.data.get('uidb64')
        token = request.data.get('token')
        new_password = request.data.get('new_password') or request.data.get('password')

        if not uid_b64 or not token or not new_password:
            return Response(
                {"detail": "uid, token, and new_password are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Decode uid
        try:
            user_pk = force_str(urlsafe_base64_decode(uid_b64))
        except (TypeError, ValueError, OverflowError):
            return Response(
                {"detail": "Invalid reset link."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with schema_context('public'):
            try:
                user = User.objects.get(pk=user_pk)
            except User.DoesNotExist:
                return Response(
                    {"detail": "Invalid reset link."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Validate token
            token_generator = PasswordResetTokenGenerator()
            if not token_generator.check_token(user, token):
                return Response(
                    {"detail": "This reset link is invalid or has already been used."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Enforce basic password strength
            if len(new_password) < 8:
                return Response(
                    {"detail": "Password must be at least 8 characters long."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if not re.search(r'[a-zA-Z]', new_password):
                return Response(
                    {"detail": "Password must contain at least one letter."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if not re.search(r'[0-9]', new_password):
                return Response(
                    {"detail": "Password must contain at least one number."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            user.set_password(new_password)
            user.is_default_password = False
            user.last_password_updated = timezone.now()
            user.save(update_fields=["password", "is_default_password", "last_password_updated"])

            from common.audit_utils import log_auth_event
            log_auth_event(request, user, "password_reset")

            school = getattr(request, 'tenant', None)
            school_workspace = getattr(school, 'schema_name', None) if school else None
            login_url = build_frontend_url(school_workspace, "/login")

            success_email_sent = send_password_reset_success_email(
                user,
                login_url=login_url,
                school=school,
            )
            if not success_email_sent:
                logger.warning("Password reset success email could not be sent to user %s", user.username)

            logger.info("Password reset confirmed for user %s", user.username)
            return Response(
                {"detail": "Your password has been reset successfully. You can now log in."},
                status=status.HTTP_200_OK,
            )


class UserRecreateView(APIView):
    """
    Create a user account from an existing Student/Staff/Parent source record.

    Automatically populates user profile from source data (Student, Staff, or Guardian record).
    Username defaults to id_number if not provided. Users can change their username later.
    Password defaults to id_number with is_default_password=True flag.

    Required lookup fields:
    - id_number: used to find Student/Staff/Guardian record
    - date_of_birth: used to match the specific record (Student/Staff must match exactly)
    - account_type: STUDENT, STAFF, or PARENT

    POST /api/v1/auth/users/recreate/
    {
        "account_type": "STUDENT",
        "id_number": "123456",
        "date_of_birth": "2012-05-14",
        "username": "john_doe"  # optional, defaults to id_number
    }

    For PARENT account_type, lookup is performed by finding Student with matching
    id_number + date_of_birth, then using the primary guardian (StudentGuardian) record.
    
    Returns:
    HTTP 201 Created - User created successfully
    HTTP 200 OK - User already exists (idempotent)
    HTTP 404 Not Found - No source record found matching id_number + date_of_birth
    
    Response body includes source_summary showing which record was used for population.
    """
    permission_classes = [UserAccessPolicy]

    @staticmethod
    def _resolve_role(account_type: str) -> str:
        if account_type == UserAccountType.STUDENT:
            return Roles.STUDENT
        if account_type == UserAccountType.PARENT:
            return Roles.PARENT
        if account_type == UserAccountType.STAFF:
            return Roles.TEACHER
        return Roles.VIEWER

    @staticmethod
    def _generate_unique_username(base_username: str) -> str:
        candidate = base_username
        index = 1
        while User.objects.filter(username=candidate).exists():
            candidate = f"{base_username}_{index}"
            index += 1
        return candidate

    @staticmethod
    def _generate_fallback_email(account_type: str, id_number: str) -> str:
        return f"{account_type}.{id_number}@local.user"

    @staticmethod
    def _build_source_summary(account_type: str, source_record, matched_student_id=None) -> dict:
        summary = {
            "account_type": account_type,
            "source_id": str(getattr(source_record, 'id', '')),
            "first_name": getattr(source_record, 'first_name', None),
            "last_name": getattr(source_record, 'last_name', None),
            "email": getattr(source_record, 'email', None),
        }

        if hasattr(source_record, 'id_number'):
            summary["id_number"] = getattr(source_record, 'id_number')

        if hasattr(source_record, 'date_of_birth'):
            summary["date_of_birth"] = getattr(source_record, 'date_of_birth')

        if matched_student_id is not None:
            summary["matched_student_id"] = str(matched_student_id)

        return summary
    
    def post(self, request):
        """Create user from Student/Staff/Parent record using id_number + DOB lookup."""
        serializer = UserRecreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        if connection.schema_name == 'public':
            return Response(
                {"detail": "This endpoint must be accessed from a tenant context (with x-tenant header)"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Capture tenant schema name BEFORE switching to public schema
        tenant_schema_name = connection.schema_name

        account_type = serializer.validated_data['account_type']
        id_number = serializer.validated_data['id_number']
        date_of_birth = serializer.validated_data['date_of_birth']

        source_first_name = ""
        source_last_name = ""
        source_gender = "male"
        source_email = None
        source_record = None
        matched_student_id = None

        try:
            if account_type == UserAccountType.STUDENT:
                from students.models import Student
                source_record = Student.objects.filter(
                    id_number=id_number,
                    date_of_birth=date_of_birth,
                ).first()

                if source_record:
                    source_first_name = source_record.first_name or ""
                    source_last_name = source_record.last_name or ""
                    source_gender = source_record.gender or "male"
                    source_email = source_record.email

            elif account_type == UserAccountType.STAFF:
                from staff.models import Staff
                source_record = Staff.objects.filter(
                    id_number=id_number,
                    date_of_birth=date_of_birth,
                ).first()

                if source_record:
                    source_first_name = source_record.first_name or ""
                    source_last_name = source_record.last_name or ""
                    source_gender = source_record.gender or "male"
                    source_email = source_record.email

            elif account_type == UserAccountType.PARENT:
                from students.models import Student
                student = Student.objects.filter(
                    id_number=id_number,
                    date_of_birth=date_of_birth,
                ).first()

                if student:
                    matched_student_id = student.id
                    source_record = student.guardians.filter(is_primary=True).first() or student.guardians.first()
                    if source_record:
                        source_first_name = source_record.first_name or ""
                        source_last_name = source_record.last_name or ""
                        source_email = source_record.email

        except Exception as exc:
            return Response(
                {"detail": f"Error retrieving source record: {str(exc)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        if not source_record:
            return Response(
                {
                    "detail": (
                        f"No {account_type} record found for id_number={id_number} "
                        f"and date_of_birth={date_of_birth}"
                    )
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        source_summary = self._build_source_summary(
            account_type=account_type,
            source_record=source_record,
            matched_student_id=matched_student_id,
        )

        with schema_context('public'):
            existing_user = User.objects.filter(id_number=id_number).first()
            if existing_user:
                try:
                    from core.models import Tenant
                    tenant = Tenant.objects.get(schema_name=tenant_schema_name)
                    is_staff = account_type == UserAccountType.STAFF
                    tenant.add_user(existing_user, is_staff=is_staff, is_superuser=False)
                except Exception as e:
                    if "already" not in str(e).lower() and "exists" not in str(e).lower():
                        return Response(
                            {"detail": f"User exists but tenant assignment failed: {str(e)}"},
                            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        )

                response_serializer = UserSerializer(existing_user, context={'request': request})
                return Response(
                    {
                        "detail": "User account already exists",
                        "user": response_serializer.data,
                        "source": source_summary,
                    },
                    status=status.HTTP_200_OK,
                )

            email = source_email or self._generate_fallback_email(account_type, id_number)
            if User.objects.filter(email=email).exists():
                email = self._generate_fallback_email(account_type, id_number)

            # Default username to id_number, allow override via request data
            username = self.request.data.get('username') or self._generate_unique_username(str(id_number))

            user_data = {
                'username': username,
                'id_number': id_number,
                'email': email,
                'first_name': source_first_name,
                'last_name': source_last_name,
                'gender': source_gender,
                'account_type': account_type,
                'role': self._resolve_role(account_type),
                'is_active': True,
            }

            create_serializer = UserCreateSerializer(data=user_data)
            if not create_serializer.is_valid():
                return Response(create_serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            user = create_serializer.save()

            try:
                from core.models import Tenant
                tenant = Tenant.objects.get(schema_name=tenant_schema_name)
                is_staff = account_type == UserAccountType.STAFF
                tenant.add_user(user, is_staff=is_staff, is_superuser=False)
            except Exception as e:
                if "already" not in str(e).lower() and "exists" not in str(e).lower():
                    return Response(
                        {"detail": f"User created but tenant assignment failed: {str(e)}"},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    )

            response_serializer = UserSerializer(user, context={'request': request})
            response_data = {
                "detail": "User account created successfully",
                "user": response_serializer.data,
                "source": source_summary,
            }

        # 🔥 CRITICAL FIX: Update source_record AFTER exiting public schema
        # so the student/staff record saves in the tenant schema, not public
        try:
            if account_type == UserAccountType.STUDENT:
                source_record.user_account_id_number = user.id_number
                source_record.save(update_fields=['user_account_id_number'])
            elif account_type == UserAccountType.STAFF:
                source_record.user_account_id_number = user.id_number
                source_record.save(update_fields=['user_account_id_number'])
            elif account_type == UserAccountType.PARENT:
                # For parents, source_record is StudentGuardian
                source_record.user_account_id_number = user.id_number
                source_record.save(update_fields=['user_account_id_number'])
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to update source_record user_account_id_number: {e}", exc_info=True)

        return Response(response_data, status=status.HTTP_201_CREATED)
