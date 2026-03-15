"""
Dashboard distribution endpoints for meaningful data visualizations.

Provides:
- Grade level distribution (students by grade)
- Payment status distribution (students by payment status)
- Attendance distribution (present vs absent)
- Section distribution (students per class)
"""

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from django.db.models import Count, Q, F, Case, When, Value as V, CharField, Avg, FloatField, ExpressionWrapper
from django.db.models.functions import Coalesce
from academics.models import AcademicYear, GradeLevel
from students.models import Student, Enrollment, Attendance
import logging

logger = logging.getLogger(__name__)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_grade_level_distribution(request):
    """
    Get student distribution by grade level.
    
    Returns:
    [
        {
            "grade_level": "Grade 10",
            "grade_id": "uuid",
            "count": 45,
            "percentage": 15.5
        },
        ...
    ]
    """
    try:
        current_academic_year = AcademicYear.objects.filter(current=True).first()
        if not current_academic_year:
            return Response([], status=status.HTTP_200_OK)
        
        # Get distribution by grade level
        distributions = Enrollment.objects.filter(
            academic_year=current_academic_year
        ).values(
            'grade_level__id',
            'grade_level__name',
            'grade_level__level'
        ).annotate(
            count=Count('id')
        ).order_by('grade_level__level')
        
        # Calculate total for percentages
        total = sum(d['count'] for d in distributions)
        
        result = []
        for dist in distributions:
            result.append({
                'grade_level': dist['grade_level__name'],
                'grade_id': str(dist['grade_level__id']),
                'count': dist['count'],
                'percentage': round((dist['count'] / total * 100), 1) if total > 0 else 0,
                'level': dist['grade_level__level']
            })
        
        return Response(result, status=status.HTTP_200_OK)
    
    except Exception as e:
        logger.error(f"Error in get_grade_level_distribution: {str(e)}")
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_payment_status_distribution(request):
    """
    Get student distribution by payment status.
    
    Returns:
    [
        {
            "status": "paid",
            "count": 120,
            "percentage": 45.2,
            "total_amount": 500000
        },
        ...
    ]
    """
    try:
        from students.models import StudentPaymentSummary
        current_academic_year = AcademicYear.objects.filter(current=True).first()
        if not current_academic_year:
            return Response([], status=status.HTTP_200_OK)
        
        # Build payment status from StudentPaymentSummary
        enrollments_with_status = StudentPaymentSummary.objects.filter(
            academic_year=current_academic_year
        ).all()
        
        status_counts = {
            'paid': 0,
            'partially_paid': 0,
            'pending': 0,
            'overdue': 0
        }
        
        status_amounts = {
            'paid': 0,
            'partially_paid': 0,
            'pending': 0,
            'overdue': 0
        }
        
        for payment_summary in enrollments_with_status:
            payment_status = payment_summary.payment_status or {}
            
            # Extract status from payment_status dict
            pstatus = payment_status.get('status', 'pending')
            
            if pstatus in status_counts:
                status_counts[pstatus] += 1
            else:
                status_counts['pending'] += 1
        
        total = sum(status_counts.values())
        
        result = []
        status_order = ['paid', 'partially_paid', 'overdue', 'pending']
        
        for s in status_order:
            if status_counts[s] > 0:
                result.append({
                    'status': s.replace('_', ' ').title(),
                    'statusKey': s,
                    'count': status_counts[s],
                    'percentage': round((status_counts[s] / total * 100), 1) if total > 0 else 0,
                    'color': {
                        'paid': '#22c55e',
                        'partially_paid': '#f59e0b',
                        'overdue': '#ef4444',
                        'pending': '#6b7280'
                    }.get(s, '#6b7280')
                })
        
        return Response(result, status=status.HTTP_200_OK)
    
    except Exception as e:
        logger.error(f"Error in get_payment_status_distribution: {str(e)}")
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_attendance_distribution(request):
    """
    Get attendance distribution (present vs absent for current marking period/academic year).
    
    Returns:
    {
        "present": {
            "count": 1200,
            "percentage": 75.5
        },
        "absent": {
            "count": 250,
            "percentage": 15.8
        },
        "late": {
            "count": 150,
            "percentage": 8.7
        }
    }
    """
    try:
        current_academic_year = AcademicYear.objects.filter(current=True).first()
        if not current_academic_year:
            return Response(
                {
                    'present': {'count': 0, 'percentage': 0},
                    'absent': {'count': 0, 'percentage': 0},
                    'late': {'count': 0, 'percentage': 0}
                },
                status=status.HTTP_200_OK
            )
        
        # Get attendance distribution for the academic year
        attendance_records = Attendance.objects.filter(
            enrollment__academic_year=current_academic_year
        ).values('status').annotate(count=Count('id'))
        
        distribution = {}
        total = 0
        
        for record in attendance_records:
            status_val = record['status'].lower()
            distribution[status_val] = record['count']
            total += record['count']
        
        result = {}
        status_labels = ['present', 'absent', 'late', 'excused']
        
        for status_label in status_labels:
            count = distribution.get(status_label, 0)
            result[status_label] = {
                'count': count,
                'percentage': round((count / total * 100), 1) if total > 0 else 0
            }
        
        return Response(result, status=status.HTTP_200_OK)
    
    except Exception as e:
        logger.error(f"Error in get_attendance_distribution: {str(e)}")
        return Response(
            {
                'present': {'count': 0, 'percentage': 0},
                'absent': {'count': 0, 'percentage': 0},
                'late': {'count': 0, 'percentage': 0}
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_section_distribution(request):
    """
    Get student distribution by section/class.
    
    Returns:
    [
        {
            "section": "10-A",
            "section_id": "uuid",
            "count": 45,
            "capacity": 50,
            "utilization": 90.0
        },
        ...
    ]
    """
    try:
        current_academic_year = AcademicYear.objects.filter(current=True).first()
        if not current_academic_year:
            return Response([], status=status.HTTP_200_OK)
        
        # Get distribution by section
        distributions = Enrollment.objects.filter(
            academic_year=current_academic_year,
            section__isnull=False
        ).values(
            'section__id',
            'section__name',
            'section__grade_level__max_class_capacity'
        ).annotate(
            count=Count('id')
        ).order_by('section__name')
        
        result = []
        for dist in distributions:
            capacity = dist['section__grade_level__max_class_capacity'] or 30
            count = dist['count']
            utilization = round((count / capacity * 100), 1) if capacity > 0 else 0
            
            result.append({
                'section': dist['section__name'],
                'section_id': str(dist['section__id']),
                'count': count,
                'capacity': capacity,
                'utilization': utilization
            })
        
        return Response(result, status=status.HTTP_200_OK)
    
    except Exception as e:
        logger.error(f"Error in get_section_distribution: {str(e)}")
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_payment_summary(request):
    """
    Get financial summary: total expected vs total paid.
    
    Returns:
    {
        "total_expected": 500000,
        "total_paid": 350000,
        "total_pending": 150000,
        "collection_rate": 70.0,
        "enrollment_count": 250
    }
    """
    try:
        from django.db.models import Sum, F
        from students.models import StudentEnrollmentBill
        from finance.models import Transaction
        
        current_academic_year = AcademicYear.objects.filter(current=True).first()
        if not current_academic_year:
            return Response(
                {
                    'total_expected': 0,
                    'total_paid': 0,
                    'total_pending': 0,
                    'collection_rate': 0,
                    'enrollment_count': 0
                },
                status=status.HTTP_200_OK
            )
        
        # Get total expected bills
        enrollments_count = Enrollment.objects.filter(
            academic_year=current_academic_year
        ).count()
        
        total_bills = StudentEnrollmentBill.objects.filter(
            enrollment__academic_year=current_academic_year
        ).aggregate(total=Sum('amount'))['total'] or 0
        
        # Get total paid from transactions
        total_paid = Transaction.objects.filter(
            status='approved',
            type__type='income',
            academic_year=current_academic_year
        ).aggregate(total=Sum('amount'))['total'] or 0
        
        total_expected = float(total_bills)
        total_paid = float(total_paid)
        total_pending = total_expected - total_paid
        collection_rate = round((total_paid / total_expected * 100), 1) if total_expected > 0 else 0
        
        return Response({
            'total_expected': total_expected,
            'total_paid': total_paid,
            'total_pending': max(0, total_pending),  # Ensure non-negative
            'collection_rate': collection_rate,
            'enrollment_count': enrollments_count
        }, status=status.HTTP_200_OK)
    
    except Exception as e:
        logger.error(f"Error in get_payment_summary: {str(e)}")
        return Response(
            {
                'total_expected': 0,
                'total_paid': 0,
                'total_pending': 0,
                'collection_rate': 0,
                'enrollment_count': 0
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_top_students_by_grade(request):
    """
    Get top 5 students by cumulative final grade average.
    
    Returns:
    [
        {
            "id": "uuid",
            "full_name": "John Doe",
            "id_number": "STU001",
            "grade_level": "Grade 10",
            "final_average": 95.5
        },
        ...
    ]
    """
    try:
        from grading.models import Grade
        
        current_academic_year = AcademicYear.objects.filter(current=True).first()
        if not current_academic_year:
            return Response([], status=status.HTTP_200_OK)
        
        # One-query aggregate avoids the expensive per-student/per-gradebook loops.
        percentage_expr = ExpressionWrapper(
            (F('score') * 100.0) / F('assessment__max_score'),
            output_field=FloatField(),
        )

        top_students_qs = (
            Grade.objects.filter(
                academic_year=current_academic_year,
                status='approved',
                assessment__is_calculated=True,
                score__isnull=False,
                assessment__max_score__gt=0,
            )
            .values(
                'student_id',
                'student__first_name',
                'student__middle_name',
                'student__last_name',
                'student__id_number',
                'enrollment__grade_level__name',
            )
            .annotate(final_average=Avg(percentage_expr))
            .order_by('-final_average')[:5]
        )

        top_students = []
        for row in top_students_qs:
            full_name = " ".join(
                part for part in [row.get('student__first_name'), row.get('student__middle_name'), row.get('student__last_name')] if part
            )
            top_students.append(
                {
                    'id': str(row['student_id']),
                    'full_name': full_name,
                    'id_number': row.get('student__id_number'),
                    'grade_level': row.get('enrollment__grade_level__name') or '-',
                    'final_average': round(float(row['final_average'] or 0), 1),
                }
            )
        
        return Response(top_students, status=status.HTTP_200_OK)
    
    except Exception as e:
        logger.error(f"Error in get_top_students_by_grade: {str(e)}")
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
