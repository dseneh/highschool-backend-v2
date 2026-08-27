"""
Serializers for authentication
"""
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.contrib.auth import authenticate, get_user_model
from django.conf import settings
from django.utils import timezone

from common.status import UserAccountType

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
    rbac_role = serializers.SerializerMethodField()
    profile_updated_by = serializers.SerializerMethodField()
    
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
            'status',
            'last_login',
            'tenants',
            'rbac_role',
            'gender',
            'last_password_updated',
            'created_at',
            'profile_updated_at',
            'profile_updated_by',
            'is_default_password',
            'is_platform_superuser',
            'is_current_user',
        ]
        read_only_fields = fields

    def get_rbac_role(self, obj):
        from django.db import connection
        from django_tenants.utils import get_public_schema_name

        if connection.schema_name == get_public_schema_name():
            try:
                from core.models import SharedRoleAssignment

                assignment = SharedRoleAssignment.objects.select_related("role").filter(
                    user=obj,
                    is_active=True,
                    role__is_active=True,
                ).first()
                if assignment is None:
                    return None
                return {
                    "id": str(assignment.role_id),
                    "name": assignment.role.name,
                    "system_key": assignment.role.system_key,
                    "is_active": assignment.is_active and assignment.role.is_active,
                    "role_type": assignment.role.role_type,
                    "scope": assignment.role.scope,
                }
            except Exception:
                return None

        try:
            from authorization.models import TenantMembership
            from authorization.services import get_applicable_shared_role

            membership = TenantMembership.objects.select_related("role").filter(user=obj).first()
            if membership is None:
                return None
            if membership.shared_role_id:
                role = get_applicable_shared_role(membership.shared_role_id)
                return {
                    "id": str(role.pk),
                    "name": role.name,
                    "system_key": role.system_key,
                    "is_active": membership.is_active and role.is_active,
                    "role_type": role.role_type,
                    "scope": role.scope,
                }
            return {
                "id": str(membership.role_id),
                "name": membership.role.name,
                "system_key": membership.role.system_key,
                "is_active": membership.is_active and membership.role.is_active,
                "role_type": "CUSTOM" if not membership.role.is_system_role else "SYSTEM",
                "scope": "TENANT",
            }
        except Exception:
            return None

    def get_profile_updated_by(self, obj):
        actor = getattr(obj, "profile_updated_by", None)
        if actor is None:
            return None
        full_name = f"{actor.first_name} {actor.last_name}".strip()
        return {
            "id": str(actor.pk),
            "id_number": actor.id_number,
            "full_name": full_name or actor.username or actor.email,
            "email": actor.email,
        }

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
            'logo': self._build_logo_url(tenant),
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

    def _build_logo_url(self, tenant):
        """Return an absolute logo URL so the frontend doesn't try to
        load it from its own origin (e.g. the Next.js dev server)."""
        from core.utils import resolve_tenant_logo_media_url

        relative = resolve_tenant_logo_media_url(getattr(tenant, "logo", None))
        if not relative:
            return None
        request = self.context.get('request') if hasattr(self, 'context') else None
        if request is not None:
            return request.build_absolute_uri(relative)
        return relative

    def get_tenants(self, obj):
        """
        Get list of tenants (schools) this user belongs to.
        Useful for parents who may have children in multiple schools,
        and for workspace/school selection in the frontend.

        Superadmins receive every active tenant. Other users only receive
        tenants where they have UserTenantPermissions (capped at 20).

        Tenant membership lives in the public schema and per-tenant permission
        tables. This method always resolves the canonical User row from public
        so it still works when the request arrived with an X-Tenant header
        (connection on a school schema) or a JWT stateless user stub.
        """
        import logging

        logger = logging.getLogger(__name__)

        try:
            from core.models import Tenant
            from tenant_users.permissions.models import UserTenantPermissions
            from django_tenants.utils import get_public_schema_name, schema_context
            from users.tenant_access import is_global_superadmin as _is_global_superadmin

            user_id = getattr(obj, "id", None)
            if not user_id:
                return []

            public_schema = get_public_schema_name()

            with schema_context(public_schema):
                try:
                    db_user = User.objects.get(pk=user_id)
                except User.DoesNotExist:
                    db_user = obj

                is_global_superadmin = _is_global_superadmin(db_user)
                result = []

                # Check if user should have access to public/admin schema
                try:
                    include_admin_schema = is_global_superadmin

                    if not include_admin_schema:
                        include_admin_schema = UserTenantPermissions.objects.filter(
                            profile_id=db_user.id
                        ).exists()

                    if include_admin_schema:
                        try:
                            public_tenant = Tenant.objects.get(schema_name=public_schema)
                            admin_payload = self._tenant_list_payload(
                                public_tenant,
                                schema_name="admin",
                                workspace="admin",
                            )
                            admin_payload["name"] = public_tenant.name or "Admin"
                            result.append(admin_payload)
                        except Tenant.DoesNotExist:
                            result.append(
                                {
                                    "id": "admin",
                                    "id_number": None,
                                    "schema_name": "admin",
                                    "workspace": "admin",
                                    "name": "Admin",
                                    "short_name": None,
                                    "logo": None,
                                    "phone": None,
                                    "email": None,
                                    "website": None,
                                    "address": None,
                                    "city": None,
                                    "state": None,
                                    "country": None,
                                    "postal_code": None,
                                    "status": "active",
                                    "active": True,
                                }
                            )
                except Exception:
                    pass

                tenant_payload_limit = 20
                all_tenants = Tenant.objects.exclude(
                    schema_name=public_schema
                ).exclude(status="deleted")

                for tenant in all_tenants:
                    try:
                        if is_global_superadmin:
                            has_access = True
                        else:
                            with schema_context(tenant.schema_name):
                                has_access = UserTenantPermissions.objects.filter(
                                    profile_id=db_user.id
                                ).exists()

                        if has_access:
                            result.append(self._tenant_list_payload(tenant))
                    except Exception:
                        continue

                    if not is_global_superadmin and len(result) >= tenant_payload_limit:
                        break

                return result
        except Exception as exc:
            logger.warning(
                "Error getting tenants for user %s: %s",
                getattr(obj, "email", None),
                exc,
            )
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
    
    Includes identity claims in token payload for stateless JWT authentication.
    and access policy checking.
    """
    
    @classmethod
    def get_token(cls, user):
        """
        Override to add custom claims to the token payload.
        
        Includes identity information for stateless JWT authentication.
        These claims are used by JWTStatelessUserAuthentication to construct the user object
        without database queries.
        """
        token = super().get_token(user)
        token['account_type'] = user.account_type
        token['email'] = user.email
        token['username'] = user.username or ''
        token['id_number'] = user.id_number
        token['first_name'] = user.first_name or ''
        token['last_name'] = user.last_name or ''
        token['is_active'] = user.is_active
        token['is_platform_superuser'] = bool(user.is_platform_superuser)
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
                'detail': ['No active account found with the given credentials']
            })
        
        if not user.is_active:
            raise serializers.ValidationError({
                'detail': ['User account is disabled.']
            })

        from authorization.exceptions import NoAssignedRole
        from authorization.services import has_assigned_role

        # Checked before any token is built so an unassigned account never
        # receives credentials.
        if not has_assigned_role(user):
            raise NoAssignedRole()

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
            'is_active',
            'is_platform_superuser',
        ]
        read_only_fields = ['id']

    def validate_account_type(self, value):
        if value not in UserAccountType.all():
            raise serializers.ValidationError('Invalid account_type.')
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
            'is_active',
            'is_platform_superuser',
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


class AdminPasswordResetSerializer(serializers.Serializer):
    """Admin-initiated password reset.

    Does NOT require the target user's current password — the actor must
    be a superadmin/admin (enforced at the view level via UserAccessPolicy).
    """

    new_password = serializers.CharField(write_only=True, required=True, min_length=6)
    confirm_password = serializers.CharField(write_only=True, required=True)
    mark_as_default = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs):
        if attrs['new_password'] != attrs['confirm_password']:
            raise serializers.ValidationError({'confirm_password': 'Passwords do not match.'})
        return attrs


class UserRecreateSerializer(serializers.Serializer):
    account_type = serializers.ChoiceField(choices=[
        UserAccountType.STUDENT,
        UserAccountType.STAFF,
        UserAccountType.PARENT,
    ])
    id_number = serializers.CharField(required=True)
    # Optional: the Users page picks the record from a dialog, so the
    # id_number alone identifies it. Kept as an extra check when supplied.
    date_of_birth = serializers.DateField(required=False, allow_null=True)
    username = serializers.CharField(required=False, allow_blank=True, help_text="Defaults to id_number if not provided")
    notify_user = serializers.BooleanField(required=False, default=True)
    role = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Role system key or id. Required for staff accounts; student and parent accounts use their fixed role.",
    )

    def validate(self, attrs):
        if not attrs.get('id_number'):
            raise serializers.ValidationError({'id_number': 'id_number is required.'})
        return attrs

