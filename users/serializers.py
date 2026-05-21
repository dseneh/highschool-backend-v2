"""
Serializers for authentication
"""
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.contrib.auth import authenticate, get_user_model
from django.conf import settings
from django.utils import timezone

from common.status import Roles, UserAccountType

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    """
    User serializer for authentication responses.
    
    Includes basic user information needed by the frontend after login.
    Excludes sensitive fields like password.
    
    For parents, includes tenants list to show which tenants they have access to.
    """
    
    # Add tenants list for users who belong to multiple tenants (especially parents)
    tenants = serializers.SerializerMethodField()
    # Add flag to identify the currently logged-in user
    is_current_user = serializers.SerializerMethodField()
    # Add effective privileges (role defaults + special grants)
    privileges = serializers.SerializerMethodField()
    
    class Meta:
        model = User
        fields = [
            'id',
            'username',
            'email',
            'id_number',
            'first_name',
            'last_name',
            'account_type',
            'photo',
            'is_active',
            'last_login',
            'tenants',
            'role',
            'gender',
            'last_password_updated',
            'is_default_password',
            'is_staff',
            'is_superuser',
            'is_current_user',
            'privileges',
            # 'date_joined',
        ]
        read_only_fields = fields

    def get_privileges(self, obj):
        try:
            return obj.get_privileges()
        except Exception:
            return []
    
    def _tenant_list_payload(self, tenant, *, schema_name=None, workspace=None):
        """Build a tenant dict for login/workspace picker responses."""
        schema = schema_name or tenant.schema_name
        ws = workspace or tenant.schema_name
        return {
            'id': str(tenant.id),
            'id_number': getattr(tenant, 'id_number', None),
            'schema_name': schema,
            'workspace': ws,
            'name': tenant.name,
            'short_name': getattr(tenant, 'short_name', None),
            'logo': tenant.logo.url if tenant.logo else None,
            'status': getattr(tenant, 'status', None),
            'active': getattr(tenant, 'active', None),
            'phone': getattr(tenant, 'phone', None),
            'email': getattr(tenant, 'email', None),
            'website': getattr(tenant, 'website', None),
            'address': getattr(tenant, 'address', None),
            'city': getattr(tenant, 'city', None),
            'state': getattr(tenant, 'state', None),
            'country': getattr(tenant, 'country', None),
            'postal_code': getattr(tenant, 'postal_code', None),
        }

    def get_tenants(self, obj):
        """
        Get list of tenants (schools) this user belongs to.
        Useful for parents who may have children in multiple schools,
        and for workspace/school selection in the frontend.

        Superadmins receive every active tenant. Other users only receive
        tenants where they have UserTenantPermissions (capped at 20).
        """
        try:
            from core.models import Tenant
            from tenant_users.permissions.models import UserTenantPermissions
            from django_tenants.utils import get_public_schema_name, schema_context

            public_schema = get_public_schema_name()
            all_tenants = Tenant.objects.exclude(schema_name=public_schema).exclude(status='deleted')
            is_global_superadmin = (
                obj.role == Roles.SUPERADMIN or bool(getattr(obj, 'is_superuser', False))
            )

            result = []

            # Check if user should have access to public/admin schema
            # Include for superadmins, superusers, or explicit public schema permissions
            try:
                include_admin_schema = is_global_superadmin

                if not include_admin_schema:
                    # Check if user has explicit permissions in public schema
                    with schema_context(public_schema):
                        include_admin_schema = UserTenantPermissions.objects.filter(
                            profile_id=obj.id
                        ).exists()
                
                # Add admin/public schema to the beginning of results if eligible
                if include_admin_schema:
                    try:
                        public_tenant = Tenant.objects.get(schema_name=public_schema)
                        admin_payload = self._tenant_list_payload(
                            public_tenant,
                            schema_name='admin',
                            workspace='admin',
                        )
                        admin_payload['name'] = public_tenant.name or 'Admin'
                        result.append(admin_payload)
                    except Tenant.DoesNotExist:
                        # If public tenant doesn't exist, create a placeholder entry
                        result.append({
                            'id': 'admin',
                            'id_number': None,
                            'schema_name': 'admin',
                            'workspace': 'admin',
                            'name': 'Admin',
                            'short_name': None,
                            'logo': None,
                            'phone': None,
                            'email': None,
                            'website': None,
                            'address': None,
                            'city': None,
                            'state': None,
                            'country': None,
                            'postal_code': None,
                            'status': 'active',
                            'active': True,
                        })
            except Exception as admin_check_error:
                # If there's an error checking admin access, skip it
                pass
            
            tenant_payload_limit = 20

            for tenant in all_tenants:
                try:
                    if is_global_superadmin:
                        has_access = True
                    else:
                        with schema_context(tenant.schema_name):
                            has_access = UserTenantPermissions.objects.filter(
                                profile_id=obj.id
                            ).exists()

                    if has_access:
                        result.append(self._tenant_list_payload(tenant))
                except Exception:
                    continue

                if not is_global_superadmin and len(result) >= tenant_payload_limit:
                    break

            return result
        except Exception as e:
            # If there's any error, return empty list
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Error getting tenants for user {obj.email}: {e}")
            return []
    
    def get_is_current_user(self, obj):
        """
        Check if the user being serialized is the currently authenticated user.
        
        This allows the frontend to identify the logged-in user and display
        the "You" badge or apply special styling/permissions.
        
        Returns True if obj is the current user, False otherwise.
        """
        request = self.context.get('request')
        if request and hasattr(request, 'user') and request.user.is_authenticated:
            return obj.id == request.user.id
        return False
    
    def _resolve_profile_photo(self, instance, request):
        if instance.photo and hasattr(instance.photo, 'url'):
            return request.build_absolute_uri(instance.photo.url) if request else instance.photo.url

        if instance.photo and isinstance(instance.photo, str):
            return instance.photo

        if instance.account_type == UserAccountType.STAFF:
            staff = instance.get_staff()
            if staff and getattr(staff, 'photo', None):
                if hasattr(staff.photo, 'url'):
                    return request.build_absolute_uri(staff.photo.url) if request else staff.photo.url
                return str(staff.photo)

        if instance.account_type == UserAccountType.STUDENT:
            student = instance.get_student()
            if student and getattr(student, 'photo', None):
                if hasattr(student.photo, 'url'):
                    return request.build_absolute_uri(student.photo.url) if request else student.photo.url
                return str(student.photo)

        if instance.account_type == UserAccountType.PARENT:
            guardians = instance.get_guardian_records()
            guardian = guardians.first() if guardians is not None else None
            if guardian and guardian.photo:
                return guardian.photo

        return None

    def _resolve_source_bio(self, instance):
        """Resolve bio fields from tenant source records for non-global users."""
        if instance.account_type == UserAccountType.STUDENT:
            student = instance.get_student()
            if student:
                return {
                    'first_name': student.first_name,
                    'last_name': student.last_name,
                    'gender': student.gender,
                    'email': student.email,
                }

        if instance.account_type == UserAccountType.STAFF:
            staff = instance.get_staff()
            if staff:
                return {
                    'first_name': staff.first_name,
                    'last_name': staff.last_name,
                    'gender': staff.gender,
                    'email': staff.email,
                }

        if instance.account_type == UserAccountType.PARENT:
            guardians = instance.get_guardian_records()
            guardian = guardians.first() if guardians is not None else None
            if guardian:
                return {
                    'first_name': guardian.first_name,
                    'last_name': guardian.last_name,
                    'gender': None,
                    'email': guardian.email,
                }

        return {}

    def to_representation(self, instance):
        """
        Override to build full URL for photo field and set workspace.
        """
        data = super().to_representation(instance)
        request = self.context.get('request')

        data['photo'] = self._resolve_profile_photo(instance, request)

        if instance.account_type != UserAccountType.GLOBAL:
            source_bio = self._resolve_source_bio(instance)
            for field in ['first_name', 'last_name', 'gender', 'email']:
                if field in source_bio:
                    data[field] = source_bio[field]

        data['is_bio_editable'] = instance.account_type == UserAccountType.GLOBAL

        from django.db import connection
        from django_tenants.utils import get_public_schema_name

        current_schema = connection.schema_name
        public_schema = get_public_schema_name()

        if current_schema and current_schema != public_schema:
            data['workspace'] = current_schema
        else:
            try:
                if hasattr(instance, 'tenants'):
                    tenants_rel = instance.tenants
                    if tenants_rel and hasattr(tenants_rel, 'exists') and tenants_rel.exists():
                        tenant = tenants_rel.first()
                        data['workspace'] = tenant.schema_name if tenant else None
                    else:
                        data['workspace'] = None
                else:
                    data['workspace'] = None
            except Exception:
                data['workspace'] = None

        return data


class MultiFieldTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    Custom token serializer that accepts username, email, or id_number in the username field.
    
    The username field can contain:
    - username
    - email
    - id_number
    
    MultiFieldAuthBackend will automatically try all three fields to find the user.
    
    Includes custom claims (role, account_type) in token payload for stateless JWT authentication
    and access policy checking.
    """
    
    @classmethod
    def get_token(cls, user):
        """
        Override to add custom claims to the token payload.
        
        Includes role and account_type for stateless JWT authentication and access policies.
        These claims are used by JWTStatelessUserAuthentication to construct the user object
        without database queries.
        """
        token = super().get_token(user)
        token['role'] = user.role
        token['account_type'] = user.account_type
        token['email'] = user.email
        token['username'] = user.username or ''
        token['id_number'] = user.id_number
        token['first_name'] = user.first_name or ''
        token['last_name'] = user.last_name or ''
        token['is_active'] = user.is_active
        token['is_superuser'] = user.is_superuser
        token['is_staff'] = user.is_staff
        return token
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'email' in self.fields:
            del self.fields['email']
        self.fields['username'] = serializers.CharField()
    
    def validate(self, attrs):
        username = attrs.get('username')
        password = attrs.get('password')
        
        if not username or not password:
            errors = {}
            if not username:
                errors['username'] = ['This field is required.']
            if not password:
                errors['password'] = ['This field is required.']
            raise serializers.ValidationError(errors)
        
        user = authenticate(
            request=self.context.get('request'),
            username=username,
            password=password
        )
        
        if not user:
            raise serializers.ValidationError({
                'non_field_errors': ['No active account found with the given credentials']
            })
        
        if not user.is_active:
            raise serializers.ValidationError({
                'non_field_errors': ['User account is disabled.']
            })
        
        refresh = self.get_token(user)
        data = {
            'refresh': str(refresh),
            'access': str(refresh.access_token),
        }
        
        if hasattr(settings, 'SIMPLE_JWT') and settings.SIMPLE_JWT.get('UPDATE_LAST_LOGIN', False):
            user.last_login = timezone.now()
            user.save(update_fields=['last_login'])
        
        data['user'] = UserSerializer(user, context=self.context).data
        return data


class UserCreateSerializer(serializers.ModelSerializer):
    username = serializers.CharField(required=False, allow_blank=True, help_text="Defaults to id_number if not provided")
    
    class Meta:
        model = User
        fields = [
            'id',
            'username',
            'email',
            'id_number',
            'first_name',
            'last_name',
            'gender',
            'account_type',
            'role',
            'is_active',
            'is_staff',
            'is_superuser',
        ]
        read_only_fields = ['id']

    def validate_account_type(self, value):
        if value not in UserAccountType.all():
            raise serializers.ValidationError('Invalid account_type.')
        return value

    def validate_role(self, value):
        if value not in Roles.all():
            raise serializers.ValidationError('Invalid role.')
        return value

    def create(self, validated_data):
        id_number = validated_data['id_number']
        user = User(**validated_data)
        user.set_password(id_number)
        user.is_default_password = True
        user.last_password_updated = None
        user.save()
        return user


class UserUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            'username',
            'email',
            'first_name',
            'last_name',
            'gender',
            'account_type',
            'role',
            'is_active',
            'is_staff',
            'is_superuser',
            'photo',
        ]

    def update(self, instance, validated_data):
        """
        Only GLOBAL users can have user-level profile fields updated directly.
        For STUDENT/STAFF/PARENT, first_name/last_name/gender/photo remain sourced
        from tenant records, but email updates are allowed and synchronized by view logic.
        """
        if instance.account_type != UserAccountType.GLOBAL:
            for field in ['first_name', 'last_name', 'gender', 'photo']:
                validated_data.pop(field, None)

        return super().update(instance, validated_data)

    def validate_account_type(self, value):
        if value not in UserAccountType.all():
            raise serializers.ValidationError('Invalid account_type.')
        return value

    def validate_role(self, value):
        if value not in Roles.all():
            raise serializers.ValidationError('Invalid role.')
        return value


class PasswordChangeSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True, required=True)
    new_password = serializers.CharField(write_only=True, required=True, min_length=6)
    confirm_password = serializers.CharField(write_only=True, required=True)

    def validate(self, attrs):
        if attrs['new_password'] != attrs['confirm_password']:
            raise serializers.ValidationError({'confirm_password': 'Passwords do not match.'})
        return attrs


class PasswordForgotSerializer(serializers.Serializer):
    user_identifier = serializers.CharField(required=True)


class UserRecreateSerializer(serializers.Serializer):
    account_type = serializers.ChoiceField(choices=[
        UserAccountType.STUDENT,
        UserAccountType.STAFF,
        UserAccountType.PARENT,
    ])
    id_number = serializers.CharField(required=True)
    date_of_birth = serializers.DateField(required=True)
    username = serializers.CharField(required=False, allow_blank=True, help_text="Defaults to id_number if not provided")
    notify_user = serializers.BooleanField(required=False, default=True)

    def validate(self, attrs):
        if not attrs.get('id_number'):
            raise serializers.ValidationError({'id_number': 'id_number is required.'})
        return attrs

