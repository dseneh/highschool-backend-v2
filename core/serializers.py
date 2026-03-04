"""
Serializers for core models (Tenant)
"""
from rest_framework import serializers
from core.models import Tenant, Domain
from django_tenants.utils import schema_context


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
        if instance.logo and hasattr(instance.logo, 'url'):
            if request:
                return request.build_absolute_uri(instance.logo.url)
            return instance.logo.url
        # default_path = '/media/images/default-logo.png'
        # return request.build_absolute_uri(default_path) if request else default_path
        return None


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
            "schema_name",
            "name",
            "short_name",
            "logo",
            "theme_color",
            "domains",
            "domain",
            "active",
            "status",
            "logo_shape",
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
            "theme_config",
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
    active = serializers.BooleanField(default=True)

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
        Create a new Tenant with domain.
        
        This should be called from a view that ensures we're in the public schema.
        Accepts all tenant profile fields for complete tenant setup.
        """
        from core.models import Tenant, Domain
        from users.models import User

        # Required fields
        name = validated_data["name"]
        short_name = validated_data.get("short_name") or name[:10]
        workspace = validated_data.get("workspace")
        schema_name = validated_data.get("schema_name")
        domain = validated_data.get("domain")
        owner_email = validated_data.get("owner_email")
        
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
                "schema_name": f"A tenant with schema name '{schema_name}' already exists"
            })
        
        # Use schema_name as domain if domain not provided
        if not domain:
            domain = f"{schema_name}.localhost"
        
        # Get owner user
        request = self.context.get("request")
        if owner_email:
            try:
                owner = User.objects.get(email=owner_email)
            except User.DoesNotExist:
                raise serializers.ValidationError(f"User with email '{owner_email}' does not exist")
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
            "status": validated_data.get("status", "active"),
            "active": validated_data.get("active", True),
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
            tenant.add_user(owner, is_superuser=True, is_staff=True)
        
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
        
        # Initialize default data for the tenant (academic years, divisions, etc.)
        try:
            from defaults.utils import setup_tenant_defaults
            setup_tenant_defaults(tenant, owner)
        except Exception as e:
            # Log the error but don't fail tenant creation
            # The tenant is created but default data initialization failed
            # This allows manual retry or fixing the issue
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to initialize default data for tenant {tenant.name}: {e}")
            # Optionally, you could raise this exception to rollback tenant creation
            # raise serializers.ValidationError(f"Tenant created but default data initialization failed: {e}")
        
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

