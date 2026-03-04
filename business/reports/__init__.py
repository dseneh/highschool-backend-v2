"""
Reports Business Logic Module

This module contains all business logic for report generation and task management.
It is framework-agnostic and contains NO Django dependencies.

Structure:
- services/: Pure Python business logic for task management and reporting
- adapters/: Django cache operations
- reports_models.py: Data transfer objects (DTOs)

Usage:
    from business.reports.services import create_task_data, should_use_background_processing
    from business.reports.adapters import store_task_in_cache, get_result_from_cache
    from business.reports.reports_models import TaskData, ReportResultData
"""

from .reports_models import (
    TaskData,
    CacheKeyData,
    ReportConfigData,
    QueryFilterData,
    ReportResultData,
)

from .services import (
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
    # Models
    'TaskData',
    'CacheKeyData',
    'ReportConfigData',
    'QueryFilterData',
    'ReportResultData',
    # Services
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
