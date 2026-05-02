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
from django.core.cache import cache
from django.utils import timezone
from academics.models import AcademicYear, GradeLevel
from students.models import Student, Enrollment, Attendance
from common.cache_service import DataCache
import logging

DASHBOARD_CACHE_TTL = 3600  # 1 hour — dashboard aggregates change infrequently

logger = logging.getLogger(__name__)


def _resolve_academic_year(request):
    """
    Resolve the academic year to filter dashboard data by.

    Looks for an ``academic_year`` UUID on the query string and falls back
    to the tenant's current academic year. Returns ``None`` if neither is
    configured.
    """
    year_id = request.GET.get('academic_year') or None
    year = None
    if year_id:
        year = AcademicYear.objects.filter(id=year_id).first()
    if not year:
        year = AcademicYear.objects.filter(current=True).first()
    return year


def _year_cache_suffix(academic_year):
    return f"_ay_{academic_year.id}" if academic_year else "_ay_none"


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
        current_academic_year = _resolve_academic_year(request)
        cache_key = DataCache._get_cache_key(
            f"dashboard_grade_distribution{_year_cache_suffix(current_academic_year)}",
            request=request,
        )
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached, status=status.HTTP_200_OK)

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
        
        # Pre-fetch section breakdown for all grades in one query
        section_qs = Enrollment.objects.filter(
            academic_year=current_academic_year,
            section__isnull=False,
        ).values(
            'grade_level__id',
            'section__id',
            'section__name',
        ).annotate(count=Count('id')).order_by('grade_level__id', 'section__name')

        sections_by_grade = {}
        for row in section_qs:
            gid = str(row['grade_level__id'])
            sections_by_grade.setdefault(gid, []).append({
                'section': row['section__name'],
                'section_id': str(row['section__id']),
                'count': row['count'],
            })

        result = []
        for dist in distributions:
            grade_id = str(dist['grade_level__id'])
            result.append({
                'grade_level': dist['grade_level__name'],
                'grade_id': grade_id,
                'count': dist['count'],
                'percentage': round((dist['count'] / total * 100), 1) if total > 0 else 0,
                'level': dist['grade_level__level'],
                'sections': sections_by_grade.get(grade_id, []),
            })

        cache.set(cache_key, result, DASHBOARD_CACHE_TTL)
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
        current_academic_year = _resolve_academic_year(request)
        cache_key = DataCache._get_cache_key(
            f"dashboard_payment_status{_year_cache_suffix(current_academic_year)}",
            request=request,
        )
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached, status=status.HTTP_200_OK)

        from accounting.models import AccountingStudentBill
        if not current_academic_year:
            return Response([], status=status.HTTP_200_OK)
        
        # Build payment status from accounting bills (source of truth).
        bills = AccountingStudentBill.objects.filter(
            academic_year=current_academic_year
        ).exclude(status=AccountingStudentBill.BillStatus.CANCELLED)
        
        status_counts = {
            'paid': 0,
            'partially_paid': 0,
            'pending': 0,
            'overdue': 0
        }
        
        today = timezone.localdate()
        for bill in bills:
            if (bill.outstanding_amount or 0) <= 0 or bill.status == AccountingStudentBill.BillStatus.PAID:
                status_counts['paid'] += 1
            elif bill.due_date and bill.due_date < today:
                status_counts['overdue'] += 1
            elif (bill.paid_amount or 0) > 0:
                status_counts['partially_paid'] += 1
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

        cache.set(cache_key, result, DASHBOARD_CACHE_TTL)
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
        current_academic_year = _resolve_academic_year(request)
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
        current_academic_year = _resolve_academic_year(request)
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
        current_academic_year = _resolve_academic_year(request)
        cache_key = DataCache._get_cache_key(
            f"dashboard_payment_summary{_year_cache_suffix(current_academic_year)}",
            request=request,
        )
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached, status=status.HTTP_200_OK)

        from django.db.models import Sum
        from accounting.models import AccountingStudentBill
        
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
        
        bill_totals = AccountingStudentBill.objects.filter(
            academic_year=current_academic_year
        ).exclude(
            status=AccountingStudentBill.BillStatus.CANCELLED
        ).aggregate(
            total_expected=Coalesce(Sum('net_amount'), 0),
            total_paid=Coalesce(Sum('paid_amount'), 0),
        )

        total_bills = bill_totals.get('total_expected') or 0
        total_paid = bill_totals.get('total_paid') or 0
        
        total_expected = float(total_bills)
        total_paid = float(total_paid)
        total_pending = total_expected - total_paid
        collection_rate = round((total_paid / total_expected * 100), 1) if total_expected > 0 else 0

        result = {
            'total_expected': total_expected,
            'total_paid': total_paid,
            'total_pending': max(0, total_pending),  # Ensure non-negative
            'collection_rate': collection_rate,
            'enrollment_count': enrollments_count
        }
        cache.set(cache_key, result, DASHBOARD_CACHE_TTL)
        return Response(result, status=status.HTTP_200_OK)
    
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

    Query params:
        marking_period (uuid, optional): If provided, restricts grades to assessments
            tied to the given marking period. Otherwise uses all approved grades for
            the current academic year.

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
        marking_period_id = request.GET.get('marking_period') or None
        current_academic_year = _resolve_academic_year(request)

        cache_suffix = f"_mp_{marking_period_id}" if marking_period_id else ""
        cache_suffix += _year_cache_suffix(current_academic_year)
        cache_key = DataCache._get_cache_key(
            f"dashboard_top_students{cache_suffix}", request=request
        )
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached, status=status.HTTP_200_OK)

        from grading.models import Grade

        if not current_academic_year:
            return Response([], status=status.HTTP_200_OK)

        # One-query aggregate avoids the expensive per-student/per-gradebook loops.
        percentage_expr = ExpressionWrapper(
            (F('score') * 100.0) / F('assessment__max_score'),
            output_field=FloatField(),
        )

        grade_qs = Grade.objects.filter(
            academic_year=current_academic_year,
            status='approved',
            assessment__is_calculated=True,
            score__isnull=False,
            assessment__max_score__gt=0,
        )

        if marking_period_id:
            grade_qs = grade_qs.filter(assessment__marking_period_id=marking_period_id)

        top_students_qs = (
            grade_qs
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

        cache.set(cache_key, top_students, DASHBOARD_CACHE_TTL)
        return Response(top_students, status=status.HTTP_200_OK)
    
    except Exception as e:
        logger.error(f"Error in get_top_students_by_grade: {str(e)}")
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_honor_distribution(request):
    """
    Distribute students across the school's configured honor categories based on
    their cumulative final-grade average for the current (or supplied) academic year.

    Returns a list of category buckets plus an "Unclassified" bucket for students
    whose average falls outside any configured band.

    [
        {
            "id": "<uuid or 'unclassified'>",
            "label": "Principal's List",
            "min_average": 95,
            "max_average": 100,
            "color": "#...",
            "icon": "",
            "order": 1,
            "count": 12,
            "percentage": 8.3
        },
        ...
    ]
    """
    try:
        current_academic_year = _resolve_academic_year(request)

        cache_key = DataCache._get_cache_key(
            f"dashboard_honor_distribution{_year_cache_suffix(current_academic_year)}",
            request=request,
        )
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(cached, status=status.HTTP_200_OK)

        if not current_academic_year:
            return Response([], status=status.HTTP_200_OK)

        from grading.models import Grade, HonorCategory

        percentage_expr = ExpressionWrapper(
            (F('score') * 100.0) / F('assessment__max_score'),
            output_field=FloatField(),
        )

        averages_qs = (
            Grade.objects.filter(
                academic_year=current_academic_year,
                status='approved',
                assessment__is_calculated=True,
                score__isnull=False,
                assessment__max_score__gt=0,
            )
            .values('student_id')
            .annotate(final_average=Avg(percentage_expr))
        )

        student_averages = [
            float(row['final_average'])
            for row in averages_qs
            if row['final_average'] is not None
        ]
        total_students = len(student_averages)

        categories = list(
            HonorCategory.objects.filter(active=True).order_by('order', '-max_average')
        )

        buckets = []
        remaining_total = total_students
        for cat in categories:
            count = sum(
                1
                for avg in student_averages
                if float(cat.min_average) <= avg <= float(cat.max_average)
            )
            remaining_total -= count
            buckets.append({
                'id': str(cat.id),
                'label': cat.label,
                'min_average': float(cat.min_average),
                'max_average': float(cat.max_average),
                'color': cat.color or '',
                'icon': cat.icon or '',
                'order': cat.order,
                'count': count,
                'percentage': (
                    round((count / total_students) * 100, 1) if total_students else 0
                ),
            })

        # Unclassified = students with an average who don't fit any active category
        unclassified_count = max(remaining_total, 0)
        buckets.append({
            'id': 'unclassified',
            'label': 'Unclassified',
            'min_average': None,
            'max_average': None,
            'color': '',
            'icon': '',
            'order': 9999,
            'count': unclassified_count,
            'percentage': (
                round((unclassified_count / total_students) * 100, 1)
                if total_students else 0
            ),
        })

        payload = {
            'total_students': total_students,
            'categories': buckets,
        }
        cache.set(cache_key, payload, DASHBOARD_CACHE_TTL)
        return Response(payload, status=status.HTTP_200_OK)

    except Exception as e:
        logger.error(f"Error in get_honor_distribution: {str(e)}")
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
