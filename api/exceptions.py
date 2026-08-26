"""
Custom exception handlers for REST API
"""
from django.http import Http404
from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status

from common.api_response import detail_from_error


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
    
    if response is not None:
        response.data = {"detail": detail_from_error(response.data)}
        
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

