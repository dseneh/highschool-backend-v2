"""
Custom middleware for multi-tenant application
"""

from django_tenants.middleware.main import TenantMainMiddleware
from django_tenants.utils import get_public_schema_name
from django.http import Http404
from core.models import Tenant


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
    
    def process_request(self, request):
        """
        Store request for use in get_tenant method.
        Catch exceptions from get_tenant and handle them for API endpoints.
        """
        # Skip OPTIONS requests (CORS preflight) - let CORS middleware handle them
        if request.method == 'OPTIONS':
            return None
        
        # Skip tenant resolution for the health check endpoint
        if request.path.startswith('/health'):
            return None
        
        # Skip tenant resolution for media files in DEBUG mode
        if request.path.startswith('/media/'):
            return None
        
        self.request = request
        try:
            return super().process_request(request)
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
            
            # If no header provided, check if this is an auth or tenant management endpoint
            # Auth endpoints and tenant management endpoints should work in public schema
            # Search endpoint is also public and should work without tenant header
            path = request.path
            if ('auth' in path or 
                path.startswith('/admin/') or 
                path.startswith('/api/v1/tenants') or 
                path.startswith('/api/v1/search')):
                # Return public tenant for authentication, tenant management, and search endpoints
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
            # If subdomain lookup fails and no header, try public schema as last resort
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

