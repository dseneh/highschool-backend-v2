"""
ViewSet for user management with proper DRF action-based permissions.
Replaces APIView implementations for better permission integration.
"""
import logging

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework_simplejwt.authentication import JWTStatelessUserAuthentication
from rest_framework.pagination import PageNumberPagination
from django.db.models import Q
from django.db import connection
from django_tenants.utils import schema_context
from django.utils import timezone

from common.utils import get_object_by_uuid_or_fields
from users.models import User, SpecialPrivilege
from users.serializers import (
    UserSerializer,
    UserCreateSerializer,
    UserUpdateSerializer,
    PasswordChangeSerializer,
    PasswordForgotSerializer,
    UserRecreateSerializer,
)
from users.access_policies import UserAccessPolicy
from users.access_policies.permissions import PRIVILEGES
from common.status import UserAccountType, Roles
from django.conf import settings


logger = logging.getLogger(__name__)


class UserPagination(PageNumberPagination):
    """Pagination for user list."""
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


class UserViewSet(viewsets.ModelViewSet):
    """
    ViewSet for user management with proper action-based permissions.
    
    Actions:
    - list: GET /users/ - List all users in current tenant
    - retrieve: GET /users/{id_number}/ - Get user details
    - create: POST /users/ - Create/attach user to tenant  
    - update: PUT /users/{id_number}/ - Update user
    - partial_update: PATCH /users/{id_number}/ - Partial update
    - destroy: DELETE /users/{id_number}/ - Delete user
    - current: GET /users/current/ - Get current authenticated user
    - password_change: POST /users/{id_number}/password/change/ - Change password
    - recreate: POST /users/recreate/ - Create user from source record
    - password_reset_request: POST /password/forgot/ - Request password reset
    - password_reset_confirm: POST /password/reset/ - Confirm password reset
    """
    permission_classes = [UserAccessPolicy]
    pagination_class = UserPagination
    lookup_field = 'id_number'
    lookup_value_regex = '[^/]+'  # Allow any characters in id_number

    @staticmethod
    def _get_linked_user_id_numbers():
        linked_id_numbers = set()

        from staff.models import Staff
        from students.models.guardian import StudentGuardian
        from students.models.student import Student

        linked_id_numbers.update(
            Staff.objects.exclude(user_account_id_number__isnull=True)
            .exclude(user_account_id_number='')
            .values_list('user_account_id_number', flat=True)
        )
        linked_id_numbers.update(
            Student.objects.exclude(user_account_id_number__isnull=True)
            .exclude(user_account_id_number='')
            .values_list('user_account_id_number', flat=True)
        )
        linked_id_numbers.update(
            StudentGuardian.objects.exclude(user_account_id_number__isnull=True)
            .exclude(user_account_id_number='')
            .values_list('user_account_id_number', flat=True)
        )

        return linked_id_numbers

    def _apply_user_filters(self, queryset):
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                Q(first_name__icontains=search) |
                Q(last_name__icontains=search) |
                Q(username__icontains=search) |
                Q(email__icontains=search) |
                Q(id_number__icontains=search)
            )

        roles = self.request.query_params.getlist('role')
        if roles:
            queryset = queryset.filter(role__in=roles)

        account_types = self.request.query_params.getlist('account_type')
        if account_types:
            queryset = queryset.filter(account_type__in=account_types)

        for field in ['is_active', 'is_staff', 'is_superuser', 'is_default_password']:
            value = self.request.query_params.get(field)
            if value is not None:
                bool_value = value.lower() in ['true', '1', 'yes']
                queryset = queryset.filter(**{field: bool_value})

        ordering = self.request.query_params.get('ordering', '-id')
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
            return queryset.order_by(ordering)
        return queryset.order_by('-id')
    
    def get_queryset(self):
        """Get users based on context (tenant or global)."""
        # For 'current' action, return empty queryset (handled in action)
        if self.action == 'current':
            return User.objects.none()
        
        # For tenant context, get users with permissions in current tenant
        if connection.schema_name != 'public':
            try:
                from tenant_users.permissions.models import UserTenantPermissions
                permission_user_ids = set(
                    UserTenantPermissions.objects.values_list('profile_id', flat=True).distinct()
                )
                linked_user_id_numbers = self._get_linked_user_id_numbers()
                
                with schema_context('public'):
                    queryset = User.objects.filter(
                        Q(id__in=list(permission_user_ids)) |
                        Q(id_number__in=list(linked_user_id_numbers))
                    ).distinct()
                    return self._apply_user_filters(queryset)
            except Exception as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"Error getting tenant users: {e}")
                return User.objects.none()
        
        # For global context, return all users
        with schema_context('public'):
            return self._apply_user_filters(User.objects.all())
    
    def get_serializer_class(self):
        """Return appropriate serializer based on action."""
        if self.action == 'create':
            return UserCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return UserUpdateSerializer
        return UserSerializer

    def destroy(self, request, *args, **kwargs):
        """Delete a user.

        Soft delete by default (?hard=false): uses User.objects.delete_user()
        which unlinks tenants and sets is_active=False (django-tenant-users contract).

        Hard delete (?hard=true): unlinks the user from every tenant, then calls
        delete(force_drop=True) — the documented escape hatch in tenant_users.
        """
        user = self.get_object()
        hard_delete = request.query_params.get('hard', 'false').lower() == 'true'

        with schema_context('public'):
            if hard_delete:
                from core.models import Tenant
                from tenant_users.permissions.models import UserTenantPermissions

                tenant_permissions = UserTenantPermissions.objects.filter(profile=user)
                for perm in tenant_permissions:
                    try:
                        tenant = Tenant.objects.get(schema_name=perm.tenant.schema_name)
                        tenant.remove_user(user)
                    except Exception as e:
                        import logging
                        logging.getLogger(__name__).warning(
                            f"Failed to remove user from tenant {perm.tenant.schema_name}: {e}"
                        )

                username = user.username
                # Use a raw delete in public schema to avoid Django relation collection
                # across tenant-scoped models (e.g., academic_year) that do not exist
                # in public schema.
                User.objects.filter(pk=user.pk)._raw_delete(User.objects.db)
                return Response(
                    {"detail": f"User {username} permanently deleted"},
                    status=status.HTTP_204_NO_CONTENT,
                )

            User.objects.delete_user(user)
            return Response(
                {"detail": f"User {user.username} deactivated"},
                status=status.HTTP_200_OK,
            )

    def get_object(self):
        """Get user by id_number."""
        lookup_value = self.kwargs.get(self.lookup_field)
        
        with schema_context('public'):
            try:
                return get_object_by_uuid_or_fields(User, lookup_value, fields=['id_number']
                )
            except User.DoesNotExist:
                from rest_framework.exceptions import NotFound
                raise NotFound(f"User with id_number '{lookup_value}' not found")
    
    def list(self, request, *args, **kwargs):
        """List users in current tenant."""
        scope = str(request.query_params.get('scope') or '').strip().lower()
        if connection.schema_name == 'public' and scope not in {'global', 'admin'}:
            return Response(
                {"detail": "This endpoint must be accessed from a tenant context (with x-tenant header)"},
                status=status.HTTP_400_BAD_REQUEST
            )
        return super().list(request, *args, **kwargs)

    def _sync_email_to_linked_record(self, user: User, email: str) -> None:
        """Sync user email to linked student/staff record in the current tenant schema."""
        if connection.schema_name == 'public':
            return

        normalized_email = (email or "").strip()
        if not normalized_email:
            return

        if user.account_type == UserAccountType.STUDENT:
            from students.models import Student

            student = Student.objects.filter(user_account_id_number=user.id_number).first()
            if not student:
                student = Student.objects.filter(id_number=user.id_number).first()
            if student and student.email != normalized_email:
                student.email = normalized_email
                student.save(update_fields=['email'])
            return

        if user.account_type == UserAccountType.STAFF:
            from staff.models import Staff

            staff = Staff.objects.filter(user_account_id_number=user.id_number).first()
            if not staff:
                staff = Staff.objects.filter(id_number=user.id_number).first()
            if staff and staff.email != normalized_email:
                staff.email = normalized_email
                staff.save(update_fields=['email'])
                return

            # Fallback for HR employee records that are not mirrored in staff table.
            from hr.models import Employee

            employee = Employee.objects.filter(user_account_id_number=user.id_number).first()
            if not employee:
                employee = Employee.objects.filter(id_number=user.id_number).first()
            if employee and employee.email != normalized_email:
                employee.email = normalized_email
                employee.save(update_fields=['email'])

    def update(self, request, *args, **kwargs):
        """Update user and sync email to linked tenant source record when relevant."""
        partial = kwargs.pop('partial', False)
        user = self.get_object()

        old_email = user.email
        serializer = self.get_serializer(user, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)

        new_email = serializer.validated_data.get('email')
        if new_email and new_email != old_email:
            try:
                self._sync_email_to_linked_record(user, new_email)
            except Exception as exc:
                logger.warning(
                    "Failed to sync email for user %s to source record: %s",
                    user.id_number,
                    exc,
                )

        response_serializer = UserSerializer(user, context={'request': request})
        return Response(response_serializer.data, status=status.HTTP_200_OK)

    def partial_update(self, request, *args, **kwargs):
        kwargs['partial'] = True
        return self.update(request, *args, **kwargs)
    
    def create(self, request, *args, **kwargs):
        """Create/attach user to current tenant from source record."""
        if connection.schema_name == 'public':
            return Response(
                {"detail": "This endpoint must be accessed from a tenant context (with x-tenant header)"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Capture tenant schema name
        tenant_schema_name = connection.schema_name
        request_data = request.data.copy()
        request_data['account_type'] = request_data.get('account_type', '').lower()
        
        lookup_serializer = UserRecreateSerializer(data=request_data)
        if not lookup_serializer.is_valid():
            return Response(lookup_serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        account_type = lookup_serializer.validated_data['account_type']
        id_number = lookup_serializer.validated_data['id_number']
        date_of_birth = lookup_serializer.validated_data['date_of_birth']
        notify_user = lookup_serializer.validated_data.get('notify_user', True)
        
        # Lookup source record
        source_record = None
        matched_student_id = None
        
        try:
            if account_type == UserAccountType.STUDENT:
                from students.models import Student
                source_record = Student.objects.filter(
                    id_number=id_number,
                    date_of_birth=date_of_birth,
                ).first()
            
            elif account_type == UserAccountType.STAFF:
                from staff.models import Staff
                source_record = Staff.objects.filter(
                    id_number=id_number,
                    date_of_birth=date_of_birth,
                ).first()
                if not source_record:
                    from hr.models import Employee

                    source_record = Employee.objects.filter(
                        id_number=id_number,
                        date_of_birth=date_of_birth,
                    ).first()
            
            elif account_type == UserAccountType.PARENT:
                from students.models import Student
                student = Student.objects.filter(
                    id_number=id_number,
                    date_of_birth=date_of_birth,
                ).first()
                
                if student:
                    matched_student_id = student.id
                    source_record = student.guardians.filter(is_primary=True).first() or student.guardians.first()
        
        except Exception as exc:
            return Response(
                {"detail": f"Error retrieving source record: {str(exc)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        
        if not source_record:
            return Response(
                {"detail": f"No {account_type} record found for id_number={id_number} and date_of_birth={date_of_birth}"},
                status=status.HTTP_404_NOT_FOUND,
            )
        
        # Extract data from source record
        source_first_name = getattr(source_record, 'first_name', '')
        source_last_name = getattr(source_record, 'last_name', '')
        source_gender = getattr(source_record, 'gender', 'male')
        source_email = getattr(source_record, 'email', None)
        
        # Check if user already exists
        with schema_context('public'):
            existing_user = User.objects.filter(id_number=id_number).first()
            if existing_user:
                # Add user to tenant
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
                
                serializer = UserSerializer(existing_user, context={'request': request})
                return Response(
                    {"detail": "User account already exists", "user": serializer.data},
                    status=status.HTTP_200_OK,
                )
            
            # Generate email and username
            email = source_email or f"{account_type}.{id_number}@local.user"
            if User.objects.filter(email=email).exists():
                email = f"{account_type}.{id_number}@local.user"
            
            username = request.data.get('username') or self._generate_unique_username(str(id_number))
            
            # Determine role
            if account_type == UserAccountType.STUDENT:
                role = Roles.STUDENT
            elif account_type == UserAccountType.PARENT:
                role = Roles.PARENT
            elif account_type == UserAccountType.STAFF:
                role = Roles.TEACHER
            else:
                role = Roles.VIEWER
            
            # Create user
            user_data = {
                'username': username,
                'id_number': id_number,
                'email': email,
                'first_name': source_first_name,
                'last_name': source_last_name,
                'gender': source_gender,
                'account_type': account_type,
                'role': role,
                'is_active': True,
            }
            
            create_serializer = UserCreateSerializer(data=user_data)
            if not create_serializer.is_valid():
                return Response(create_serializer.errors, status=status.HTTP_400_BAD_REQUEST)
            
            user = create_serializer.save()
            
            # Add user to tenant
            tenant = None
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

            if notify_user:
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
                    logger.warning(
                        "Account-created email could not be sent to user %s",
                        user.username,
                    )
        
        # Update source record with user account id_number
        try:
            source_record.user_account_id_number = user.id_number
            source_record.save(update_fields=['user_account_id_number'])
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to update source_record user_account_id_number: {e}", exc_info=True)
        
        serializer = UserSerializer(user, context={'request': request})
        return Response(
            {"detail": "User account created successfully", "user": serializer.data},
            status=status.HTTP_201_CREATED,
        )
    
    @staticmethod
    def _generate_unique_username(base_username: str) -> str:
        """Generate unique username by appending numeric suffix if needed."""
        candidate = base_username
        index = 1
        while User.objects.filter(username=candidate).exists():
            candidate = f"{base_username}_{index}"
            index += 1
        return candidate

    @action(detail=False, methods=['get'],
            permission_classes=[UserAccessPolicy], url_path='privileges')
    def privileges_catalog(self, request):
        """Return all assignable special privilege definitions."""
        data = [
            {
                "code": privilege.code,
                "label": privilege.label,
                "description": privilege.description,
            }
            for privilege in sorted(PRIVILEGES.values(), key=lambda item: item.code)
        ]
        return Response(data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get', 'put'],
            permission_classes=[UserAccessPolicy], url_path='special-privileges')
    def special_privileges(self, request, id_number=None):
        """Get or replace user-specific special privilege assignments."""
        user = self.get_object()

        if request.method == 'GET':
            assigned_codes = list(
                SpecialPrivilege.objects.filter(user=user)
                .values_list('code', flat=True)
            )
            return Response(
                {
                    "user_id_number": user.id_number,
                    "assigned_codes": sorted(set(assigned_codes)),
                    "effective_codes": user.get_privileges(),
                },
                status=status.HTTP_200_OK,
            )

        raw_codes = request.data.get('codes', [])
        if not isinstance(raw_codes, list):
            return Response(
                {"detail": "codes must be an array of privilege codes."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        requested_codes = sorted({str(code).strip().upper() for code in raw_codes if str(code).strip()})
        invalid_codes = [code for code in requested_codes if code not in PRIVILEGES]
        if invalid_codes:
            return Response(
                {"detail": "Invalid privilege code(s).", "invalid_codes": invalid_codes},
                status=status.HTTP_400_BAD_REQUEST,
            )

        current_codes = set(
            SpecialPrivilege.objects.filter(user=user).values_list('code', flat=True)
        )
        requested_set = set(requested_codes)
        to_add = requested_set - current_codes
        to_remove = current_codes - requested_set

        actor = request.user
        unmanaged = [
            code for code in sorted(to_add | to_remove)
            if not actor.can_grant_privilege(code)
        ]
        if unmanaged:
            return Response(
                {
                    "detail": "You are not allowed to grant or revoke one or more privileges.",
                    "forbidden_codes": unmanaged,
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        for code in to_add:
            SpecialPrivilege.objects.create(
                user=user,
                code=code,
                granted_by=actor,
            )

        if to_remove:
            SpecialPrivilege.objects.filter(user=user, code__in=list(to_remove)).delete()

        assigned_codes = list(
            SpecialPrivilege.objects.filter(user=user).values_list('code', flat=True)
        )
        return Response(
            {
                "detail": "Special privileges updated successfully.",
                "user_id_number": user.id_number,
                "assigned_codes": sorted(set(assigned_codes)),
                "effective_codes": user.get_privileges(),
            },
            status=status.HTTP_200_OK,
        )
    
    @action(detail=False, methods=['get'], 
            authentication_classes=[JWTStatelessUserAuthentication],
            permission_classes=[UserAccessPolicy])
    def current(self, request):
        """
        Get current authenticated user from JWT token.
        
        GET /users/current/
        """
        serializer = UserSerializer(request.user, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    @action(detail=True, methods=['post'], 
            permission_classes=[UserAccessPolicy], url_path='password/change')
    def password_change(self, request, id_number=None):
        """
        Change user password (requires current password).
        
        POST /users/{id_number}/password/change/
        {
            "current_password": "old_password",
            "new_password": "new_password",
            "confirm_password": "new_password"
        }
        """
        user = self.get_object()
        
        serializer = PasswordChangeSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        # Validate current password
        if not user.check_password(serializer.validated_data['current_password']):
            return Response(
                {"detail": "Current password is incorrect"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Set new password
        with schema_context('public'):
            user.set_password(serializer.validated_data['new_password'])
            user.is_default_password = False
            user.last_password_updated = timezone.now()
            user.save()

        from common.audit_utils import log_auth_event
        log_auth_event(request, user, "password_changed")
        
        # Return updated user payload (same format as login)
        user_serializer = UserSerializer(user, context={'request': request})
        return Response(
            {
                "detail": "Password changed successfully",
                "user": user_serializer.data,
                "is_default_password": False
            },
            status=status.HTTP_200_OK
        )

    @action(detail=True, methods=['post'],
            permission_classes=[UserAccessPolicy], url_path='password/default')
    def password_default(self, request, id_number=None):
        """Allow admins to reset any account password to the default (id_number)."""
        user = self.get_object()

        with schema_context('public'):
            user.set_password(user.id_number)
            user.is_default_password = True
            user.last_password_updated = None
            user.save(update_fields=["password", "is_default_password", "last_password_updated"])

        from common.audit_utils import log_auth_event
        log_auth_event(request, user, "password_reset_to_default")

        return Response(
            {
                "detail": f"Password reset to default for {user.username}",
                "is_default_password": True,
            },
            status=status.HTTP_200_OK,
        )
    
    @action(detail=False, methods=['post'],
            permission_classes=[UserAccessPolicy])
    def recreate(self, request):
        """
        Create/attach user from source record (Student/Staff/Parent).
        
        POST /users/recreate/
        {
            "account_type": "STUDENT",
            "id_number": "123456",
            "date_of_birth": "2005-01-15",
            "username": "john_doe"  # optional
        }
        """
        # This is essentially the same as create, so redirect
        return self.create(request)
    
    @action(detail=False, methods=['post'],
            permission_classes=[AllowAny],
            url_path='password/forgot')
    def password_reset_request(self, request):
        """
        Request password reset (public endpoint).

        POST /users/password/forgot/
        {
            "user_identifier": "username_or_email_or_id_number"
        }

        Always returns 200 to avoid leaking whether an account exists.
        """
        import logging
        from django.contrib.auth.tokens import PasswordResetTokenGenerator
        from django.utils.encoding import force_bytes
        from django.utils.http import urlsafe_base64_encode

        from common.email_service import send_password_reset_email
        from users.utils import build_password_reset_url

        logger = logging.getLogger(__name__)

        serializer = PasswordForgotSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        user_identifier = serializer.validated_data['user_identifier']

        safe_response = Response(
            {"detail": "If a user with that identifier exists, a password reset link has been sent to their email."},
            status=status.HTTP_200_OK,
        )

        with schema_context('public'):
            user = User.objects.filter(
                Q(username=user_identifier) |
                Q(email=user_identifier) |
                Q(id_number=user_identifier)
            ).first()

            if not user or not user.is_active or not user.email:
                return safe_response

            token_generator = PasswordResetTokenGenerator()
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = token_generator.make_token(user)

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

            return safe_response
