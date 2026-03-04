"""
Background task processor for reports

Handles automatic background processing for large queries and caching
"""

import json
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from django.core.cache import cache
from django.conf import settings

from .settings import get_reports_setting

# For future Celery integration
# from celery import shared_task


class TaskManager:
    """Manages background tasks and caching for reports"""
    
    CACHE_PREFIX = "report_task"
    RESULT_CACHE_PREFIX = "report_result"
    DEFAULT_TIMEOUT = 3600  # 1 hour
    
    @staticmethod
    def should_use_background(query_count: int, export_format: str = None) -> bool:
        """
        Determine if a query should be processed in background
        
        Args:
            query_count: Number of records in the query
            export_format: Export format requested
            
        Returns:
            bool: True if should use background processing
        """
        # Always use background for exports
        if export_format:
            return True
            
        # Use background for large datasets
        threshold = get_reports_setting('BACKGROUND_THRESHOLD', 5000)
        return query_count > threshold
    
    @classmethod
    def create_task(cls, task_type: str, query_params: Dict[str, Any], 
                   user_id: int, estimated_count: int) -> str:
        """
        Create a new background task
        
        Args:
            task_type: Type of task (e.g., 'transaction_report')
            query_params: Parameters for the query
            user_id: ID of requesting user
            estimated_count: Estimated number of records
            
        Returns:
            str: Task ID
        """
        task_id = str(uuid.uuid4())
        
        task_data = {
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
        
        cache.set(f"{cls.CACHE_PREFIX}_{task_id}", task_data, timeout=cls.DEFAULT_TIMEOUT)
        
        # Queue the actual task
        # process_report_task.delay(task_id)  # Uncomment when using Celery
        
        return task_id
    
    @classmethod
    def get_task(cls, task_id: str) -> Optional[Dict[str, Any]]:
        """Get task data by ID"""
        return cache.get(f"{cls.CACHE_PREFIX}_{task_id}")
    
    @classmethod
    def update_task(cls, task_id: str, **updates) -> bool:
        """Update task data"""
        task_data = cls.get_task(task_id)
        if not task_data:
            return False
            
        task_data.update(updates)
        task_data['updated_at'] = datetime.now(timezone.utc).isoformat()
        
        cache.set(f"{cls.CACHE_PREFIX}_{task_id}", task_data, timeout=cls.DEFAULT_TIMEOUT)
        return True
    
    @classmethod
    def cache_result(cls, cache_key: str, data: Any, timeout: int = None) -> None:
        """Cache query results"""
        if timeout is None:
            timeout = get_reports_setting('CACHE_TIMEOUT', 300)  # 5 minutes default
            
        cache.set(f"{cls.RESULT_CACHE_PREFIX}_{cache_key}", data, timeout=timeout)
    
    @classmethod
    def get_cached_result(cls, cache_key: str) -> Optional[Any]:
        """Get cached query results"""
        return cache.get(f"{cls.RESULT_CACHE_PREFIX}_{cache_key}")
    
    @classmethod
    def generate_cache_key(cls, query_params: Dict[str, Any]) -> str:
        """Generate a cache key from query parameters"""
        # Sort params for consistent cache keys
        sorted_params = sorted(query_params.items())
        params_str = json.dumps(sorted_params, default=str)
        
        import hashlib
        return hashlib.md5(params_str.encode()).hexdigest()


class MockTaskProcessor:
    """
    Mock task processor for demonstration
    Replace with actual Celery tasks in production
    """
    
    @staticmethod
    def process_transaction_report(task_id: str):
        """
        Mock background processing of transaction reports
        In production, this would be a Celery task
        """
        import threading
        import time
        
        def background_work():
            try:
                task_data = TaskManager.get_task(task_id)
                if not task_data:
                    return
                
                # Simulate work
                TaskManager.update_task(task_id, status='processing', progress=10)
                time.sleep(2)  # Simulate processing time
                
                TaskManager.update_task(task_id, status='processing', progress=50)
                time.sleep(2)
                
                TaskManager.update_task(task_id, status='processing', progress=90)
                time.sleep(1)
                
                # Mark as completed
                TaskManager.update_task(
                    task_id, 
                    status='completed', 
                    progress=100,
                    result_url=f"/api/v1/reports/download/{task_id}/"
                )
                
            except Exception as e:
                TaskManager.update_task(
                    task_id, 
                    status='failed', 
                    error=str(e)
                )
        
        # Start background thread (in production, use Celery)
        thread = threading.Thread(target=background_work)
        thread.daemon = True
        thread.start()


# Future Celery task implementation
"""
@shared_task(bind=True)
def process_report_task(self, task_id: str):
    '''
    Celery task for processing reports in background
    '''
    try:
        task_data = TaskManager.get_task(task_id)
        if not task_data:
            return
        
        TaskManager.update_task(task_id, status='processing')
        
        # Process based on task type
        if task_data['type'] == 'transaction_report':
            process_transaction_report_task(task_id, task_data)
        
    except Exception as e:
        TaskManager.update_task(task_id, status='failed', error=str(e))
        raise


def process_transaction_report_task(task_id: str, task_data: Dict[str, Any]):
    '''Process transaction report in background'''
    from reports.views.transactions import TransactionReportProcessor
    
    processor = TransactionReportProcessor()
    result = processor.process_background_task(task_data)
    
    TaskManager.update_task(
        task_id,
        status='completed',
        progress=100,
        result_url=result['download_url']
    )
"""
