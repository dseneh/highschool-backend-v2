"""
Reports Business Service - Task Management Logic

Framework-agnostic business logic for report task management, caching, and processing decisions.
NO Django or framework-specific imports allowed.
"""

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Tuple


# =============================================================================
# TASK DECISION LOGIC
# =============================================================================

def should_use_background_processing(query_count: int, export_format: Optional[str] = None,
                                     background_threshold: int = 5000) -> bool:
    """
    Determine if a query should be processed in background
    
    Args:
        query_count: Number of records in the query
        export_format: Export format requested (triggers background if set)
        background_threshold: Threshold for automatic background processing
        
    Returns:
        bool: True if should use background processing
    """
    # Always use background for exports
    if export_format:
        return True
        
    # Use background for large datasets
    return query_count > background_threshold


def determine_processing_mode(query_count: int, export_format: Optional[str] = None,
                              force_background: bool = False,
                              background_threshold: int = 5000) -> str:
    """
    Determine processing mode for a report request
    
    Args:
        query_count: Number of records
        export_format: Export format if any
        force_background: Force background processing
        background_threshold: Threshold for automatic background
        
    Returns:
        str: 'sync' or 'background'
    """
    if force_background or should_use_background_processing(query_count, export_format, background_threshold):
        return 'background'
    return 'sync'


# =============================================================================
# CACHE KEY GENERATION
# =============================================================================

def generate_cache_key(query_params: Dict[str, Any]) -> str:
    """
    Generate a consistent cache key from query parameters
    
    Args:
        query_params: Dictionary of query parameters
        
    Returns:
        str: MD5 hash of sorted parameters
    """
    # Sort params for consistent cache keys
    sorted_params = sorted(query_params.items())
    params_str = json.dumps(sorted_params, default=str)
    
    return hashlib.md5(params_str.encode()).hexdigest()


def build_cache_key_from_request(query_params: Dict[str, Any]) -> str:
    """
    Build cache key from query parameters
    
    Args:
        query_params: Query parameters
        
    Returns:
        str: Cache key
    """
    params_dict = {
        **dict(query_params)
    }
    return generate_cache_key(params_dict)


# =============================================================================
# TASK CREATION AND MANAGEMENT
# =============================================================================

def create_task_data(task_type: str, query_params: Dict[str, Any],
                    user_id: int, estimated_count: int) -> Dict[str, Any]:
    """
    Create task data structure for background processing
    
    Args:
        task_type: Type of task (e.g., 'transaction_report')
        query_params: Parameters for the query
        user_id: ID of requesting user
        estimated_count: Estimated number of records
        
    Returns:
        dict: Task data structure
    """
    task_id = str(uuid.uuid4())
    
    return {
        'id': task_id,
        'type': task_type,
        'status': 'pending',
        'progress': 0,
        'created_at': datetime.now(timezone.utc).isoformat(),
        'updated_at': datetime.now(timezone.utc).isoformat(),
        'user_id': user_id,
        'query_params': query_params,
        'estimated_count': estimated_count,
        'total_processed': 0,
        'error': None,
        'result_url': None,
    }


def update_task_data(task_data: Dict[str, Any], **updates) -> Dict[str, Any]:
    """
    Update task data with new values
    
    Args:
        task_data: Current task data
        **updates: Fields to update
        
    Returns:
        dict: Updated task data
    """
    task_data.update(updates)
    task_data['updated_at'] = datetime.now(timezone.utc).isoformat()
    return task_data


def validate_task_status(task_data: Optional[Dict[str, Any]]) -> Tuple[bool, Optional[str]]:
    """
    Validate task data and status
    
    Args:
        task_data: Task data to validate
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not task_data:
        return False, 'Task not found or has expired'
    
    return True, None


def can_cancel_task(task_data: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """
    Check if a task can be cancelled
    
    Args:
        task_data: Task data
        
    Returns:
        Tuple of (can_cancel, reason_if_not)
    """
    current_status = task_data.get('status')
    
    if current_status == 'completed':
        return False, 'Cannot cancel completed task'
    
    if current_status == 'failed':
        return False, 'Task already failed'
    
    if current_status == 'cancelled':
        return False, 'Task already cancelled'
    
    return True, None


def can_download_task(task_data: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """
    Check if a task result can be downloaded
    
    Args:
        task_data: Task data
        
    Returns:
        Tuple of (can_download, reason_if_not)
    """
    if task_data.get('status') != 'completed':
        return False, f"Task not completed yet (status: {task_data.get('status', 'unknown')})"
    
    return True, None


# =============================================================================
# PROGRESS CALCULATION
# =============================================================================

def calculate_estimated_completion_time(progress: int, elapsed_seconds: float) -> Optional[int]:
    """
    Calculate estimated completion time based on progress
    
    Args:
        progress: Current progress percentage (0-100)
        elapsed_seconds: Seconds elapsed since start
        
    Returns:
        Optional[int]: Estimated seconds remaining, None if can't calculate
    """
    if progress <= 0 or progress >= 100:
        return None
    
    # Calculate average time per percent
    time_per_percent = elapsed_seconds / progress
    
    # Calculate remaining time
    remaining_percent = 100 - progress
    estimated_remaining = int(remaining_percent * time_per_percent)
    
    return estimated_remaining


def calculate_simple_estimated_time(progress: int, seconds_per_percent: int = 2) -> int:
    """
    Simple estimation of completion time based on progress
    
    Args:
        progress: Current progress percentage
        seconds_per_percent: Estimated seconds per percent progress
        
    Returns:
        int: Estimated seconds remaining
    """
    return (100 - progress) * seconds_per_percent


# =============================================================================
# PAGINATION LOGIC
# =============================================================================

def calculate_pagination_limits(total_count: int, use_pagination: bool,
                                page_size: Optional[int] = None,
                                max_page_size: int = 1000,
                                default_limit: int = 1000) -> Dict[str, Any]:
    """
    Calculate pagination parameters
    
    Args:
        total_count: Total number of records
        use_pagination: Whether to use pagination
        page_size: Requested page size
        max_page_size: Maximum allowed page size
        default_limit: Default limit for unpaginated requests
        
    Returns:
        dict: Pagination parameters
    """
    if not use_pagination:
        # For unpaginated requests, apply reasonable limits
        limit = min(default_limit, max_page_size)
        return {
            'limit': limit,
            'paginated': False,
            'has_more': total_count > limit,
            'returned': min(total_count, limit)
        }
    
    # For paginated requests
    effective_page_size = page_size or 100
    effective_page_size = min(effective_page_size, max_page_size)
    
    return {
        'page_size': effective_page_size,
        'paginated': True,
        'total_pages': (total_count + effective_page_size - 1) // effective_page_size
    }


# =============================================================================
# RESULT FORMATTING
# =============================================================================

def format_sync_result(count: int, returned: int, has_more: bool, 
                      limit: int, data: Any) -> Dict[str, Any]:
    """
    Format synchronous processing result
    
    Args:
        count: Total count
        returned: Number of records returned
        has_more: Whether there are more records
        limit: Limit applied
        data: Result data
        
    Returns:
        dict: Formatted result
    """
    return {
        'count': count,
        'returned': returned,
        'has_more': has_more,
        'limit': limit,
        'processing_mode': 'sync',
        'cached': False,
        'results': data
    }


def format_background_response(task_id: str, estimated_records: int,
                               status_url: str) -> Dict[str, Any]:
    """
    Format background processing response
    
    Args:
        task_id: Task identifier
        estimated_records: Estimated number of records
        status_url: URL to check task status
        
    Returns:
        dict: Background response
    """
    return {
        'task_id': task_id,
        'status': 'pending',
        'processing_mode': 'background',
        'message': 'Large dataset detected. Processing in background.',
        'estimated_records': estimated_records,
        'check_status_url': status_url,
        'auto_background': True
    }


def enrich_task_status_response(task_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Enrich task status response with computed fields
    
    Args:
        task_data: Task data
        
    Returns:
        dict: Enriched response
    """
    response_data = task_data.copy()
    
    # Calculate estimated completion time if processing
    if task_data.get('status') == 'processing':
        progress = task_data.get('progress', 0)
        if progress > 0:
            estimated_seconds = calculate_simple_estimated_time(progress)
            response_data['estimated_completion_seconds'] = estimated_seconds
    
    # Add helpful URLs
    if task_data.get('status') == 'completed' and task_data.get('result_url'):
        response_data['download_url'] = task_data['result_url']
    
    return response_data


# =============================================================================
# VALIDATION HELPERS
# =============================================================================

def validate_query_params(query_params: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """
    Validate report query parameters
    
    Args:
        query_params: Query parameters to validate
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    
    # Validate page_size if provided
    page_size = query_params.get('page_size')
    if page_size:
        try:
            page_size_int = int(page_size)
            if page_size_int < 1:
                return False, 'page_size must be positive'
            if page_size_int > 1000:
                return False, 'page_size cannot exceed 1000'
        except (ValueError, TypeError):
            return False, 'page_size must be a valid integer'
    
    return True, None
