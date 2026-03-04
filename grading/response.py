"""
Standard response utilities for grading API endpoints.

Provides consistent response structure across all grading-related endpoints.
"""

from typing import Any, Dict, Optional, List
from rest_framework.response import Response
from rest_framework import status as http_status


class GradingResponse:
    """
    Standard response builder for grading API endpoints.
    
    Ensures consistent response structure across all grading endpoints.
    """
    
    @staticmethod
    def success(
        data: Optional[Any] = None,
        message: str = "Operation completed successfully",
        status: int = http_status.HTTP_200_OK,
        **extra_fields
    ) -> Response:
        """
        Build a successful response.
        
        Args:
            data: Response payload data
            message: Success message
            status: HTTP status code (default: 200)
            **extra_fields: Additional fields to include in response
            
        Returns:
            Response object with standardized structure
            
        Example:
            >>> GradingResponse.success(
            ...     data={'grading_style': 'single_entry'},
            ...     message='Settings updated'
            ... )
        """
        response_data = {
            'success': True,
            'detail': message,
            'data': data,
        }
        
        # Add any extra fields
        response_data.update(extra_fields)
        
        return Response(response_data, status=status)
    
    @staticmethod
    def error(
        message: str,
        errors: Optional[List[str]] = None,
        status: int = http_status.HTTP_400_BAD_REQUEST,
        error_code: Optional[str] = None,
        **extra_fields
    ) -> Response:
        """
        Build an error response.
        
        Args:
            message: Error message
            errors: List of detailed error messages
            status: HTTP status code (default: 400)
            error_code: Machine-readable error code
            **extra_fields: Additional fields to include in response
            
        Returns:
            Response object with standardized error structure
            
        Example:
            >>> GradingResponse.error(
            ...     message='Invalid grading style',
            ...     errors=['Must be single_entry or multiple_entry'],
            ...     error_code='INVALID_GRADING_STYLE'
            ... )
        """
        response_data = {
            'success': False,
            'detail': message,
            'errors': errors or [],
        }
        
        if error_code:
            response_data['error_code'] = error_code
        
        # Add any extra fields
        response_data.update(extra_fields)
        
        return Response(response_data, status=status)
    
    @staticmethod
    def async_task(
        task_id: str,
        status_url: str,
        message: str = "Task started in background",
        estimated_time_seconds: Optional[int] = None,
        **extra_fields
    ) -> Response:
        """
        Build an async task response (HTTP 202 ACCEPTED).
        
        Args:
            task_id: UUID of the background task
            status_url: URL to poll for task status
            message: Descriptive message
            estimated_time_seconds: Estimated completion time
            **extra_fields: Additional fields (e.g., section_count, grading_style_change)
            
        Returns:
            Response object with task information
            
        Example:
            >>> GradingResponse.async_task(
            ...     task_id='uuid',
            ...     status_url='/api/v1/tasks/uuid/',
            ...     estimated_time_seconds=180,
            ...     section_count=100
            ... )
        """
        response_data = {
            'success': True,
            'detail': message,
            'async': True,
            'task': {
                'id': task_id,
                'status_url': status_url,
                'estimated_time_seconds': estimated_time_seconds,
            }
        }
        
        # Add any extra fields
        response_data.update(extra_fields)
        
        return Response(response_data, status=http_status.HTTP_202_ACCEPTED)
    
    @staticmethod
    def task_status(
        task_id: str,
        status: str,
        progress: int,
        message: str,
        created_at: str,
        updated_at: str,
        result: Optional[Dict] = None,
        error: Optional[str] = None,
        **extra_fields
    ) -> Response:
        """
        Build a task status response.
        
        Args:
            task_id: UUID of the task
            status: Task status (pending/processing/completed/failed/cancelled)
            progress: Progress percentage (0-100)
            message: Human-readable status message
            created_at: ISO timestamp when task was created
            updated_at: ISO timestamp when task was last updated
            result: Task result data (when completed)
            error: Error message (when failed)
            **extra_fields: Additional fields
            
        Returns:
            Response object with task status
            
        Example:
            >>> GradingResponse.task_status(
            ...     task_id='uuid',
            ...     status='processing',
            ...     progress=45,
            ...     message='Processing gradebooks...',
            ...     created_at='2025-11-01T10:00:00Z',
            ...     updated_at='2025-11-01T10:01:30Z'
            ... )
        """
        response_data = {
            'success': True,
            'task': {
                'id': task_id,
                'status': status,
                'progress': progress,
                'detail': message,
                'created_at': created_at,
                'updated_at': updated_at,
            }
        }
        
        if result is not None:
            response_data['task']['result'] = result
        
        if error is not None:
            response_data['task']['error'] = error
        
        # Add any extra fields
        response_data.update(extra_fields)
        
        return Response(response_data, status=http_status.HTTP_200_OK)
    
    @staticmethod
    def validation_error(
        message: str,
        field_errors: Optional[Dict[str, List[str]]] = None,
        **extra_fields
    ) -> Response:
        """
        Build a validation error response.
        
        Args:
            message: General validation error message
            field_errors: Dictionary of field-specific errors
            **extra_fields: Additional fields
            
        Returns:
            Response object with validation errors
            
        Example:
            >>> GradingResponse.validation_error(
            ...     message='Validation failed',
            ...     field_errors={
            ...         'grading_style': ['This field is required'],
            ...         'force': ['Must be true to confirm']
            ...     }
            ... )
        """
        response_data = {
            'success': False,
            'detail': message,
            'error_code': 'VALIDATION_ERROR',
            'field_errors': field_errors or {},
        }
        
        # Add any extra fields
        response_data.update(extra_fields)
        
        return Response(response_data, status=http_status.HTTP_400_BAD_REQUEST)
    
    @staticmethod
    def not_found(
        message: str = "Resource not found",
        resource_type: Optional[str] = None,
        resource_id: Optional[str] = None
    ) -> Response:
        """
        Build a not found response.
        
        Args:
            message: Error message
            resource_type: Type of resource (e.g., 'task', 'school')
            resource_id: ID of the resource
            
        Returns:
            Response object with 404 status
            
        Example:
            >>> GradingResponse.not_found(
            ...     message='Task not found',
            ...     resource_type='task',
            ...     resource_id='uuid'
            ... )
        """
        response_data = {
            'success': False,
            'detail': message,
            'error_code': 'NOT_FOUND',
        }
        
        if resource_type:
            response_data['resource_type'] = resource_type
        
        if resource_id:
            response_data['resource_id'] = resource_id
        
        return Response(response_data, status=http_status.HTTP_404_NOT_FOUND)
    
    @staticmethod
    def forbidden(
        message: str = "Access forbidden",
        reason: Optional[str] = None
    ) -> Response:
        """
        Build a forbidden response.
        
        Args:
            message: Error message
            reason: Detailed reason for denial
            
        Returns:
            Response object with 403 status
            
        Example:
            >>> GradingResponse.forbidden(
            ...     message='Task does not belong to this school',
            ...     reason='School ID mismatch'
            ... )
        """
        response_data = {
            'success': False,
            'detail': message,
            'error_code': 'FORBIDDEN',
        }
        
        if reason:
            response_data['reason'] = reason
        
        return Response(response_data, status=http_status.HTTP_403_FORBIDDEN)
    
    @staticmethod
    def warning(
        message: str,
        data: Optional[Any] = None,
        warnings: Optional[List[str]] = None,
        requires_confirmation: bool = False,
        **extra_fields
    ) -> Response:
        """
        Build a warning response (requires user confirmation).
        
        Args:
            message: Warning message
            data: Data about what will happen
            warnings: List of specific warnings
            requires_confirmation: If True, requires explicit confirmation
            **extra_fields: Additional fields
            
        Returns:
            Response object with warning
            
        Example:
            >>> GradingResponse.warning(
            ...     message='This will delete all gradebooks',
            ...     warnings=['All existing grades will be lost'],
            ...     requires_confirmation=True,
            ...     confirmation_param='force',
            ...     current_grading_style='multiple_entry',
            ...     new_grading_style='single_entry'
            ... )
        """
        response_data = {
            'success': False,
            'detail': message,
            'error_code': 'REQUIRES_CONFIRMATION',
            'warnings': warnings or [],
            'requires_confirmation': requires_confirmation,
        }
        
        if data is not None:
            response_data['data'] = data
        
        # Add any extra fields
        response_data.update(extra_fields)
        
        return Response(response_data, status=http_status.HTTP_400_BAD_REQUEST)


# Convenience aliases for common patterns
def success_response(*args, **kwargs) -> Response:
    """Alias for GradingResponse.success()"""
    return GradingResponse.success(*args, **kwargs)


def error_response(*args, **kwargs) -> Response:
    """Alias for GradingResponse.error()"""
    return GradingResponse.error(*args, **kwargs)


def async_response(*args, **kwargs) -> Response:
    """Alias for GradingResponse.async_task()"""
    return GradingResponse.async_task(*args, **kwargs)


def task_status_response(*args, **kwargs) -> Response:
    """Alias for GradingResponse.task_status()"""
    return GradingResponse.task_status(*args, **kwargs)
