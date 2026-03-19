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
from django.contrib.auth import get_user_model

from academics.models import GradeLevel
from common.utils import (
    StudentBulkProcessor,
    StudentImportValidator,
    format_import_response,
)

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


class StudentImportTaskManager:
    """Manages background student import tasks."""

    CACHE_PREFIX = "student_import_task"

    @staticmethod
    def should_use_background(row_count: int) -> bool:
        """Use background mode for larger imports to avoid HTTP timeouts."""
        threshold = 500
        return row_count > threshold

    @classmethod
    def create_import_task(
        cls,
        *,
        grade_level_id: str,
        row_count: int,
        user_id: int,
        file_name: str,
    ) -> str:
        task_id = str(uuid.uuid4())

        task_data = {
            "id": task_id,
            "type": "student_import",
            "status": "pending",
            "progress": 0,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "user_id": user_id,
            "grade_level_id": grade_level_id,
            "file_name": file_name,
            "estimated_count": row_count,
            "total_processed": 0,
            "created": 0,
            "errors": [],
            "total_errors": 0,
            "error": None,
            "result": None,
        }

        cache.set(f"{cls.CACHE_PREFIX}_{task_id}", task_data, timeout=3600)
        return task_id

    @classmethod
    def get_task(cls, task_id: str) -> Dict[str, Any]:
        return cache.get(f"{cls.CACHE_PREFIX}_{task_id}")

    @classmethod
    def update_task(cls, task_id: str, **updates) -> bool:
        task_data = cls.get_task(task_id)
        if not task_data:
            return False

        task_data.update(updates)
        task_data["updated_at"] = datetime.now(timezone.utc).isoformat()
        cache.set(f"{cls.CACHE_PREFIX}_{task_id}", task_data, timeout=3600)
        return True


class MockStudentImportProcessor:
    """Background processor for student import operations."""

    @staticmethod
    def process_student_import(
        task_id: str,
        *,
        df,
        grade_level_id: str,
        user_id: int,
    ):
        import threading

        def background_work():
            try:
                task_data = StudentImportTaskManager.get_task(task_id)
                if not task_data:
                    return

                StudentImportTaskManager.update_task(
                    task_id, status="processing", progress=5
                )

                grade_level = GradeLevel.objects.get(id=grade_level_id)
                user_model = get_user_model()
                request_user = user_model.objects.get(id=user_id)

                total_rows = len(df)
                processed_rows = 0
                total_created = 0
                all_errors = []

                for i in range(0, total_rows, StudentImportValidator.CHUNK_SIZE):
                    current_task = StudentImportTaskManager.get_task(task_id)
                    if not current_task:
                        return

                    if current_task.get("status") == "cancelled":
                        StudentImportTaskManager.update_task(
                            task_id,
                            result={
                                "success": False,
                                "message": "Student import cancelled",
                                "created": total_created,
                                "total_errors": len(all_errors),
                                "errors": all_errors[:20],
                            },
                        )
                        return

                    chunk = df.iloc[i : i + StudentImportValidator.CHUNK_SIZE]

                    chunk_validation_errors = []
                    for index, row in chunk.iterrows():
                        row_errors = StudentImportValidator.validate_row_data(
                            row, index + 2
                        )
                        chunk_validation_errors.extend(row_errors)

                    if chunk_validation_errors:
                        all_errors.extend(chunk_validation_errors)
                        processed_rows += len(chunk)
                        progress = 5 + int((processed_rows / total_rows) * 90)
                        StudentImportTaskManager.update_task(
                            task_id,
                            progress=min(progress, 95),
                            total_processed=processed_rows,
                            total_errors=len(all_errors),
                            errors=all_errors[:20],
                            created=total_created,
                        )
                        continue

                    students_to_create, _, chunk_errors = StudentBulkProcessor.process_chunk(
                        chunk, grade_level, request_user
                    )

                    if chunk_errors:
                        all_errors.extend(chunk_errors)

                    if students_to_create:
                        created_students = []
                        for student_obj in students_to_create:
                            try:
                                with transaction.atomic():
                                    student_obj.save()
                                    created_students.append(student_obj)
                            except Exception as create_error:
                                chunk_errors.append(
                                    {
                                        "row": f"Student {student_obj.first_name} {student_obj.last_name}",
                                        "error": f"Failed to create: {str(create_error)}",
                                    }
                                )

                        total_created += len(created_students)

                        if created_students:
                            try:
                                StudentBulkProcessor.create_user_accounts(
                                    created_students, request_user
                                )
                            except Exception as user_error:
                                all_errors.append(
                                    {
                                        "row": "User account creation",
                                        "error": f"Failed to create user accounts: {str(user_error)}",
                                    }
                                )

                    if chunk_errors:
                        all_errors.extend(chunk_errors)

                    processed_rows += len(chunk)
                    progress = 5 + int((processed_rows / total_rows) * 90)
                    StudentImportTaskManager.update_task(
                        task_id,
                        progress=min(progress, 95),
                        total_processed=processed_rows,
                        total_errors=len(all_errors),
                        errors=all_errors[:20],
                        created=total_created,
                    )

                result = format_import_response(total_created, all_errors, success=True)
                StudentImportTaskManager.update_task(
                    task_id,
                    status="completed",
                    progress=100,
                    result=result,
                    total_processed=processed_rows,
                    total_errors=len(all_errors),
                    errors=all_errors[:20],
                    created=total_created,
                )

            except Exception as e:
                StudentImportTaskManager.update_task(
                    task_id,
                    status="failed",
                    error=str(e),
                )

        thread = threading.Thread(target=background_work)
        thread.daemon = True
        thread.start()


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