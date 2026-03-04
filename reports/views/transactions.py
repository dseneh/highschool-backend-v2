"""
Transaction Reports Views

Handles transaction reporting functionality including:
- Automatic background processing for large datasets
- Intelligent caching
- Export status monitoring
"""

import hashlib
import json
from datetime import datetime, timezone

from django.core.cache import cache
from django.db.models import Q
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView
from ..access_policies import ReportsAccessPolicy

from common.filter import get_transaction_queryparams
from finance.models import Transaction
from finance.serializers import TransactionSerializer, TransactionStudentSerializer
from reports.tasks import TaskManager, MockTaskProcessor

class TransactionPageNumberPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100

class TransactionReportingPagination(PageNumberPagination):
    """
    Specialized pagination for reporting purposes that allows larger page sizes
    """
    page_size = 100
    page_size_query_param = "page_size"
    max_page_size = 1000  # Allow up to 1000 records per page for reporting

class TransactionReportView(APIView):
    permission_classes = [ReportsAccessPolicy]
    """
    Enhanced transaction reports with automatic background processing and caching
    """

    def get(self, request, school_id):
        # Build base query
        f = (
            Q(account__school__id=school_id)
            | Q(account__school__id_number=school_id)
            | Q(account__school__workspace=school_id)
        )
        transactions = Transaction.objects.filter(f).select_related(
            "student",
            "academic_year",
            "account",
            "type",
            "payment_method",
        )

        # Apply filters and ordering
        ordering = request.query_params.get("ordering", "-updated_at")
        transactions = transactions.order_by(ordering)

        query_params = request.query_params.copy()
        query = get_transaction_queryparams(query_params)
        if query:
            transactions = transactions.filter(query)

        # Check cache first
        cache_key = self._generate_cache_key(school_id, request.query_params)
        cached_result = TaskManager.get_cached_result(cache_key)
        
        if cached_result and not request.query_params.get('force_refresh'):
            cached_result['from_cache'] = True
            return Response(cached_result)

        # Get count for decision making
        total_count = transactions.count()
        export_format = query_params.get("export_format")
        force_background = query_params.get("force_background", "false").lower() == "true"
        
        # Automatic background processing decision
        should_background = (
            force_background or 
            TaskManager.should_use_background(total_count, export_format)
        )
        
        if should_background:
            return self._handle_background_processing(
                request, transactions, query_params, total_count, cache_key
            )
        
        # Process synchronously for small datasets
        return self._handle_sync_processing(
            request, transactions, query_params, total_count, cache_key
        )

    def _generate_cache_key(self, school_id: str, query_params) -> str:
        """Generate cache key from request parameters"""
        # Create a consistent cache key
        params_dict = {
            'school_id': school_id,
            **dict(query_params)
        }
        return TaskManager.generate_cache_key(params_dict)

    def _handle_sync_processing(self, request, transactions, query_params, 
                               total_count: int, cache_key: str):
        """Handle synchronous processing for smaller datasets"""
        target = query_params.get("target")
        use_pagination = query_params.get("paginate", "true").lower() == "true"
        
        if target == "student" and not use_pagination:
            # Limited unpaginated response
            limit = min(int(query_params.get("limit", 1000)), 5000)
            limited_transactions = transactions[:limit]
            
            serializer = TransactionStudentSerializer(limited_transactions, many=True)
            result = {
                'count': total_count,
                'returned': len(limited_transactions),
                'has_more': total_count > limit,
                'limit': limit,
                'processing_mode': 'sync',
                'cached': False,
                'results': serializer.data
            }
        else:
            # Regular pagination
            if target == "student":
                paginator = TransactionReportingPagination()
                serializer_class = TransactionStudentSerializer
            else:
                paginator = TransactionPageNumberPagination()
                serializer_class = TransactionSerializer
                
            paginated_qs = paginator.paginate_queryset(transactions, request)
            serializer = serializer_class(paginated_qs, many=True)
            
            result = {
                'count': total_count,
                'processing_mode': 'sync',
                'cached': False,
                **paginator.get_paginated_response(serializer.data).data
            }
        
        # Cache the result for future requests
        cache_timeout = 300  # 5 minutes for sync results
        TaskManager.cache_result(cache_key, result, timeout=cache_timeout)
        
        return Response(result)

    def _handle_background_processing(self, request, transactions, query_params, 
                                    total_count: int, cache_key: str):
        """Handle background processing for large datasets"""
        # Prepare task parameters
        task_params = {
            'school_id': request.resolver_match.kwargs.get('school_id'),
            'query_params': dict(query_params),
            'user_id': request.user.id,
            'cache_key': cache_key,
            'queryset_filters': self._serialize_queryset_filters(transactions)
        }
        
        # Create background task
        task_id = TaskManager.create_task(
            task_type='transaction_report',
            query_params=task_params,
            user_id=request.user.id,
            estimated_count=total_count
        )
        
        # Start the background processing (mock for now)
        MockTaskProcessor.process_transaction_report(task_id)
        
        return Response({
            'task_id': task_id,
            'status': 'pending',
            'processing_mode': 'background',
            'message': 'Large dataset detected. Processing in background.',
            'estimated_records': total_count,
            'check_status_url': f'/api/v1/reports/export-status/{task_id}/',
            'auto_background': True
        }, status=status.HTTP_202_ACCEPTED)

    def _serialize_queryset_filters(self, queryset) -> dict:
        """Convert queryset to serializable filters for background processing"""
        # This is a simplified version - in production you'd want more robust serialization
        return {
            'model': 'finance.Transaction',
            'filters': str(queryset.query),  # Simplified - use proper serialization in production
        }

class TransactionExportStatusView(APIView):
    """
    Enhanced view to check the status of background tasks
    """
    
    def get(self, request, task_id):
        task_data = TaskManager.get_task(task_id)
        
        if not task_data:
            return Response({
                'detail': 'Task not found or has expired'
            }, status=status.HTTP_404_NOT_FOUND)
        
        # Add some computed fields for better UX
        response_data = task_data.copy()
        
        # Calculate estimated completion time if processing
        if task_data.get('status') == 'processing':
            progress = task_data.get('progress', 0)
            if progress > 0:
                # Simple estimation based on progress
                estimated_seconds_remaining = (100 - progress) * 2  # Rough estimate
                response_data['estimated_completion_seconds'] = estimated_seconds_remaining
        
        # Add helpful URLs
        if task_data.get('status') == 'completed' and task_data.get('result_url'):
            response_data['download_url'] = task_data['result_url']
        
        return Response(response_data, status=status.HTTP_200_OK)
    
    def delete(self, request, task_id):
        """Cancel a background task"""
        task_data = TaskManager.get_task(task_id)
        
        if not task_data:
            return Response({
                'detail': 'Task not found'
            }, status=status.HTTP_404_NOT_FOUND)
        
        current_status = task_data.get('status')
        
        if current_status == 'completed':
            return Response({
                'detail': 'Cannot cancel completed task'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        if current_status == 'failed':
            return Response({
                'detail': 'Task already failed'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Update task status to cancelled
        TaskManager.update_task(task_id, status='cancelled')
        
        # In production, you would also cancel the Celery task here
        # cancel_celery_task.delay(task_id)
        
        return Response({
            'message': 'Task cancelled successfully',
            'task_id': task_id
        }, status=status.HTTP_200_OK)

class TransactionReportDownloadView(APIView):
    """
    View to download completed report results
    """
    
    def get(self, request, task_id):
        task_data = TaskManager.get_task(task_id)
        
        if not task_data:
            return Response({
                'detail': 'Task not found or has expired'
            }, status=status.HTTP_404_NOT_FOUND)
        
        if task_data.get('status') != 'completed':
            return Response({
                'detail': 'Task not completed yet',
                'status': task_data.get('status', 'unknown')
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # In a real implementation, you would:
        # 1. Generate the file based on cached results
        # 2. Return a file response or redirect to cloud storage
        # 3. Handle different export formats
        
        # For now, return the cached result
        cache_key = task_data.get('query_params', {}).get('cache_key')
        if cache_key:
            cached_result = TaskManager.get_cached_result(cache_key)
            if cached_result:
                return Response({
                    'download_ready': True,
                    'format': 'json',
                    'data': cached_result,
                    'message': 'In production, this would be a file download'
                })
        
        return Response({
            'detail': 'Download not available'
        }, status=status.HTTP_404_NOT_FOUND)
