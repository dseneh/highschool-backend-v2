from django.db.models import Q, Sum, Count
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from ..access_policies import StudentAccessPolicy

from academics.models import GradeLevel, AcademicYear
from finance.models import Currency

from ..models import StudentEnrollmentBill

class BillSummaryMetadataView(APIView):
    permission_classes = [StudentAccessPolicy]
    """
    Get metadata for bill summary filtering including available academic years,
    grade levels, and sections.
    """

    def get(self, request):
        try:
            # Get currency information (tenant-filtered)
            currency = self._get_school_currency()
            
            # Get academic years with billing data (tenant-filtered)
            academic_years = AcademicYear.objects.filter(
                enrollments__student_bills__isnull=False
            ).distinct().values('id', 'name', 'start_date', 'end_date', 'current').order_by('-start_date')
            
            # Get current academic year details
            current_year = AcademicYear.objects.filter(active=True).first()
            
            # Get grade levels with students in current year
            grade_levels = []
            if current_year:
                grade_levels = GradeLevel.objects.filter(
                    active=True,
                    enrollments__academic_year=current_year
                ).distinct().values('id', 'name', 'level').order_by('level')
            
            return Response({
                'currency': currency,
                'current_academic_year': {
                    'id': current_year.id,
                    'name': current_year.name
                } if current_year else None,
                'academic_years': list(academic_years),
                'grade_levels': list(grade_levels),
                'view_types': [
                    {'value': 'grade_level', 'label': 'By Grade Level'},
                    {'value': 'section', 'label': 'By Section'},
                    {'value': 'student', 'label': 'By Student'}
                ]
            })
            
        except Exception as e:
            return Response(
                {'detail': f'Error retrieving metadata: {str(e)}'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def _get_school_currency(self):
        """Get the default currency information (tenant-filtered)"""
        try:
            currency = Currency.objects.first()
            if currency:
                return {
                    "name": currency.name,
                    "code": currency.code,
                    "symbol": currency.symbol
                }
            return None
        except Exception:
            return None

class BillSummaryQuickStatsView(APIView):
    permission_classes = [StudentAccessPolicy]
    """
    Get quick statistics for bill summary including totals
    for the current academic year.
    """

    def get(self, request):
        try:
            current_year = AcademicYear.objects.filter(active=True).first()
            
            if not current_year:
                return Response({
                    'school': {'id': school.id, 'name': school.name},
                    'message': 'No current academic year set for this school',
                    'stats': {}
                })
            
            # Get overall statistics
            stats = StudentEnrollmentBill.objects.filter(
                enrollment__academic_year=current_year,
                enrollment__student__school=school
            ).aggregate(
                total_students=Count('enrollment__student', distinct=True),
                total_bills=Sum('amount'),
                total_bill_count=Count('id')
            )
            
            # Get grade level count
            grade_level_count = school.grade_levels.filter(
                active=True,
                enrollments__academic_year=current_year
            ).distinct().count()
            
            # Get section count
            section_count = school.grade_levels.filter(
                active=True,
                sections__enrollments__academic_year=current_year
            ).values('sections').distinct().count()
            
            # Calculate payment statistics (if transaction model exists)
            payment_stats = {}
            try:
                from finance.models import Transaction  # Adjust import as needed
                payment_stats = Transaction.objects.filter(
                    academic_year=current_year,
                    type__type='income'
                ).aggregate(
                    total_paid=Sum('amount', filter=Q(status='approved')),
                    pending_payments=Sum('amount', filter=Q(status='pending'))
                )
            except ImportError:
                # Fallback if transaction model structure is different
                payment_stats = {
                    'total_paid': 0,
                    'pending_payments': 0
                }
            
            # Calculate balance and percentage paid
            total_bills = float(stats.get('total_bills') or 0)
            total_paid = float(payment_stats.get('total_paid') or 0)
            balance = total_bills - total_paid
            
            # Calculate percentage paid
            if total_bills > 0:
                percent_paid = round((total_paid / total_bills) * 100, 2)
            else:
                percent_paid = 0.0
            
            # Get currency information (tenant-filtered)
            currency = self._get_school_currency()
            
            return Response({
                'currency': currency,
                'academic_year': {
                    'id': current_year.id,
                    'name': current_year.name
                },
                'stats': {
                    'total_students': stats.get('total_students', 0),
                    'total_grade_levels': grade_level_count,
                    'total_sections': section_count,
                    'total_bills': total_bills,
                    'total_paid': total_paid,
                    'outstanding_balance': balance,
                    'percent_paid': percent_paid,
                    'total_bill_items': stats.get('total_bill_count', 0),
                    'average_bill_per_student': float(round(
                        total_bills / stats.get('total_students', 1), 2
                    )) if stats.get('total_students') else 0.0
                }
            })
            
        except Exception as e:
            return Response(
                {'detail': f'Error retrieving quick stats: {str(e)}'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def _get_school_currency(self):
        """Get the default currency information (tenant-filtered)"""
        try:
            currency = Currency.objects.first()
            if currency:
                return {
                    "name": currency.name,
                    "code": currency.code,
                    "symbol": currency.symbol
                }
            return None
        except Exception:
            return None