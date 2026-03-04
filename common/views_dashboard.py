"""
Dashboard summary API views with optimized statistics.
Uses cached reference data for maximum performance.
"""
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from django.db.models import Count, Sum
from django.utils import timezone
from decimal import Decimal

from common.cache_service import DataCache
from users.models import User
import logging

logger = logging.getLogger(__name__)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_dashboard_summary(request):
    """
    Get comprehensive dashboard summary with optimized statistics.
    
    Query Parameters:
        - academic_year_id: Filter data by specific academic year (optional, uses current if not provided)
        - force_refresh: If 'true', bypass cache for reference data
    
    Returns:
        Dictionary containing:
        - overview: General school statistics
        - students: Student enrollment statistics (if students app available)
        - finance: Financial overview (if finance models available)
        - metadata: Generation metadata
    """
    try:
        tenant = request
        
        # Get query parameters
        force_refresh = request.query_params.get('force_refresh', 'false').lower() == 'true'
        academic_year_id = request.query_params.get('academic_year_id')
        
        # Get current academic year if not provided
        if not academic_year_id:
            current_year = DataCache.get_current_academic_year(force_refresh)
            academic_year_id = current_year['id'] if current_year else None
        
        # Get cached reference data
        divisions = DataCache.get_divisions(force_refresh)
        grade_levels = DataCache.get_grade_levels(force_refresh)
        sections = DataCache.get_sections(academic_year_id, force_refresh)
        subjects = DataCache.get_subjects(force_refresh)
        academic_years = DataCache.get_academic_years(force_refresh)
        
        # Build comprehensive summary
        summary = {
            'overview': _get_overview_stats(divisions, grade_levels, sections, subjects, academic_years, academic_year_id),
            'metadata': {
                'academic_year_id': academic_year_id,
                'generated_at': timezone.now().isoformat(),
            }
        }
        
        # Add optional sections if apps are available
        try:
            summary['students'] = _get_student_stats(academic_year_id)
        except Exception as e:
            logger.error(f"Could not fetch student stats for tenant: {e}", exc_info=True)
            summary['students'] = {'error': 'Students data not available', 'detail': str(e)}
        
        try:
            summary['finance'] = _get_finance_stats(academic_year_id)
        except Exception as e:
            logger.error(f"Could not fetch finance stats for tenant: {e}", exc_info=True)
            summary['finance'] = {'error': 'Finance data not available', 'detail': str(e)}
        
        return Response(summary, status=status.HTTP_200_OK)
        
    except Exception as e:
        logger.error(f"Error fetching dashboard summary for tenant: {e}", exc_info=True)
        return Response(
            {'error': 'Failed to fetch dashboard summary', 'detail': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


def _get_overview_stats(divisions, grade_levels, sections, subjects, academic_years, academic_year_id):
    """Get general overview statistics."""
    # Count staff/users
    try:
        staff_count = User.objects.filter(
            # school=school,
            is_active=True
        ).exclude(role='student').count()
    except:
        staff_count = 0
    
    # Count enrollments for the specific academic year
    try:
        from students.models import Enrollment
        if academic_year_id:
            active_students = Enrollment.objects.filter(
                academic_year_id=academic_year_id,
            ).count()
        else:
            # Fallback to all active students if no academic year
            from students.models import Student
            active_students = Student.objects.filter(
                status__in=['active', 'enrolled']
            ).count()
    except:
        active_students = 0
    
    # Filter only active items from cached reference data
    active_divisions = [d for d in divisions if d.get('active', True)]
    active_grade_levels = [g for g in grade_levels if g.get('active', True)]
    active_sections = [s for s in sections if s.get('active', True)]
    active_subjects = [subj for subj in subjects if subj.get('active', True)]
    
    return {
        'total_students': active_students,
        'total_staff': staff_count,
        'total_divisions': len(active_divisions),
        'total_grade_levels': len(active_grade_levels),
        'total_sections': len(active_sections),
        'total_subjects': len(active_subjects),
        'total_academic_years': len(academic_years),
        'current_academic_year': next((y for y in academic_years if y.get('current')), None),
    }


def _get_student_stats(academic_year_id):
    """Get detailed student enrollment statistics."""
    from students.models import Student, Enrollment
    
    # Base query for all students in school
    all_students_query = Student.objects.filter(status__in=['active', 'enrolled'])
    
    # If academic year is provided, filter students by enrollment in that year
    if academic_year_id:
        # Get students enrolled in the specific academic year
        enrolled_student_ids = Enrollment.objects.filter(
            academic_year_id=academic_year_id,
        ).values_list('student_id', flat=True)
        
        all_students_query = all_students_query.filter(id__in=enrolled_student_ids)
    
    # Active students only
    active_query = all_students_query.filter(status__in=['active', 'enrolled'])
    
    # Total active students
    total_active = active_query.count()
    
    # Students by status
    status_stats = all_students_query.values('status').annotate(count=Count('id')).order_by('-count')
    
    # Students by gender (active only)
    gender_stats = active_query.values('gender').annotate(count=Count('id'))
    
    # Calculate gender percentages
    gender_with_percentage = {}
    for stat in gender_stats:
        gender = stat['gender']
        count = stat['count']
        percentage = round((count / total_active * 100), 2) if total_active > 0 else 0
        gender_with_percentage[gender] = {
            'count': count,
            'percentage': percentage
        }
    
    # Students by grade level (active only)
    # If academic year is provided, use enrollment grade level
    if academic_year_id:
        grade_stats = Enrollment.objects.filter(
            academic_year_id=academic_year_id,
            student__status__in=['enrolled']
        ).values(
            'grade_level__short_name',
            'grade_level__level'
        ).annotate(
            count=Count('id')
        ).order_by('grade_level__level')
    else:
        # Fall back to current grade level if no academic year specified
        grade_stats = active_query.filter(
            grade_level__isnull=False
        ).values(
            'grade_level__short_name',
            'grade_level__level'
        ).annotate(
            count=Count('id')
        ).order_by('grade_level__level')
    
    # New enrollments (last 30 days)
    thirty_days_ago = timezone.now() - timezone.timedelta(days=30)
    if academic_year_id:
        recent_enrollments = Enrollment.objects.filter(
            academic_year_id=academic_year_id,
            created_at__gte=thirty_days_ago
        ).count()
    else:
        recent_enrollments = active_query.filter(
            created_at__gte=thirty_days_ago
        ).count()
    
    return {
        'total_active': total_active,
        'by_status': list(status_stats),
        'by_gender': gender_with_percentage,
        'by_grade_level': list(grade_stats),
        'recent_enrollments_30_days': recent_enrollments,
    }


def _get_finance_stats(academic_year_id):
    """Get financial overview statistics."""
    from finance.models import Transaction
    
    # Base queries
    transactions_query = Transaction.objects.all()
    
    # Filter by academic year if provided
    if academic_year_id:
        transactions_query = transactions_query.filter(academic_year_id=academic_year_id)
    
    # Recent transactions (last 7 days)
    seven_days_ago = timezone.now() - timezone.timedelta(days=7)
    recent_transactions = transactions_query.filter(
        created_at__gte=seven_days_ago
    ).aggregate(
        count=Count('id'),
        total_amount=Sum('amount')
    )
    
    # Income vs Expenses - Transaction model uses 'type' field
    income = transactions_query.filter(
        type__type='income'
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    
    expense = transactions_query.filter(
        type__type='expense'
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    
    # Transaction count
    total_transactions = transactions_query.count()
    
    return {
        'total_transactions': total_transactions,
        'recent_transactions_7_days': {
            'count': recent_transactions['count'] or 0,
            'total_amount': float(recent_transactions['total_amount'] or 0)
        },
        'income_vs_expense': {
            'income': float(income),
            'expense': abs(float(expense)),
            'balance': float(income - abs(expense))
        }
    }
