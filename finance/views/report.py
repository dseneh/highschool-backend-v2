
from datetime import datetime, timezone

from django.db.models import Q
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from common.filter import get_transaction_queryparams
from finance.models import Transaction
from finance.serializers import TransactionSerializer, TransactionStudentSerializer

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
    """
    View to generate transaction reports with support for large datasets and background processing.
    Supports filtering by student, status, payment method, etc.
    """

    def get(self, request, school_id):
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

        ordering = request.query_params.get("ordering", "-updated_at")
        transactions = transactions.order_by(ordering)

        query_params = request.query_params.copy()

        target = query_params.get("target", None)

        query = get_transaction_queryparams(query_params)
        if query:
            transactions = transactions.filter(query)

        paginator = TransactionPageNumberPagination()
        
        if target == "student":
            # Check if this should be processed in background
            export_format = query_params.get("export_format")
            large_export = query_params.get("large_export", "false").lower() == "true"
            
            # Background processing for large exports or specific formats
            if export_format or large_export:
                return self._handle_background_export(request, transactions, export_format)
            
            # For reporting purposes, allow larger datasets but with configurable limits
            # Check if user wants unpaginated results (for exports/reports)
            use_pagination = query_params.get("paginate", "true").lower() == "true"
            
            if not use_pagination:
                # Default limit of 5000 for performance, can be overridden via query param
                limit = query_params.get("limit", 5000)
                try:
                    limit = int(limit)
                    # Cap the maximum limit to prevent memory issues
                    # If limit is too large, suggest background processing
                    if limit > 10000:
                        return Response({
                            "detail": "Large exports require background processing. Use export_format parameter or set large_export=true",
                            "suggestion": "Add ?large_export=true or ?export_format=csv to your request"
                        }, status=status.HTTP_400_BAD_REQUEST)
                    limit = min(limit, 10000)
                except (ValueError, TypeError):
                    limit = 5000
                
                # Apply limit only if it's reasonable (avoid unlimited queries)
                if limit > 0:
                    limited_transactions = transactions[:limit]
                    total_count = transactions.count()
                    
                    # Warn if there are more records than the limit
                    has_more = total_count > limit
                    
                    serializer = TransactionStudentSerializer(limited_transactions, many=True)
                    return Response({
                        'count': total_count,
                        'returned': len(limited_transactions),
                        'has_more': has_more,
                        'limit': limit,
                        'next': None,
                        'previous': None,
                        'results': serializer.data
                    })
            
            # Use reporting pagination for better performance with larger datasets
            reporting_paginator = TransactionReportingPagination()
            paginated_qs = reporting_paginator.paginate_queryset(transactions, request)
            serializer = TransactionStudentSerializer(paginated_qs, many=True)
            return reporting_paginator.get_paginated_response(serializer.data)
        else:
            paginated_qs = paginator.paginate_queryset(transactions, request)
            serializer = TransactionSerializer(paginated_qs, many=True)
            return paginator.get_paginated_response(serializer.data)

    def _handle_background_export(self, request, transactions, export_format):
        """
        Handle large exports or specific format exports in background
        """
        from django.core.cache import cache
        import uuid
        
        # Generate a unique task ID
        task_id = str(uuid.uuid4())
        
        # Store task metadata in cache
        task_data = {
            'status': 'pending',
            'created_at': datetime.now(timezone.utc).isoformat(),
            'total_records': transactions.count(),
            'export_format': export_format or 'json',
            'progress': 0
        }
        cache.set(f"export_task_{task_id}", task_data, timeout=3600)  # 1 hour
        
        # Queue the background task (you'll need to implement this based on your task queue)
        # Examples: Celery, Django-RQ, etc.
        # export_transactions_task.delay(task_id, transactions.query, request.user.id)
        
        return Response({
            'task_id': task_id,
            'status': 'pending',
            'message': 'Export task has been queued. Use the task_id to check progress.',
            'check_status_url': f'/api/export-status/{task_id}/',
            'estimated_records': task_data['total_records']
        }, status=status.HTTP_202_ACCEPTED)

class TransactionExportStatusView(APIView):
    """
    View to check the status of background export tasks
    """
    
    def get(self, request, task_id):
        from django.core.cache import cache
        
        task_data = cache.get(f"export_task_{task_id}")
        
        if not task_data:
            return Response({
                'detail': 'Export task not found or has expired'
            }, status=status.HTTP_404_NOT_FOUND)
        
        return Response(task_data, status=status.HTTP_200_OK)
    
    def delete(self, request, task_id):
        """Cancel an export task"""
        from django.core.cache import cache
        
        task_data = cache.get(f"export_task_{task_id}")
        
        if not task_data:
            return Response({
                'detail': 'Export task not found'
            }, status=status.HTTP_404_NOT_FOUND)
        
        if task_data.get('status') == 'completed':
            return Response({
                'detail': 'Cannot cancel completed task'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Update task status to cancelled
        task_data['status'] = 'cancelled'
        cache.set(f"export_task_{task_id}", task_data, timeout=3600)
        
        # Here you would also cancel the background task
        # cancel_export_task.delay(task_id)
        
        return Response({
            'message': 'Export task cancelled successfully'
        }, status=status.HTTP_200_OK)
