"""Reports Adapters - Cache and Storage Operations"""

from .cache_adapter import (
    store_task_in_cache,
    get_task_from_cache,
    update_task_in_cache,
    delete_task_from_cache,
    store_result_in_cache,
    get_result_from_cache,
    delete_result_from_cache,
    clear_user_tasks,
    get_cache_stats,
)

__all__ = [
    'store_task_in_cache',
    'get_task_from_cache',
    'update_task_in_cache',
    'delete_task_from_cache',
    'store_result_in_cache',
    'get_result_from_cache',
    'delete_result_from_cache',
    'clear_user_tasks',
    'get_cache_stats',
]
