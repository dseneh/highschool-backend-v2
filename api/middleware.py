"""
Custom middleware for multi-tenant application
"""

from django_tenants.middleware.main import TenantMainMiddleware
from django_tenants.utils import get_public_schema_name
from django.http import Http404
from core.models import Tenant
from rest_framework_simplejwt.authentication import JWTAuthentication


class HeaderBasedTenantMiddleware(TenantMainMiddleware):
    """
    Custom middleware that extracts tenant from X-Tenant or X-Workspace header
    instead of subdomain. Based on django-tenants' TenantMainMiddleware.
    
    This allows the frontend to handle subdomain routing while the backend
    identifies tenants via HTTP headers.
    
    Usage:
    - Frontend sends: X-Tenant: tenantabc
    - Middleware looks up Tenant by schema_name or domain
    - Switches to that tenant's schema
    - Special case: X-Tenant: admin → routes to public schema (for global users)
    - If no header provided, falls back to public schema for auth endpoints
    """

    BLOCKED_TENANT_ALLOWED_PATHS = {
        '/api/v1/auth/login/',
        '/api/v1/auth/token/refresh/',
        '/api/v1/auth/verify/',
        '/api/v1/auth/users/current/',
        '/api/v1/auth/password/forgot/',
        '/api/v1/auth/password/reset/',
        '/api/v1/tenants/current/',
    }

    def _blocked_tenant_response(self, detail: str, error_code: str, status_code: int = 423):
        from django.http import JsonResponse

        return JsonResponse(
            {
                'detail': detail,
                'error_code': error_code,
            },
            status=status_code,
            json_dumps_params={'ensure_ascii': False},
        )

    def _is_blocked_tenant_path_allowed(self, path: str) -> bool:
        return path in self.BLOCKED_TENANT_ALLOWED_PATHS

    @staticmethod
    def _normalize_frontend_path(path: str) -> str:
        value = str(path or "").strip()
        if not value:
            return ""
        if not value.startswith('/'):
            value = f'/{value}'
        return value if value == '/' else value.rstrip('/')

    @staticmethod
    def _is_allowed_path(path: str, allowed_prefixes) -> bool:
        normalized_path = HeaderBasedTenantMiddleware._normalize_frontend_path(path)
        if not normalized_path:
            return False

        for prefix in (allowed_prefixes or []):
            normalized_prefix = HeaderBasedTenantMiddleware._normalize_frontend_path(prefix)
            if not normalized_prefix:
                continue
            if normalized_prefix == '/':
                if normalized_path == '/':
                    return True
                continue
            if normalized_prefix.endswith('-'):
                if normalized_path.startswith(normalized_prefix):
                    return True
                continue
            if normalized_path == normalized_prefix or normalized_path.startswith(f"{normalized_prefix}/"):
                return True

        return False

    def _resolve_api_user(self, request):
        try:
            auth_result = JWTAuthentication().authenticate(request)
        except Exception:
            return None
        if not auth_result:
            return None
        user, _ = auth_result
        return user

    def _is_disabled_override_allowed(self, request, tenant) -> bool:
        frontend_path = request.META.get('HTTP_X_APP_PATH', '')
        allowed_paths = getattr(tenant, 'disabled_access_allowed_paths', []) or []

        if not self._is_allowed_path(frontend_path, allowed_paths):
            return False

        user = self._resolve_api_user(request)
        if not user:
            return False

        role = str(getattr(user, 'role', '') or '').lower()
        is_tenant_admin = bool(getattr(user, 'is_superuser', False)) or role in {'admin', 'superadmin'}
        allow_tenant_admins = bool(getattr(tenant, 'disabled_access_allow_tenant_admins', True))

        allowed_users = {
            str(value or '').strip().lower()
            for value in (getattr(tenant, 'disabled_access_allowed_users', []) or [])
            if str(value or '').strip()
        }

        candidates = {
            str(getattr(user, 'id', '') or '').strip().lower(),
            str(getattr(user, 'id_number', '') or '').strip().lower(),
            str(getattr(user, 'username', '') or '').strip().lower(),
            str(getattr(user, 'email', '') or '').strip().lower(),
        }
        candidates.discard('')

        is_selected_user = bool(allowed_users.intersection(candidates))
        return (allow_tenant_admins and is_tenant_admin) or is_selected_user

    def _enforce_tenant_runtime_controls(self, request):
        path = request.path
        if not path.startswith('/api/'):
            return None

        tenant = getattr(request, 'tenant', None)
        if not tenant:
            return None

        public_schema = get_public_schema_name()
        if getattr(tenant, 'schema_name', None) == public_schema:
            return None

        if self._is_blocked_tenant_path_allowed(path):
            return None

        is_disabled = not getattr(tenant, 'active', True)
        is_non_operational = getattr(tenant, 'status', 'active') != 'active'

        if is_disabled or is_non_operational:
            if self._is_disabled_override_allowed(request, tenant):
                return None

        if is_disabled:
            return self._blocked_tenant_response(
                'This workspace is disabled. Tenant operations are currently blocked.',
                'TENANT_DISABLED',
            )

        if is_non_operational:
            return self._blocked_tenant_response(
                f"This workspace is currently {tenant.status}. Tenant operations are currently blocked.",
                'TENANT_STATUS_BLOCKED',
            )

        if getattr(tenant, 'maintenance_mode', False):
            return self._blocked_tenant_response(
                'This workspace is currently in maintenance mode. Tenant operations are temporarily paused.',
                'TENANT_MAINTENANCE_MODE',
            )

        return None
    
    def process_request(self, request):
        """
        Store request for use in get_tenant method.
        Catch exceptions from get_tenant and handle them for API endpoints.
        """
        # Skip OPTIONS requests (CORS preflight) - let CORS middleware handle them
        if request.method == 'OPTIONS':
            return None
        
        # Skip tenant resolution for liveness endpoints
        if request.path == '/' or request.path.startswith('/health'):
            return None
        
        # Skip tenant resolution for media files in DEBUG mode
        if request.path.startswith('/media/'):
            return None
        
        self.request = request
        try:
            response = super().process_request(request)
            if response is not None:
                return response

            return self._enforce_tenant_runtime_controls(request)
        except Exception as exc:
            # If it's an API endpoint and we have a DRF or Http404 exception, handle it
            if request.path.startswith('/api/'):
                from rest_framework.exceptions import APIException
                from django.http import JsonResponse, Http404
                from rest_framework import status
                
                # Handle DRF exceptions (like NotFound)
                if isinstance(exc, APIException):
                    detail = exc.detail
                    if isinstance(detail, list):
                        detail = detail[0] if detail else "An error occurred"
                    elif not isinstance(detail, str):
                        detail = str(detail)
                    
                    error_code = getattr(exc, 'default_code', getattr(exc, 'code', 'ERROR'))
                    return JsonResponse(
                        {
                            "detail": detail,
                            "error_code": error_code,
                        },
                        status=exc.status_code,
                        json_dumps_params={'ensure_ascii': False}
                    )
                
                # Handle Http404
                if isinstance(exc, Http404):
                    return JsonResponse(
                        {
                            "detail": str(exc),
                            "error_code": "NOT_FOUND",
                        },
                        status=status.HTTP_404_NOT_FOUND,
                        json_dumps_params={'ensure_ascii': False}
                    )
            
            # Re-raise other exceptions
            raise
    
    def get_tenant(self, domain_model, hostname):
        """
        Override get_tenant to check X-Tenant header first,
        then fall back to standard subdomain lookup or public schema.
        
        Args:
            domain_model: The Domain model class
            hostname: The request hostname
            
        Returns:
            Tenant instance or raises Http404
        """
        # Access request from instance (set in process_request)
        request = getattr(self, 'request', None)
        
        if request:
            def _is_public_path(path: str) -> bool:
                return (
                    path.startswith('/admin/')
                    or path.startswith('/api/v1/auth')
                    or path.startswith('/api/v1/tenants')
                    or path.startswith('/api/v1/search')
                    or path in ('/', '/health', '/health/')
                )

            # Tenant management endpoints (retrieving tenant info) should ignore x-tenant header
            # and always work in public schema
            path = request.path
            if path.startswith('/api/v1/tenants/'):
                # For tenant-specific retrieval endpoints like GET /api/v1/tenants/ldtc/
                # Always use public schema, regardless of x-tenant header
                try:
                    public_schema = get_public_schema_name()
                    return Tenant.objects.get(schema_name=public_schema)
                except Tenant.DoesNotExist:
                    # If public tenant doesn't exist, fall through to parent
                    pass
            
            # Try header first (for frontend-driven routing)
            tenant_header = request.META.get('HTTP_X_TENANT') or request.META.get('HTTP_X_WORKSPACE')

            # Tenant-scoped API routes must provide tenant context explicitly.
            # Falling back to hostname can resolve to public schema and cause
            # runtime errors when tenant tables (e.g., employee) are queried.
            if path.startswith('/api/') and not _is_public_path(path) and not tenant_header:
                from rest_framework.exceptions import NotFound
                raise NotFound(
                    detail="Missing tenant context. Provide a valid X-Tenant header.",
                    code="tenant_header_required"
                )
            
            if tenant_header:
                # Special case: "admin" is an alias for the public schema
                if tenant_header.lower() == 'admin':
                    try:
                        public_schema = get_public_schema_name()
                        return Tenant.objects.get(schema_name=public_schema)
                    except Tenant.DoesNotExist:
                        from rest_framework.exceptions import NotFound
                        raise NotFound(
                            detail="Public schema (admin) not found.",
                            code="tenant_not_found"
                        )
                
                try:
                    # Option 1: Look up by schema_name (most direct)
                    # schema_name is typically lowercase alphanumeric
                    tenant = Tenant.objects.get(schema_name=tenant_header.lower())
                    return tenant
                except Tenant.DoesNotExist:
                    try:
                        # Option 2: Look up by domain
                        # For backward compatibility with workspace field
                        domain = domain_model.objects.select_related('tenant').get(
                            domain__icontains=tenant_header
                        )
                        return domain.tenant
                    except domain_model.DoesNotExist:
                        # If header is provided but tenant not found, raise 404 with detailed message
                        # The custom exception handler will convert this to JSON
                        from rest_framework.exceptions import NotFound
                        raise NotFound(
                            detail=f"The value of '{tenant_header}' is not a valid tenant workspace.",
                            code="tenant_not_found"
                        )
            
            # If no tenant header provided, only allow known public endpoints on public schema.
            # Tenant-scoped API requests should not silently fall back to public schema.
            path = request.path
            if _is_public_path(path):
                try:
                    public_schema = get_public_schema_name()
                    return Tenant.objects.get(schema_name=public_schema)
                except Tenant.DoesNotExist:
                    # If public tenant doesn't exist, fall through to parent
                    pass
        
        # Fallback to standard subdomain-based lookup
        # This handles cases where header is not provided and it's not an auth endpoint
        try:
            return super().get_tenant(domain_model, hostname)
        except Http404:
            # For tenant-scoped API endpoints, fail fast instead of using public fallback.
            if request and request.path.startswith('/api/'):
                from rest_framework.exceptions import NotFound
                raise NotFound(
                    detail="Missing or invalid tenant context. Provide a valid X-Tenant header.",
                    code="tenant_header_required"
                )

            # Non-API requests can still use public fallback as a safe default.
            try:
                public_schema = get_public_schema_name()
                return Tenant.objects.get(schema_name=public_schema)
            except Tenant.DoesNotExist:
                # Re-raise the original 404 if public schema also doesn't exist
                # Check if this is an API endpoint to return JSON response
                if request and request.path.startswith('/api/'):
                    from rest_framework.exceptions import NotFound
                    raise NotFound(
                        detail="No tenant found and public schema does not exist. Please provide a valid X-Tenant header.",
                        code="tenant_not_found"
                    )
                else:
                    raise Http404("No tenant found and public schema does not exist")
    
    def process_exception(self, request, exception):
        """
        Handle exceptions raised during tenant resolution.
        Convert DRF exceptions to JSON responses for API endpoints.
        
        This is called when an exception is raised during request processing,
        including exceptions from get_tenant during process_request.
        """
        from rest_framework.exceptions import NotFound, APIException
        from django.http import JsonResponse
        from rest_framework import status
        
        # Only handle exceptions for API endpoints
        if not request.path.startswith('/api/'):
            return None  # Let Django handle non-API exceptions
        
        # Handle DRF exceptions (like NotFound from get_tenant)
        if isinstance(exception, APIException):
            # Get detail - it might be a string or a list
            detail = exception.detail
            if isinstance(detail, list):
                detail = detail[0] if detail else "An error occurred"
            elif not isinstance(detail, str):
                detail = str(detail)
            
            # Get error code from exception or use default
            error_code = getattr(exception, 'default_code', getattr(exception, 'code', 'ERROR'))
            
            # Return JSON response using JsonResponse for proper content-type
            return JsonResponse(
                {
                    "detail": detail,
                    "error_code": error_code,
                },
                status=exception.status_code,
                json_dumps_params={'ensure_ascii': False}
            )
        
        # Handle Http404 exceptions for API endpoints
        if isinstance(exception, Http404):
            return JsonResponse(
                {
                    "detail": str(exception),
                    "error_code": "NOT_FOUND",
                },
                status=status.HTTP_404_NOT_FOUND,
                json_dumps_params={'ensure_ascii': False}
            )
        
        # Let other exceptions be handled normally (will go to DRF exception handler)
        return None

