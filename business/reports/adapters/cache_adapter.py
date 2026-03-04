"""
Reports Django Adapter - Cache and Task Storage Operations

This module handles all Django-specific cache and storage operations for reports.
Business logic should NOT be in this file - only storage interactions.
"""

from typing import Optional, Dict, Any
from django.core.cache import cache


# =============================================================================
# CACHE OPERATIONS
# =============================================================================

CACHE_PREFIX = "report_task"
RESULT_CACHE_PREFIX = "report_result"
DEFAULT_TIMEOUT = 3600  # 1 hour


def store_task_in_cache(task_id: str, task_data: Dict[str, Any], 
                        timeout: int = DEFAULT_TIMEOUT) -> bool:
    """
    Store task data in cache
    
    Args:
        task_id: Task identifier
        task_data: Task data to store
        timeout: Cache timeout in seconds
        
    Returns:
        bool: True if successful
    """
    try:
        cache.set(f"{CACHE_PREFIX}_{task_id}", task_data, timeout=timeout)
        return True
    except Exception:
        return False


def get_task_from_cache(task_id: str) -> Optional[Dict[str, Any]]:
    """
    Retrieve task data from cache
    
    Args:
        task_id: Task identifier
        
    Returns:
        Optional[Dict]: Task data or None if not found
    """
    return cache.get(f"{CACHE_PREFIX}_{task_id}")


def update_task_in_cache(task_id: str, task_data: Dict[str, Any],
                         timeout: int = DEFAULT_TIMEOUT) -> bool:
    """
    Update task data in cache
    
    Args:
        task_id: Task identifier
        task_data: Updated task data
        timeout: Cache timeout in seconds
        
    Returns:
        bool: True if successful
    """
    return store_task_in_cache(task_id, task_data, timeout)


def delete_task_from_cache(task_id: str) -> bool:
    """
    Delete task from cache
    
    Args:
        task_id: Task identifier
        
    Returns:
        bool: True if successful
    """
    try:
        cache.delete(f"{CACHE_PREFIX}_{task_id}")
        return True
    except Exception:
        return False


# =============================================================================
# RESULT CACHING
# =============================================================================

def store_result_in_cache(cache_key: str, data: Any, timeout: int = 300) -> bool:
    """
    Store query results in cache
    
    Args:
        cache_key: Cache key
        data: Result data to cache
        timeout: Cache timeout in seconds
        
    Returns:
        bool: True if successful
    """
    try:
        cache.set(f"{RESULT_CACHE_PREFIX}_{cache_key}", data, timeout=timeout)
        return True
    except Exception:
        return False


def get_result_from_cache(cache_key: str) -> Optional[Any]:
    """
    Retrieve cached query results
    
    Args:
        cache_key: Cache key
        
    Returns:
        Optional[Any]: Cached data or None if not found
    """
    return cache.get(f"{RESULT_CACHE_PREFIX}_{cache_key}")


def delete_result_from_cache(cache_key: str) -> bool:
    """
    Delete cached results
    
    Args:
        cache_key: Cache key
        
    Returns:
        bool: True if successful
    """
    try:
        cache.delete(f"{RESULT_CACHE_PREFIX}_{cache_key}")
        return True
    except Exception:
        return False


# =============================================================================
# BATCH OPERATIONS
# =============================================================================

def clear_user_tasks(user_id: int) -> int:
    """
    Clear all tasks for a specific user
    
    Args:
        user_id: User identifier
        
    Returns:
        int: Number of tasks cleared
    """
    # Note: This is a simplified implementation
    # In production, you might want to maintain an index of user tasks
    # or use a more sophisticated cache backend
    cleared = 0
    
    # This would require iterating through all task keys
    # which is not efficient with default cache backend
    # Consider using Redis SCAN or maintaining a separate index
    
    return cleared


def get_cache_stats() -> Dict[str, Any]:
    """
    Get cache statistics
    
    Returns:
        dict: Cache statistics
    """
    try:
        # This depends on cache backend
        # Redis would have more detailed stats
        return {
            'backend': cache.__class__.__name__,
            'available': True
        }
    except Exception:
        return {
            'backend': 'unknown',
            'available': False
        }
