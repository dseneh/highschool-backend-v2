"""Serializers for authentication and user management."""
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.contrib.auth import authenticate, get_user_model
from django.conf import settings
from django.utils import timezone

from common.status import UserAccountType

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    tenants = serializers.SerializerMethodField()
    is_current_user = serializers.SerializerMethodField()
    rbac_role = serializers.SerializerMethodField()
    profile_updated_by = serializers.SerializerMethodField()
    linked_profiles = serializers.SerializerMethodField()
    platform_employment = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'username', 'email', 'id_number', 'first_name', 'last_name',
            'account_type', 'account_scope', 'photo', 'is_active', 'status',
            'last_login', 'tenants', 'rbac_role', 'gender',
            'last_password_updated', 'created_at', 'profile_updated_at',
            'profile_updated_by', 'is_default_password', 'is_platform_superuser',
            'is_current_user', 'linked_profiles', 'platform_employment',
        ]
        read_only_fields = fields

    def get_rbac_role(self, obj):
        from django.db import connection
        from django_tenants.utils import get_public_schema_name

        if connection.schema_name == get_public_schema_name():
            try:
                from core.models import SharedRoleAssignment
                assignment = SharedRoleAssignment.objects.select_related('role').filter(
                    user=obj, is_active=True, role__is_active=True,
                    role__scope__in=['PUBLIC', 'GLOBAL'],
                ).first()
                if assignment is None:
                    return None
                return {
                    'id': str(assignment.role_id), 'name': assignment.role.name,
                    'system_key': assignment.role.system_key,
                    'is_active': assignment.is_active and assignment.role.is_active,
                    'role_type': assignment.role.role_type, 'scope': assignment.role.scope,
                }
            except Exception:
                return None

        try:
            from authorization.models import TenantMembership
            from authorization.services import get_applicable_shared_role
            membership = TenantMembership.objects.select_related('role').filter(user=obj).first()
            if membership is None:
                return None
            if membership.shared_role_id:
                role = get_applicable_shared_role(membership.shared_role_id)
                return {
                    'id': str(role.pk), 'name': role.name, 'system_key': role.system_key,
                    'is_active': membership.is_active and role.is_active,
                    'role_type': role.role_type, 'scope': role.scope,
                }
            if membership.role is None:
                return None
            return {
                'id': str(membership.role_id), 'name': membership.role.name,
                'system_key': membership.role.system_key,
                'is_active': membership.is_active and membership.role.is_active,
                'role_type': 'CUSTOM' if not membership.role.is_system_role else 'SYSTEM',
                'scope': 'TENANT',
            }
        except Exception:
            return None

    def get_profile_updated_by(self, obj):
        actor = getattr(obj, 'profile_updated_by', None)
        if actor is None:
            return None
        full_name = f'{actor.first_name} {actor.last_name}'.strip()
        return {
            'id': str(actor.pk),
            'id_number': actor.id_number,
            'full_name': full_name or actor.username or actor.email,
            'email': actor.email,
        }

    def _is_public_detail_request(self) -> bool:
        from django.db import connection
        from django_tenants.utils import get_public_schema_name

        if connection.schema_name != get_public_schema_name():
            return False
        request = self.context.get('request')
        parser_context = getattr(request, 'parser_context', None) or {}
        view = parser_context.get('view')
        return getattr(view, 'action', None) == 'retrieve'

    def get_linked_profiles(self, obj):
        if self._is_public_detail_request():
            from users.access_service import discover_linked_profile_types
            return discover_linked_profile_types(obj)

        profiles = []
        if obj.get_staff() is not None:
            profiles.append('staff')
        if obj.get_student() is not None:
            profiles.append('student')
        guardians = obj.get_guardian_records()
        if guardians is not None and guardians.exists():
            profiles.append('parent')
        try:
            obj.platform_employment
            profiles.append('platform_employee')
        except Exception:
            pass
        return profiles

    def get_platform_employment(self, obj):
        try:
            employment = obj.platform_employment
        except Exception:
            return None
        return {
            'id': str(employment.pk),
            'employee_number': employment.employee_number,
            'position': employment.position,
            'department': employment.department,
            'status': employment.status,
            'hire_date': employment.hire_date,
            'termination_date': employment.termination_date,
        }

    def _tenant_list_payload(self, tenant, *, schema_name=None, workspace=None):
        schema = schema_name or tenant.schema_name
        ws = workspace or tenant.schema_name
        return {
            'id': str(tenant.id), 'id_number': getattr(tenant, 'id_number', None),
            'schema_name': schema, 'workspace': ws, 'name': tenant.name,
            'short_name': getattr(tenant, 'short_name', None), 'logo': self._build_logo_url(tenant),
            'status': getattr(tenant, 'status', None), 'active': getattr(tenant, 'active', None),
            'phone': getattr(tenant, 'phone', None), 'email': getattr(tenant, 'email', None),
            'website': getattr(tenant, 'website', None), 'address': getattr(tenant, 'address', None),
            'city': getattr(tenant, 'city', None), 'state': getattr(tenant, 'state', None),
            'country': getattr(tenant, 'country', None), 'postal_code': getattr(tenant, 'postal_code', None),
        }

    def _build_logo_url(self, tenant):
        from core.utils import resolve_tenant_logo_media_url
        relative = resolve_tenant_logo_media_url(getattr(tenant, 'logo', None))
        if not relative:
            return None
        request = self.context.get('request') if hasattr(self, 'context') else None
        return request.build_absolute_uri(relative) if request is not None else relative

    def get_tenants(self, obj):
        import logging
        logger = logging.getLogger(__name__)
        try:
            from core.models import Tenant
            from django_tenants.utils import get_public_schema_name, schema_context
            from users.tenant_access import is_global_superadmin, user_has_platform_workspace_access
            from authorization.services import get_assigned_role

            user_id = getattr(obj, 'id', None)
            if not user_id:
                return []
            public_schema = get_public_schema_name()
            with schema_context(public_schema):
                try:
                    db_user = User.objects.get(pk=user_id)
                except User.DoesNotExist:
                    db_user = obj
                superadmin = is_global_superadmin(db_user)
                result = []
                if user_has_platform_workspace_access(db_user):
                    try:
                        public_tenant = Tenant.objects.get(schema_name=public_schema)
                        payload = self._tenant_list_payload(public_tenant, schema_name='admin', workspace='admin')
                        payload['name'] = public_tenant.name or 'Admin'
                        result.append(payload)
                    except Tenant.DoesNotExist:
                        result.append({
                            'id': 'admin', 'schema_name': 'admin', 'workspace': 'admin',
                            'name': 'Admin', 'status': 'active', 'active': True,
                        })

                for tenant in Tenant.objects.exclude(schema_name=public_schema).exclude(status='deleted'):
                    try:
                        if superadmin:
                            allowed = True
                        else:
                            with schema_context(tenant.schema_name):
                                allowed = db_user.has_tenant_permissions() and get_assigned_role(db_user) is not None
                        if allowed:
                            result.append(self._tenant_list_payload(tenant))
                    except Exception:
                        continue
                    if not superadmin and len(result) >= 20:
                        break
                return result
        except Exception as exc:
            logger.warning('Error getting tenants for user %s: %s', getattr(obj, 'email', None), exc)
            return []

    def get_is_current_user(self, obj):
        request = self.context.get('request')
        return bool(
            request and hasattr(request, 'user') and request.user.is_authenticated
            and obj.id == request.user.id
        )

    def _resolve_profile_photo(self, instance, request):
        if instance.photo and hasattr(instance.photo, 'url'):
            return request.build_absolute_uri(instance.photo.url) if request else instance.photo.url
        if instance.photo and isinstance(instance.photo, str):
            return instance.photo
        if instance.account_type == UserAccountType.STAFF:
            source = instance.get_staff()
        elif instance.account_type == UserAccountType.STUDENT:
            source = instance.get_student()
        elif instance.account_type == UserAccountType.PARENT:
            records = instance.get_guardian_records()
            source = records.first() if records is not None else None
        else:
            source = None
        photo = getattr(source, 'photo', None) if source else None
        if photo and hasattr(photo, 'url'):
            return request.build_absolute_uri(photo.url) if request else photo.url
        return str(photo) if photo else None

    def _resolve_source_bio(self, instance):
        if instance.account_type == UserAccountType.STUDENT:
            source = instance.get_student()
        elif instance.account_type == UserAccountType.STAFF:
            source = instance.get_staff()
        elif instance.account_type == UserAccountType.PARENT:
            records = instance.get_guardian_records()
            source = records.first() if records is not None else None
        else:
            source = None
        if not source:
            return {}
        return {
            'first_name': getattr(source, 'first_name', None),
            'last_name': getattr(source, 'last_name', None),
            'gender': getattr(source, 'gender', None),
            'email': getattr(source, 'email', None),
        }

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get('request')
        data['photo'] = self._resolve_profile_photo(instance, request)
        source_bio = self._resolve_source_bio(instance)
        for field in ['first_name', 'last_name', 'gender', 'email']:
            if source_bio.get(field) is not None:
                data[field] = source_bio[field]
        data['is_bio_editable'] = instance.account_type == UserAccountType.OTHER

        from django.db import connection
        from django_tenants.utils import get_public_schema_name
        current_schema = connection.schema_name
        data['workspace'] = (
            current_schema if current_schema and current_schema != get_public_schema_name()
            else None
        )
        return data


class MultiFieldTokenObtainPairSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token['account_type'] = user.account_type
        token['account_scope'] = user.account_scope
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
        username, password = attrs.get('username'), attrs.get('password')
        if not username or not password:
            errors = {}
            if not username:
                errors['username'] = ['This field is required.']
            if not password:
                errors['password'] = ['This field is required.']
            raise serializers.ValidationError(errors)
        user = authenticate(request=self.context.get('request'), username=username, password=password)
        if not user:
            raise serializers.ValidationError({'detail': ['No active account found with the given credentials']})
        if not user.is_active:
            raise serializers.ValidationError({'detail': ['User account is disabled.']})

        from authorization.exceptions import NoAssignedRole
        from users.access_service import has_any_assigned_role
        if not has_any_assigned_role(user):
            raise NoAssignedRole()

        refresh = self.get_token(user)
        data = {'refresh': str(refresh), 'access': str(refresh.access_token)}
        if hasattr(settings, 'SIMPLE_JWT') and settings.SIMPLE_JWT.get('UPDATE_LAST_LOGIN', False):
            user.last_login = timezone.now()
            user.save(update_fields=['last_login'])
        data['user'] = UserSerializer(user, context=self.context).data
        return data


class UserCreateSerializer(serializers.ModelSerializer):
    username = serializers.CharField(
        required=False, allow_blank=True, help_text='Defaults to id_number if not provided'
    )

    class Meta:
        model = User
        fields = [
            'id', 'username', 'email', 'id_number', 'first_name', 'last_name',
            'gender', 'account_type', 'is_active',
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
            'username', 'email', 'first_name', 'last_name', 'gender',
            'account_type', 'is_active', 'photo',
        ]

    def update(self, instance, validated_data):
        if instance.account_type != UserAccountType.OTHER:
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
    new_password = serializers.CharField(write_only=True, required=True, min_length=6)
    confirm_password = serializers.CharField(write_only=True, required=True)
    mark_as_default = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs):
        if attrs['new_password'] != attrs['confirm_password']:
            raise serializers.ValidationError({'confirm_password': 'Passwords do not match.'})
        return attrs


class UserRecreateSerializer(serializers.Serializer):
    account_type = serializers.ChoiceField(
        choices=[UserAccountType.STUDENT, UserAccountType.STAFF, UserAccountType.PARENT]
    )
    id_number = serializers.CharField(required=True)
    date_of_birth = serializers.DateField(required=False, allow_null=True)
    username = serializers.CharField(
        required=False, allow_blank=True, help_text='Defaults to id_number if not provided'
    )
    notify_user = serializers.BooleanField(required=False, default=True)
    role = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        if not attrs.get('id_number'):
            raise serializers.ValidationError({'id_number': 'id_number is required.'})
        return attrs
