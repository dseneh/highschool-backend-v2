"""
Reports Data Models - DTOs for report data transfer

Pure Python data classes with no framework dependencies.
"""

from dataclasses import dataclass
from typing import Optional, Dict, Any, List
from datetime import datetime


@dataclass
class TaskData:
    """Task information for background processing"""
    id: str
    type: str
    status: str
    progress: int
    created_at: str
    updated_at: str
    user_id: int
    query_params: Dict[str, Any]
    estimated_count: int
    total_processed: int
    error: Optional[str] = None
    result_url: Optional[str] = None


@dataclass
class CacheKeyData:
    """Cache key information"""
    key: str
    params: Dict[str, Any]
    hash: str


@dataclass
class ReportConfigData:
    """Report configuration settings"""
    background_threshold: int
    cache_timeout: int
    max_page_size: int
    default_page_size: int


@dataclass
class QueryFilterData:
    """Query filter parameters"""
    ordering: str
    filters: Dict[str, Any]
    page: Optional[int] = None
    page_size: Optional[int] = None
    export_format: Optional[str] = None
    target: Optional[str] = None


@dataclass
class ReportResultData:
    """Report result data"""
    count: int
    processing_mode: str
    cached: bool
    from_cache: bool = False
    returned: Optional[int] = None
    has_more: Optional[bool] = None
    limit: Optional[int] = None
    results: Optional[List[Dict[str, Any]]] = None
    next: Optional[str] = None
    previous: Optional[str] = None
