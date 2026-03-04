"""
Custom exception handlers for REST API
"""
from django.http import Http404
from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status


def custom_exception_handler(exc, context):
    """
    Custom exception handler that returns JSON responses for API errors.
    Normalizes all validation errors to use 'detail' field format.
    
    Handles:
    - DRF exceptions (ValidationError, NotFound, PermissionDenied, etc.)
    - Django Http404 exceptions
    - Server errors
    
    All errors are normalized to: {"detail": "error message"}
    """
    # Call REST framework's default exception handler first
    response = exception_handler(exc, context)
    
    # Normalize validation errors to use 'detail' field
    if response is not None:
        # Check if we have field errors or non_field_errors
        if isinstance(response.data, dict):
            # Handle field-specific validation errors
            if any(isinstance(v, list) for v in response.data.values()):
                # Extract error message with field name for better context
                error_message = None
                error_field = None
                
                for key, value in response.data.items():
                    if isinstance(value, list) and value:
                        error_field = key
                        error_message = value[0] if isinstance(value[0], str) else str(value[0])
                        break
                
                if error_message:
                    # Include field name in the message for clarity
                    if error_field and error_field != "non_field_errors":
                        error_message = f"{error_field}: {error_message}"
                    response.data = {"detail": error_message}
            
            # Handle non_field_errors
            elif "non_field_errors" in response.data:
                non_field_errors = response.data.get("non_field_errors", [])
                if non_field_errors:
                    error_message = (
                        non_field_errors[0] 
                        if isinstance(non_field_errors[0], str) 
                        else str(non_field_errors[0])
                    )
                    response.data = {"detail": error_message}
        
        return response
    
    # Handle Django Http404 exceptions (from middleware, etc.)
    if isinstance(exc, Http404):
        request = context.get('request', None)
        # Only return JSON for API endpoints
        if request and request.path.startswith('/api/'):
            return Response(
                {
                    "detail": str(exc),
                    "error_code": "NOT_FOUND",
                },
                status=status.HTTP_404_NOT_FOUND
            )
        # For non-API endpoints, let Django handle it (HTML 404 page)
        return None
    
    # For other unhandled exceptions, return JSON error for API endpoints
    request = context.get('request', None)
    if request and request.path.startswith('/api/'):
        return Response(
            {
                "detail": str(exc) if str(exc) else "An error occurred",
                "error_code": "SERVER_ERROR",
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    
    # Let Django handle non-API exceptions normally
    return None

