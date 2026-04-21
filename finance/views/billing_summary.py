"""
Finance billing summary API views for dashboard.
"""
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from django.db.models import Count, Sum, Q
from django.core.cache import cache
from django.utils import timezone
from datetime import timedelta
from common.cache_service import DataCache

import logging

logger = logging.getLogger(__name__)

DASHBOARD_CACHE_TTL = 3600  # 1 hour


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_billing_summary(request):
    """
    Get financial billing summary for dashboard.
    
    Returns:
        List of monthly financial data points with income and expense trends
        [
            {
                "month": "2025-01",
                "moneyIn": 5000.00,
                "moneyOut": 2000.00,
                "moneyInChange": 10.5,
                "moneyOutChange": -5.2
            },
            ...
        ]
    """
    try:
        from academics.models import AcademicYear

        # Resolve academic year from ?academic_year= or fall back to current
        year_id = request.GET.get("academic_year")
        current_academic_year = None
        if year_id:
            current_academic_year = AcademicYear.objects.filter(id=year_id).first()
        if not current_academic_year:
            current_academic_year = AcademicYear.objects.filter(current=True).first()
        year_cache_suffix = f"_ay_{current_academic_year.id}" if current_academic_year else "_ay_none"

        cache_key = DataCache._get_cache_key(
            f"dashboard_billing_summary{year_cache_suffix}", request=request
        )
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached, status=status.HTTP_200_OK)

        from finance.models import Transaction
        
        # Get last 12 months of data
        twelve_months_ago = timezone.now().date() - timedelta(days=365)
        
        # Aggregate transactions by month and type
        monthly_data = {}
        
        # Get all approved transactions from the last 12 months
        transactions = Transaction.objects.filter(
            status='approved',
            date__gte=twelve_months_ago
        )
        
        if current_academic_year:
            transactions = transactions.filter(academic_year=current_academic_year)
        
        # Aggregate by month and type
        monthly_stats = transactions.values('type__type').annotate(
            month=Sum('date'),  # This won't work for grouping, need to use annotations differently
        ).order_by('date')
        
        # Better approach: use values with date truncation
        from django.db.models.functions import TruncMonth
        
        monthly_totals = transactions.annotate(
            month=TruncMonth('date')
        ).values('month', 'type__type').annotate(
            total=Sum('amount')
        ).order_by('month', 'type__type')
        
        # Process the data into the expected format
        months_dict = {}
        previous_income = None
        previous_expense = None
        
        for entry in monthly_totals:
            month_str = entry['month'].strftime('%Y-%m') if entry['month'] else '2025-01'
            
            if month_str not in months_dict:
                months_dict[month_str] = {
                    'month': month_str,
                    'income': 0,
                    'expense': 0
                }
            
            amount = float(entry['total'] or 0)
            if entry['type__type'] == 'income':
                months_dict[month_str]['income'] += amount
            else:  # expense
                months_dict[month_str]['expense'] += abs(amount)  # Make positive
        
        # Calculate percentage changes and format for frontend
        result = []
        for month_str in sorted(months_dict.keys()):
            data = months_dict[month_str]
            
            income = data['income']
            expense = data['expense']
            
            # Calculate percentage changes
            money_in_change = 0
            money_out_change = 0
            
            if previous_income is not None:
                if previous_income > 0:
                    money_in_change = ((income - previous_income) / previous_income) * 100
                elif income > previous_income:
                    money_in_change = 100
            
            if previous_expense is not None:
                if previous_expense > 0:
                    money_out_change = ((expense - previous_expense) / previous_expense) * 100
                elif expense > previous_expense:
                    money_out_change = 100
            
            result.append({
                'month': month_str,
                'moneyIn': round(income, 2),
                'moneyOut': round(expense, 2),
                'moneyInChange': round(money_in_change, 1),
                'moneyOutChange': round(money_out_change, 1)
            })
            
            previous_income = income
            previous_expense = expense
        
        # If no data, return empty array
        if not result:
            return Response([], status=status.HTTP_200_OK)

        cache.set(cache_key, result, DASHBOARD_CACHE_TTL)
        return Response(result, status=status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f"Error fetching billing summary for dashboard: {e}", exc_info=True)
        return Response(
            {"detail": f"Error fetching billing summary: {str(e)}"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
