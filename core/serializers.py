"""
Serializers for core models (Tenant)
"""
from rest_framework import serializers
from core.models import Tenant, Domain, SignupRequest
from core.utils import resolve_tenant_logo_media_url
from django_tenants.utils import schema_context
import logging
import uuid


logger = logging.getLogger(__name__)


def get_signup_request_linked_tenant(instance: SignupRequest):
    workspace_slug = (instance.workspace_slug or "").strip()
    if not workspace_slug:
        return None
    return Tenant.objects.filter(schema_name=workspace_slug).first()


def get_signup_request_owner(tenant: Tenant | None, signup_request: SignupRequest):
    if tenant and getattr(tenant, "owner", None):
        return tenant.owner
    request_email = (signup_request.email or "").strip().lower()
    if not request_email:
        return None
    from users.models import User

    return User.objects.filter(email__iexact=request_email).first()


def _sync_signup_request_after_tenant_create(
    *,
    tenant: Tenant,
    owner,
    signup_request_id: int | None = None,
    request=None,
    actor=None,
):
    """Link and refresh the most relevant signup request once workspace is created."""
    queryset = SignupRequest.objects.all()
    signup_request = None

    if signup_request_id:
        signup_request = queryset.filter(pk=signup_request_id).first()

    if not signup_request and tenant.schema_name:
        signup_request = queryset.filter(
            workspace_slug__iexact=tenant.schema_name
        ).order_by("-submitted_at").first()

    owner_email = (getattr(owner, "email", "") or "").strip().lower()
    if not signup_request and owner_email:
        signup_request = queryset.filter(email__iexact=owner_email).order_by("-submitted_at").first()

    if not signup_request and tenant.name:
        signup_request = queryset.filter(school_name__iexact=tenant.name).order_by("-submitted_at").first()

    if not signup_request:
        return

    update_fields = []
    changed_values = {}

    if tenant.schema_name and signup_request.workspace_slug != tenant.schema_name:
        changed_values["workspace_slug"] = {
            "from": signup_request.workspace_slug,
            "to": tenant.schema_name,
        }
        signup_request.workspace_slug = tenant.schema_name
        update_fields.append("workspace_slug")

    if tenant.name and signup_request.school_name != tenant.name:
        changed_values["school_name"] = {
            "from": signup_request.school_name,
            "to": tenant.name,
        }
        signup_request.school_name = tenant.name
        update_fields.append("school_name")

    if getattr(tenant, "phone", None) and not signup_request.phone:
        changed_values["phone"] = {
            "from": signup_request.phone,
            "to": tenant.phone,
        }
        signup_request.phone = tenant.phone
        update_fields.append("phone")

    if owner_email and signup_request.email.lower() != owner_email:
        changed_values["email"] = {
            "from": signup_request.email,
            "to": owner_email,
        }
        signup_request.email = owner_email
        update_fields.append("email")

    if getattr(tenant, "country", None) and not signup_request.country:
        changed_values["country"] = {
            "from": signup_request.country,
            "to": tenant.country,
        }
        signup_request.country = tenant.country
        update_fields.append("country")

    if signup_request.status in (SignupRequest.STATUS_PENDING, SignupRequest.STATUS_CONTACTED):
        changed_values["status"] = {
            "from": signup_request.status,
            "to": SignupRequest.STATUS_ONBOARDED,
        }
        signup_request.status = SignupRequest.STATUS_ONBOARDED
        update_fields.append("status")

    if update_fields:
        signup_request.save(update_fields=update_fields)
        from common.audit_utils import log_signup_request_workspace_sync

        log_signup_request_workspace_sync(
            request=request,
            actor=actor,
            signup_request=signup_request,
            tenant=tenant,
            changes=changed_values,
        )


class TenantDomainMixin:
    """
    Mixin for tenant serializers to provide domain-related methods.
    """
    def get_domain(self, obj):
        """
        Get the primary domain for the tenant.
        Returns the primary domain's domain string, or the first domain if no primary exists.
        """
        try:
            primary_domain = obj.domains.filter(is_primary=True).first()
            if primary_domain:
                return primary_domain.domain
            # Fallback to first domain if no primary
            first_domain = obj.domains.first()
            if first_domain:
                return first_domain.domain
            return None
        except Exception:
            return None
    
    def get_domains(self, obj):
        """
        Get all domains for the tenant.
        Returns a list of domain objects with id, domain, and is_primary.
        """
        try:
            domains = obj.domains.all()
            return [
                {
                    "id": domain.id,
                    "domain": domain.domain,
                    "is_primary": domain.is_primary,
                }
                for domain in domains
            ]
        except Exception:
            return []
    
    def build_logo_url(self, instance, request):
        """
        Build full URL for logo if available.
        """
        relative = resolve_tenant_logo_media_url(getattr(instance, "logo", None))
        if not relative:
            return None
        if request:
            return request.build_absolute_uri(relative)
        return relative


class BaseTenantSerializer(TenantDomainMixin, serializers.ModelSerializer):
    """
    Base serializer for Tenant model with common functionality.
    Provides domain methods and logo URL building.
    """
    domain = serializers.SerializerMethodField()
    domains = serializers.SerializerMethodField()
    
    class Meta:
        model = Tenant
        abstract = True
    
    # def get_logo_url(self, obj):
    #     """Build full URL for logo if available."""
    #     return self.build_logo_url(obj, self.context.get("request"))
    
    
    def to_representation(self, instance):
        """
        Override to build full URLs for logo.
        """
        response = super().to_representation(instance)
        request = self.context.get("request")
        response["logo"] = self.build_logo_url(instance, request)
        response["workspace"] = instance.schema_name
        return response


class TenantListSerializer(BaseTenantSerializer):
    """
    Lightweight serializer for listing tenants (better performance).
    Returns only the most relevant fields for list views.
    Used for both authenticated and unauthenticated endpoints.
    Includes logo with default fallback when null.
    """
    
    class Meta:
        model = Tenant
        fields = [
            "id",
            "id_number",
            "schema_name",
            "name",
            "short_name",
            "phone",
            "email",
            "website",
            "address",
            "city",
            "state",
            "country",
            "postal_code",
            "logo",
            "logo_shape",
            "theme_color",
            "domains",
            "domain",
            "active",
            "status",
            "maintenance_mode",
            "login_access_policy",
            "disabled_access_allow_tenant_admins",
            "disabled_access_allowed_paths",
            "disabled_access_allowed_users",
        ]
        read_only_fields = fields

class PublicTenantSerializer(BaseTenantSerializer):
    """
    Public serializer for Tenant model (no authentication required).
    Used for tenant discovery, routing, and branding before login.
    Includes basic tenant information needed for frontend routing and branding.
    Only active tenants are returned (filtered in get_queryset).
    """
    class Meta:
        model = Tenant
        fields = [
            "id",
            "id_number",
            "name",
            "short_name",
            "schema_name",
            "domain",
            "domains",
            "website",
            "status",
            "active",
            "maintenance_mode",
            "login_access_policy",
            "disabled_access_allow_tenant_admins",
            "disabled_access_allowed_paths",
            "disabled_access_allowed_users",
            "logo",
            "logo_shape",
            "theme_color",
            "theme_config",
        ]
        read_only_fields = fields
    def to_representation(self, instance):
        """
        Override to build full URLs for logo.
        """
        response = super().to_representation(instance)
        response["workspace"] = instance.schema_name
        return response


class TenantSerializer(BaseTenantSerializer):
    """
    Serializer for Tenant model.
    Used for reading and updating tenant data.
    Includes all tenant profile fields and domain information.
    """
    schema_name = serializers.CharField(read_only=True)
    id_number = serializers.CharField(read_only=True)  # ID number should not be changed after creation
    
    class Meta:
        model = Tenant
        fields = [
            # Core fields
            "id",
            "id_number",
            "name",
            "short_name",
            "schema_name",
            # Domain information
            "domain",
            "domains",
            # Identity fields
            "funding_type",
            "school_type",
            "slogan",
            "emis_number",
            "description",
            "date_est",
            # Address fields
            "address",
            "city",
            "state",
            "country",
            "postal_code",
            # Contact fields
            "phone",
            "email",
            "website",
            # Status and configuration
            "status",
            "active",
            "maintenance_mode",
            "login_access_policy",
            "disabled_access_allow_tenant_admins",
            "disabled_access_allowed_paths",
            "disabled_access_allowed_users",
            # Branding
            "logo",
            "logo_shape",
            "theme_color",
            "theme_config",
            # Onboarding
            "onboarding_plan",
            "onboarding_started_at",
            "onboarding_completed_at",
            # Timestamps
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "id_number", "schema_name", "created_at", "updated_at"]
    
    def to_representation(self, instance):
        """
        Override to build full URLs for logo and include computed fields.
        """
        response = super().to_representation(instance)
        
        # Add full_address computed field
        address_parts = [
            instance.address or "",
            instance.city or "",
            instance.state or "",
            instance.country or "",
            instance.postal_code or "",
        ]
        response["full_address"] = ", ".join([part for part in address_parts if part])
        
        return response


class PublicTenantSerializer(serializers.ModelSerializer, TenantDomainMixin):
    """
    Limited serializer for public tenant information.
    Used for public pages like login, registration, etc.
    """
    domain = serializers.SerializerMethodField(method_name="get_domain")
    
    class Meta:
        model = Tenant
        fields = [
            "id",
            "name",
            "schema_name",
            "domain",
            "logo",
            "active",
            "status",
            "maintenance_mode",
            "login_access_policy",
            "disabled_access_allow_tenant_admins",
            "disabled_access_allowed_paths",
            "disabled_access_allowed_users",
            "theme_config",
            # Expose onboarding status so frontend can enforce redirect
            "onboarding_started_at",
            "onboarding_completed_at",
        ]

class CreateTenantSerializer(serializers.Serializer):
    """
    Serializer for creating a new Tenant.
    
    This serializer handles the creation of a new tenant with domain.
    """
    name = serializers.CharField(max_length=255, help_text="Tenant name (required)")
    short_name = serializers.CharField(
        max_length=50, 
        required=False, 
        allow_blank=True,
        help_text="Short name for the tenant (optional)"
    )
    schema_name = serializers.CharField(
        max_length=63,
        required=False,
        help_text="Schema name (optional, uses workspace value or auto-generated from name)"
    )
    domain = serializers.CharField(
        max_length=253,
        required=False,
        help_text="Domain name (optional, auto-generated if not provided)"
    )
    owner_email = serializers.EmailField(
        required=False,
        help_text="Email of the owner user (optional, uses request user if not provided)"
    )
    signup_request_id = serializers.IntegerField(
        required=False,
        min_value=1,
        write_only=True,
        help_text="Signup request ID to link/update automatically after workspace creation.",
    )
    email = serializers.EmailField(required=False, allow_blank=True)
    phone = serializers.CharField(max_length=20, required=False, allow_blank=True)
    website = serializers.URLField(required=False, allow_blank=True)
    funding_type = serializers.CharField(max_length=100, required=False, allow_blank=True)
    school_type = serializers.CharField(max_length=100, required=False, allow_blank=True)
    slogan = serializers.CharField(max_length=250, required=False, allow_blank=True)
    emis_number = serializers.CharField(max_length=100, required=False, allow_blank=True)
    description = serializers.CharField(required=False, allow_blank=True)
    date_est = serializers.DateField(required=False, allow_null=True)
    address = serializers.CharField(max_length=250, required=False, allow_blank=True)
    city = serializers.CharField(max_length=100, required=False, allow_blank=True)
    state = serializers.CharField(max_length=100, required=False, allow_blank=True)
    country = serializers.CharField(max_length=100, required=False, allow_blank=True)
    postal_code = serializers.CharField(max_length=20, required=False, allow_blank=True)
    active = serializers.BooleanField(default=True)
    maintenance_mode = serializers.BooleanField(default=False, required=False)
    login_access_policy = serializers.ChoiceField(
        choices=["all_users", "tenant_admin_only", "disabled"],
        default="all_users",
        required=False,
    )
    disabled_access_allow_tenant_admins = serializers.BooleanField(default=True, required=False)
    disabled_access_allowed_paths = serializers.ListField(
        child=serializers.CharField(max_length=120),
        required=False,
        default=list,
    )
    disabled_access_allowed_users = serializers.ListField(
        child=serializers.CharField(max_length=120),
        required=False,
        default=list,
    )

    def validate_value(self, value, field_name):
        """Validate schema_name format and uniqueness"""
        if value:
            value = value.strip()
            # Schema names must be valid PostgreSQL identifiers
            if not value.replace('_', '').isalnum():
                raise serializers.ValidationError(
                    f"{field_name} can only contain letters, numbers, and underscores"
                )
            if len(value) > 63:
                raise serializers.ValidationError(f"{field_name} must be 63 characters or less")
            
            # Check if schema_name already exists
            from core.models import Tenant
            f = {field_name: value}
            if Tenant.objects.filter(**f).exists():
                raise serializers.ValidationError(
                    f"A tenant with {field_name} '{value}' already exists"
                )
        return value

    def validate_workspace(self, value):
        """Validate workspace format and uniqueness"""
        value = self.validate_value(value, "workspace")
        return value

    def validate_schema_name(self, value):
        """Validate schema_name format and uniqueness"""
        value = self.validate_value(value, "schema_name")
        return value

    def validate_domain(self, value):
        from core.models import Domain

        value = value.strip().lower()
        if Domain.objects.filter(domain__iexact=value).exists():
            raise serializers.ValidationError(f"Domain '{value}' already exists")
        return value

    def validate_name(self, value):
        """Ensure name is not empty and unique"""
        if not value or not value.strip():
            raise serializers.ValidationError("Tenant name cannot be empty")
        
        # Check if tenant name already exists
        from core.models import Tenant
        if Tenant.objects.filter(name__iexact=value.strip()).exists():
            raise serializers.ValidationError(
                f"A tenant with name '{value.strip()}' already exists"
            )
        
        return value.strip()

    def create(self, validated_data):
        """
        Create a new Tenant with domain.
        
        This should be called from a view that ensures we're in the public schema.
        Accepts all tenant profile fields for complete tenant setup.
        """
        from core.models import Tenant, Domain
        from users.models import User
        from common.status import Roles, UserAccountType
        from tenant_users.permissions.models import UserTenantPermissions

        # Required fields
        name = validated_data["name"]
        short_name = validated_data.get("short_name") or name[:10]
        workspace = validated_data.get("workspace")
        schema_name = validated_data.get("schema_name")
        domain = validated_data.get("domain")
        owner_email = validated_data.get("owner_email")
        signup_request_id = validated_data.get("signup_request_id")
        
        # Priority: workspace > schema_name > auto-generate from name
        # Workspace is the preferred identifier that becomes the schema_name
        if not schema_name:
            # Auto-generate from name if neither workspace nor schema_name provided
            schema_name = short_name.lower().replace(' ', '_').replace('-', '_')
            # Remove any special characters
            schema_name = ''.join(c for c in schema_name if c.isalnum() or c == '_')
        
        # Double-check uniqueness (in case validation was bypassed)
        from core.models import Tenant
        if Tenant.objects.filter(schema_name=schema_name).exists():
            raise serializers.ValidationError({
                "workspace": f"A tenant with workspace name '{schema_name}' already exists"
            })
        
        # Use schema_name as domain if domain not provided
        if not domain:
            domain = f"{schema_name}.localhost"
        
        # Get owner user
        request = self.context.get("request")
        if owner_email:
            owner_email = owner_email.strip().lower()
            owner = User.objects.filter(email__iexact=owner_email).first()
            if owner is None:
                owner_id_number = f"OWNER-{uuid.uuid4().hex[:12]}"
                owner = User.objects.create(
                    email=owner_email,
                    username=f"owner_{uuid.uuid4().hex[:12]}",
                    id_number=owner_id_number,
                    account_type=UserAccountType.GLOBAL,
                    role=Roles.ADMIN,
                    is_active=True,
                    is_default_password=True,
                )
                owner.set_password(owner_id_number)
                owner.save(update_fields=["password"])
        elif request and request.user.is_authenticated:
            owner = request.user
        else:
            # Try to get or create a default admin user
            owner, _ = User.objects.get_or_create(
                email='admin@example.com',
                defaults={
                    'id_number': 'admin001',
                    'username': 'admin',
                    'first_name': 'System',
                    'last_name': 'Admin'
                }
            )
        
        # Prepare tenant data with all profile fields
        tenant_data = {
            "name": name,
            "short_name": short_name,
            "schema_name": schema_name,
            "owner": owner,
            # Identity fields
            "funding_type": validated_data.get("funding_type"),
            "school_type": validated_data.get("school_type"),
            "slogan": validated_data.get("slogan"),
            "emis_number": validated_data.get("emis_number"),
            "description": validated_data.get("description"),
            "date_est": validated_data.get("date_est"),
            # Address fields
            "address": validated_data.get("address"),
            "city": validated_data.get("city"),
            "state": validated_data.get("state"),
            "country": validated_data.get("country"),
            "postal_code": validated_data.get("postal_code"),
            # Contact fields
            "phone": validated_data.get("phone"),
            "email": validated_data.get("email"),
            "website": validated_data.get("website"),
            # Status and configuration
            # Always start in onboarding state; keep workspace active so
            # owner activation/auth flows can run before full provisioning.
            "status": Tenant.STATUS_PENDING,
            "active": True,
            "maintenance_mode": validated_data.get("maintenance_mode", False),
            "login_access_policy": validated_data.get("login_access_policy", "all_users"),
            "disabled_access_allow_tenant_admins": validated_data.get("disabled_access_allow_tenant_admins", True),
            "disabled_access_allowed_paths": validated_data.get("disabled_access_allowed_paths", []),
            "disabled_access_allowed_users": validated_data.get("disabled_access_allowed_users", []),
            # Branding
            "logo_shape": validated_data.get("logo_shape", "square"),
            "theme_color": validated_data.get("theme_color"),
        }
        
        # Add id_number if provided
        if validated_data.get("id_number"):
            tenant_data["id_number"] = validated_data["id_number"]
        
        # Remove None values to use model defaults
        tenant_data = {k: v for k, v in tenant_data.items() if v is not None}
        
        # Create the tenant
        tenant = Tenant.objects.create(**tenant_data)
        
        # Create domain for the tenant
        domain_obj = Domain.objects.create(
            domain=domain,
            tenant=tenant,
            is_primary=True,
        )
        
        # Automatically add owner as superuser to the new tenant
        with schema_context(tenant.schema_name):
            permissions, _ = UserTenantPermissions.objects.get_or_create(
                profile=owner,
                defaults={"is_superuser": True, "is_staff": True},
            )
            if not permissions.is_superuser or not permissions.is_staff:
                permissions.is_superuser = True
                permissions.is_staff = True
                permissions.save(update_fields=["is_superuser", "is_staff"])
            owner.tenants.add(tenant)
        
        # Add all superadmin users to the new tenant
        # Superadmins should have access to all tenants
        try:
            from common.status import Roles
            superadmin_users = User.objects.filter(role=Roles.SUPERADMIN)
            with schema_context(tenant.schema_name):
                for superadmin in superadmin_users:
                    # Skip if already added (e.g., if owner is also a superadmin)
                    if superadmin.id != owner.id:
                        tenant.add_user(superadmin, is_superuser=True, is_staff=True)
        except Exception as e:
            # Log the error but don't fail tenant creation
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to add superadmin users to tenant {tenant.name}: {e}")
        
        # Generate the initial onboarding plan and set status to pending.
        # Workspace provisioning (default data) now happens later via the
        # onboarding wizard POST /onboarding/apply/ endpoint.
        try:
            from defaults.services import build_initial_plan
            tenant.onboarding_plan = build_initial_plan(tenant)
            tenant.save(update_fields=["onboarding_plan"])
        except Exception as e:
            logger.error(f"Failed to generate onboarding plan for tenant {tenant.name}: {e}")

        # Keep CRM records in sync with newly created workspaces.
        try:
            _sync_signup_request_after_tenant_create(
                tenant=tenant,
                owner=owner,
                signup_request_id=signup_request_id,
                request=request,
                actor=request.user if request and getattr(request.user, "is_authenticated", False) else None,
            )
        except Exception as e:
            logger.warning(
                "Failed to sync signup request for workspace %s: %s",
                tenant.schema_name,
                e,
            )
        
        # Store domain for response
        self._domain = domain_obj
        
        return tenant
    
    def to_representation(self, instance):
        """Return tenant data with domain and workspace information"""
        data = TenantSerializer(instance, context=self.context).data
        # Add workspace alias (same as schema_name)
        data['workspace'] = instance.schema_name
        if hasattr(self, '_domain'):
            data['domain'] = self._domain.domain
            data['domain_id'] = self._domain.id
        return data


class TenantInfoSearchResultSerializer(serializers.Serializer):
    """
    Serializer for tenant information search results.
    
    Used to format search results when querying by email, phone, or id_number
    across User, Student, and Staff models.
    """
    user_type = serializers.CharField(help_text="Type of user: user, student, or staff")
    tenant = serializers.DictField(allow_null=True, help_text="Tenant information (null for users in public schema)")
    data = serializers.DictField(help_text="User/Student/Staff data")


class SignupRequestCreateSerializer(serializers.ModelSerializer):
    """Public marketing signup form (write-only)."""

    class Meta:
        model = SignupRequest
        fields = [
            "first_name", "last_name", "email", "phone",
            "school_name", "role_title", "country", "students_count",
            "workspace_slug", "plan", "notes",
        ]


class SignupRequestAdminSerializer(serializers.ModelSerializer):
    """Admin list/detail/update for signup requests."""

    linked_tenant_schema_name = serializers.SerializerMethodField()
    linked_tenant_status = serializers.SerializerMethodField()
    linked_tenant_active = serializers.SerializerMethodField()
    can_email_owner = serializers.SerializerMethodField()
    owner_email = serializers.SerializerMethodField()
    owner_activation_ready_reason = serializers.SerializerMethodField()

    class Meta:
        model = SignupRequest
        fields = [
            "id",
            "first_name", "last_name", "email", "phone",
            "school_name", "role_title", "country", "students_count",
            "workspace_slug", "plan", "notes",
            "status", "submitted_at",
            "linked_tenant_schema_name", "linked_tenant_status", "linked_tenant_active",
            "can_email_owner", "owner_email", "owner_activation_ready_reason",
        ]
        read_only_fields = ["id", "submitted_at"]

    def get_linked_tenant_schema_name(self, obj):
        tenant = get_signup_request_linked_tenant(obj)
        return tenant.schema_name if tenant else ""

    def get_linked_tenant_status(self, obj):
        tenant = get_signup_request_linked_tenant(obj)
        return tenant.status if tenant else ""

    def get_linked_tenant_active(self, obj):
        tenant = get_signup_request_linked_tenant(obj)
        return bool(getattr(tenant, "active", False)) if tenant else False

    def get_can_email_owner(self, obj):
        tenant = get_signup_request_linked_tenant(obj)
        owner = get_signup_request_owner(tenant, obj)
        return bool(tenant and owner and owner.email)

    def get_owner_email(self, obj):
        tenant = get_signup_request_linked_tenant(obj)
        owner = get_signup_request_owner(tenant, obj)
        return owner.email if owner and owner.email else ""

    def get_owner_activation_ready_reason(self, obj):
        tenant = get_signup_request_linked_tenant(obj)
        if not tenant:
            return "Workspace has not been created yet."
        owner = get_signup_request_owner(tenant, obj)
        if not owner or not owner.email:
            return "No tenant owner account is linked yet."
        return ""


# Backwards-compatible alias
SignupRequestSerializer = SignupRequestCreateSerializer


class ContactInquirySerializer(serializers.Serializer):
    """Public marketing contact form (email only — not persisted)."""

    TOPIC_CHOICES = [
        ("general", "General question"),
        ("sales", "Sales & pricing"),
        ("support", "Existing customer support"),
        ("migration", "Data migration"),
    ]

    name = serializers.CharField(max_length=120)
    email = serializers.EmailField()
    school_name = serializers.CharField(required=False, allow_blank=True, max_length=200)
    topic = serializers.ChoiceField(choices=TOPIC_CHOICES)
    message = serializers.CharField(max_length=5000)
