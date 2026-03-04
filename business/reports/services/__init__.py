"""Reports Services - Business Logic"""

from .task_service import (
    should_use_background_processing,
    determine_processing_mode,
    generate_cache_key,
    build_cache_key_from_request,
    create_task_data,
    update_task_data,
    validate_task_status,
    can_cancel_task,
    can_download_task,
    calculate_estimated_completion_time,
    calculate_simple_estimated_time,
    calculate_pagination_limits,
    format_sync_result,
    format_background_response,
    enrich_task_status_response,
    validate_query_params,
)

__all__ = [
    'should_use_background_processing',
    'determine_processing_mode',
    'generate_cache_key',
    'build_cache_key_from_request',
    'create_task_data',
    'update_task_data',
    'validate_task_status',
    'can_cancel_task',
    'can_download_task',
    'calculate_estimated_completion_time',
    'calculate_simple_estimated_time',
    'calculate_pagination_limits',
    'format_sync_result',
    'format_background_response',
    'enrich_task_status_response',
    'validate_query_params',
]
