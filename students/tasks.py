"""
Background tasks for student bill recreation

Leverages the existing reports task infrastructure for large bill recreation operations
"""

import time
import uuid
from datetime import datetime, timezone
from typing import Dict, Any

from django.db import transaction
from django.core.cache import cache

from .models import StudentEnrollmentBill
from .views.utils import create_student_bill


class BillRecreationTaskManager:
    """Manages background bill recreation tasks"""
    
    CACHE_PREFIX = "bill_recreation_task"
    
    @staticmethod
    def should_use_background(enrollment_count: int) -> bool:
        """
        Determine if bill recreation should be processed in background
        
        Args:
            enrollment_count: Number of enrollments to process
            
        Returns:
            bool: True if should use background processing
        """
        # Use background for > 50 students to prevent timeouts
        threshold = 50
        return enrollment_count > threshold
    
    @classmethod
    def create_recreation_task(cls, scope: str, target_id: str, 
                              enrollment_count: int, academic_year_id: str = None,
                              user_id: int = None, diff_only: bool = False) -> str:
        """Create a new bill recreation task"""
        
        task_id = str(uuid.uuid4())
        
        task_data = {
            'id': task_id,
            'type': 'bill_recreation',
            'status': 'pending',
            'progress': 0,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'updated_at': datetime.now(timezone.utc).isoformat(),
            'user_id': user_id,
            'scope': scope,
            'target_id': target_id,
            'academic_year_id': academic_year_id,
            'diff_only': diff_only,
            'estimated_count': enrollment_count,
            'total_processed': 0,
            'bills_deleted': 0,
            'bills_created': 0,
            'failed_enrollments': [],
            'error': None,
            'result': None
        }
        
        cache.set(f"{cls.CACHE_PREFIX}_{task_id}", task_data, timeout=3600)  # 1 hour
        return task_id
    
    @classmethod
    def get_task(cls, task_id: str) -> Dict[str, Any]:
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
        
        cache.set(f"{cls.CACHE_PREFIX}_{task_id}", task_data, timeout=3600)
        return True


class MockBillRecreationProcessor:
    """
    Mock background processor for bill recreation
    In production, replace with Celery task
    """
    
    @staticmethod
    def process_bill_recreation(task_id: str, request=None):
        """
        Background processing of bill recreation
        """
        import threading
        
        def background_work():
            try:
                task_data = BillRecreationTaskManager.get_task(task_id)
                if not task_data:
                    return
                
                BillRecreationTaskManager.update_task(task_id, status='processing', progress=5)
                
                # Import here to avoid circular imports
                from .views.bill_recreation import BillRecreationView
                
                # Get enrollments using the existing logic
                recreation_view = BillRecreationView()
                enrollments_query = recreation_view._get_enrollments_by_scope(
                    task_data['scope'], 
                    task_data['target_id'], 
                    task_data['academic_year_id']
                )
                
                # Filter for differences if diff_only is enabled
                if task_data.get('diff_only', False):
                    enrollments = recreation_view._filter_enrollments_with_differences(enrollments_query)
                    if not enrollments:
                        # No differences found
                        BillRecreationTaskManager.update_task(
                            task_id,
                            status='completed',
                            progress=100,
                            result={
                                'enrollments_processed': 0,
                                'bills_deleted': 0,
                                'bills_created': 0,
                                'failed_enrollments': [],
                                'success_rate': '100%',
                                'message': 'No students had bill differences - all are up to date'
                            }
                        )
                        return
                else:
                    enrollments = list(enrollments_query)
                total_count = len(enrollments)
                chunk_size = 25  # Process 25 students at a time
                
                BillRecreationTaskManager.update_task(task_id, progress=10)
                
                # Delete existing bills in bulk
                enrollment_ids = [e.id for e in enrollments]
                deleted_count = StudentEnrollmentBill.objects.filter(
                    enrollment_id__in=enrollment_ids
                ).delete()[0]
                
                BillRecreationTaskManager.update_task(
                    task_id, 
                    progress=20,
                    bills_deleted=deleted_count
                )
                
                # Process enrollments in chunks
                created_bills = []
                failed_enrollments = []
                processed = 0
                
                for i in range(0, total_count, chunk_size):
                    chunk = enrollments[i:i + chunk_size]
                    
                    # Process chunk with transaction safety
                    try:
                        with transaction.atomic():
                            for enrollment in chunk:
                                try:
                                    bills = create_student_bill(enrollment, request)
                                    created_bills.extend(bills)
                                    processed += 1
                                    
                                except Exception as e:
                                    failed_enrollments.append({
                                        'enrollment_id': enrollment.id,
                                        'student_name': enrollment.student.get_full_name(),
                                        'error': str(e)
                                    })
                                    processed += 1
                    
                    except Exception as chunk_error:
                        # If whole chunk fails, mark all as failed
                        for enrollment in chunk:
                            failed_enrollments.append({
                                'enrollment_id': enrollment.id,
                                'student_name': enrollment.student.get_full_name(),
                                'error': f"Chunk error: {str(chunk_error)}"
                            })
                            processed += 1
                    
                    # Update progress (20% for deletion, 80% for creation)
                    progress = 20 + int((processed / total_count) * 80)
                    
                    BillRecreationTaskManager.update_task(
                        task_id,
                        progress=progress,
                        total_processed=processed,
                        bills_created=len(created_bills),
                        failed_enrollments=failed_enrollments
                    )
                    
                    # Small delay to prevent overwhelming the database
                    time.sleep(0.1)
                
                # Calculate success rate
                success_rate = f"{((processed - len(failed_enrollments)) / processed * 100):.1f}%" if processed > 0 else "0%"
                
                # Complete the task
                result = {
                    'enrollments_processed': processed,
                    'bills_deleted': deleted_count,
                    'bills_created': len(created_bills),
                    'failed_enrollments': failed_enrollments,
                    'success_rate': success_rate
                }
                
                BillRecreationTaskManager.update_task(
                    task_id,
                    status='completed',
                    progress=100,
                    result=result
                )
                
            except Exception as e:
                BillRecreationTaskManager.update_task(
                    task_id,
                    status='failed',
                    error=str(e)
                )
        
        # Start background thread
        thread = threading.Thread(target=background_work)
        thread.daemon = True
        thread.start()


# Future Celery implementation
"""
from celery import shared_task

@shared_task(bind=True, autoretry_for=(Exception,), retry_kwargs={'max_retries': 3, 'countdown': 60})
def process_bill_recreation_celery(self, task_id: str):
    '''
    Celery task for processing bill recreation in background
    
    Features:
    - Automatic retry on failure
    - Progress tracking
    - Chunked processing
    - Memory efficient
    '''
    try:
        task_data = BillRecreationTaskManager.get_task(task_id)
        if not task_data:
            return {'status': 'error', 'message': 'Task not found'}
        
        BillRecreationTaskManager.update_task(task_id, status='processing', progress=5)
        
        # ... (similar logic to MockBillRecreationProcessor but with Celery features)
        
        return {'status': 'completed', 'task_id': task_id}
        
    except Exception as e:
        BillRecreationTaskManager.update_task(task_id, status='failed', error=str(e))
        raise
"""