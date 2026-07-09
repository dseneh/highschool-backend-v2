"""
Serializers for core models (Tenant)
"""
from rest_framework import serializers
from core.models import Tenant, Domain, SignupRequest
from core.utils import resolve_tenant_logo_media_url


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
    provisioning_step_label = serializers.SerializerMethodField()
    deletion_step_label = serializers.SerializerMethodField()

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
            "provisioning_status",
            "provisioning_step",
            "provisioning_step_label",
            "provisioning_progress",
            "provisioning_error",
            "deletion_status",
            "deletion_mode",
            "deletion_step",
            "deletion_step_label",
            "deletion_progress",
            "deletion_error",
            "created_at",
        ]
        read_only_fields = fields

    def get_provisioning_step_label(self, obj):
        from core.tenant_provisioning import get_provisioning_step_label

        step = getattr(obj, "provisioning_step", "") or ""
        if not step:
            return None
        return get_provisioning_step_label(step)

    def get_deletion_step_label(self, obj):
        from core.tenant_deletion import get_deletion_step_label

        step = getattr(obj, "deletion_step", "") or ""
        if not step:
            return None
        return get_deletion_step_label(step)

class PublicTenantSerializer(BaseTenantSerializer):
    """
    Public serializer for Tenant model (no authentication required).
    Used for tenant discovery, routing, and branding before login.
    Includes basic tenant information needed for frontend routing and branding.
    Only active tenants are returned (filtered in get_queryset).
    """
    billing_summary = serializers.SerializerMethodField()

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
            "billing_summary",
        ]
        read_only_fields = fields

    def get_billing_summary(self, obj):
        from billing.services.state import billing_summary_dict

        request = self.context.get("request")
        user = getattr(request, "user", None) if request else None
        authenticated = bool(user and getattr(user, "is_authenticated", False))
        if not authenticated:
            return billing_summary_dict(obj, for_banner=False, scope="public")

        from billing.permissions import user_is_platform_superadmin, user_is_tenant_admin

        if user_is_platform_superadmin(user):
            return billing_summary_dict(obj, for_banner=True, scope="platform")

        if user_is_tenant_admin(user):
            return billing_summary_dict(obj, for_banner=True, scope="tenant_admin")

        return billing_summary_dict(obj, for_banner=False, scope="public")

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
            # Billing (platform admin)
            "complimentary_until",
            "complimentary_note",
            "stripe_customer_id",
            "stripe_subscription_id",
            "subscription_status",
            "billing_interval",
            "current_period_end",
            "past_due_since",
            "enabled_addons",
            "promotion_code_redeemed",
            "billing_enrollment_count",
            "billing_employee_count",
            # Branding
            "logo",
            "logo_shape",
            "theme_color",
            "theme_config",
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
    admin_first_name = serializers.CharField(max_length=100, required=False, allow_blank=True)
    admin_last_name = serializers.CharField(max_length=100, required=False, allow_blank=True)
    admin_email = serializers.EmailField(required=False, allow_blank=True)
    admin_username = serializers.CharField(max_length=150, required=False, allow_blank=True)
    admin_password = serializers.CharField(
        max_length=128,
        required=False,
        allow_blank=True,
        write_only=True,
        min_length=6,
    )

    def validate(self, attrs):
        admin_fields = (
            "admin_first_name",
            "admin_last_name",
            "admin_email",
            "admin_username",
            "admin_password",
        )
        provided = [attrs.get(field) for field in admin_fields]
        if any(provided) and not all(provided):
            raise serializers.ValidationError(
                {
                    field: "All admin account fields are required when creating a tenant."
                    for field in admin_fields
                    if not attrs.get(field)
                }
            )

        admin_email = (attrs.get("admin_email") or "").strip()
        admin_username = (attrs.get("admin_username") or "").strip()
        if admin_email and admin_username:
            from core.tenant_admin import validate_tenant_admin_account

            validate_tenant_admin_account(email=admin_email, username=admin_username)

        admin_password = attrs.get("admin_password") or ""
        admin_confirm = self.initial_data.get("admin_confirm_password") or ""
        if admin_password and admin_confirm and admin_password != admin_confirm:
            raise serializers.ValidationError(
                {"admin_confirm_password": "Passwords do not match."}
            )

        return attrs

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
        Create a tenant record and enqueue background workspace provisioning.

        The tenant appears in the admin list immediately while schema
        creation, migrations, and default data run asynchronously.
        """
        from core.models import Tenant
        from core.tenant_admin import resolve_or_create_tenant_admin_user
        from core.tenant_provisioning import enqueue_tenant_provisioning
        from users.models import User

        name = validated_data["name"]
        short_name = validated_data.get("short_name") or name[:10]
        schema_name = validated_data.get("schema_name")
        domain = validated_data.get("domain")

        admin_first_name = (validated_data.get("admin_first_name") or "").strip()
        admin_last_name = (validated_data.get("admin_last_name") or "").strip()
        admin_email = (validated_data.get("admin_email") or "").strip()
        admin_username = (validated_data.get("admin_username") or "").strip()
        admin_password = validated_data.get("admin_password") or ""

        if not all([admin_first_name, admin_last_name, admin_email, admin_username, admin_password]):
            raise serializers.ValidationError(
                {
                    "admin_email": "Tenant admin account details are required.",
                }
            )

        if not schema_name:
            schema_name = short_name.lower().replace(" ", "_").replace("-", "_")
            schema_name = "".join(c for c in schema_name if c.isalnum() or c == "_")

        if Tenant.objects.filter(schema_name=schema_name).exists():
            raise serializers.ValidationError(
                {"schema_name": f"A tenant with schema name '{schema_name}' already exists"}
            )

        if not domain:
            domain = f"{schema_name}.localhost"

        request = self.context.get("request")
        placeholder_owner = None
        if request and request.user.is_authenticated:
            placeholder_owner = request.user
        else:
            placeholder_owner = User.objects.filter(role="superadmin").first()
        if placeholder_owner is None:
            raise serializers.ValidationError(
                {"detail": "Unable to determine platform owner for tenant record."}
            )

        desired_active = validated_data.get("active", True)
        desired_status = validated_data.get("status", "active")

        tenant_data = {
            "name": name,
            "short_name": short_name,
            "schema_name": schema_name,
            "owner": placeholder_owner,
            "funding_type": validated_data.get("funding_type"),
            "school_type": validated_data.get("school_type"),
            "slogan": validated_data.get("slogan"),
            "emis_number": validated_data.get("emis_number"),
            "description": validated_data.get("description"),
            "date_est": validated_data.get("date_est"),
            "address": validated_data.get("address"),
            "city": validated_data.get("city"),
            "state": validated_data.get("state"),
            "country": validated_data.get("country"),
            "postal_code": validated_data.get("postal_code"),
            "phone": validated_data.get("phone"),
            "email": validated_data.get("email"),
            "website": validated_data.get("website"),
            "status": "inactive",
            "active": False,
            "maintenance_mode": validated_data.get("maintenance_mode", False),
            "login_access_policy": validated_data.get("login_access_policy", "all_users"),
            "disabled_access_allow_tenant_admins": validated_data.get(
                "disabled_access_allow_tenant_admins", True
            ),
            "disabled_access_allowed_paths": validated_data.get(
                "disabled_access_allowed_paths", []
            ),
            "disabled_access_allowed_users": validated_data.get(
                "disabled_access_allowed_users", []
            ),
            "logo_shape": validated_data.get("logo_shape", "square"),
            "theme_color": validated_data.get("theme_color"),
            "provisioning_status": "queued",
            "provisioning_step": "",
            "provisioning_progress": 0,
            "provisioning_error": "",
            "provisioning_completed_steps": [],
            "provisioning_payload": {
                "domain": domain,
                "desired_active": desired_active,
                "desired_status": desired_status,
            },
        }

        if validated_data.get("id_number"):
            tenant_data["id_number"] = validated_data["id_number"]

        tenant_data = {k: v for k, v in tenant_data.items() if v is not None}

        tenant = Tenant(**tenant_data)
        tenant.auto_create_schema = False
        tenant._skip_async_default_setup = True
        tenant.save()

        admin_user, admin_user_created = resolve_or_create_tenant_admin_user(
            tenant=tenant,
            first_name=admin_first_name,
            last_name=admin_last_name,
            email=admin_email,
            username=admin_username,
            password=admin_password,
        )
        tenant.owner = admin_user
        tenant.provisioning_payload = {
            **(tenant.provisioning_payload or {}),
            "admin_user_id": str(admin_user.pk),
            "admin_user_created": admin_user_created,
            "admin_password": admin_password if admin_user_created else "",
        }
        tenant.save(update_fields=["owner", "provisioning_payload", "updated_at"])

        self._domain = domain
        enqueue_tenant_provisioning(tenant.schema_name)
        return tenant
    
    def to_representation(self, instance):
        """Return tenant data with domain and workspace information"""
        data = TenantSerializer(instance, context=self.context).data
        data["workspace"] = instance.schema_name
        payload = instance.provisioning_payload or {}
        planned_domain = payload.get("domain")
        if planned_domain and not data.get("domain"):
            data["domain"] = planned_domain
        if hasattr(self, "_domain"):
            if isinstance(self._domain, str):
                data["domain"] = self._domain
            else:
                data["domain"] = self._domain.domain
                data["domain_id"] = self._domain.id
        data["provisioning_status"] = instance.provisioning_status
        data["provisioning_step"] = instance.provisioning_step
        data["provisioning_progress"] = instance.provisioning_progress
        data["provisioning_error"] = instance.provisioning_error
        from core.tenant_provisioning import get_provisioning_step_label

        if instance.provisioning_step:
            data["provisioning_step_label"] = get_provisioning_step_label(
                instance.provisioning_step
            )
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

    class Meta:
        model = SignupRequest
        fields = [
            "id",
            "first_name", "last_name", "email", "phone",
            "school_name", "role_title", "country", "students_count",
            "workspace_slug", "plan", "notes",
            "status", "submitted_at",
        ]
        read_only_fields = ["id", "submitted_at"]


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

