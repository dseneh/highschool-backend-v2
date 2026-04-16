from datetime import datetime

from django.db.models import Avg, Count, Q, Sum, F, Case, When, DecimalField, Prefetch
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView
from ..access_policies import StudentAccessPolicy

from common.file_generators import FileGenerator, FileGeneratorConfig
from academics.models import AcademicYear, GradeLevel, Section
from accounting.models import AccountingStudentBill
from finance.models import Currency

from ..models import Enrollment, Student
from ..serializers.bill_summary import (
    BillSummaryGradeLevelSerializer,
    BillSummarySectionSerializer,
    BillSummaryStudentSerializer,
)

class BillSummaryPagination(PageNumberPagination):
    page_size = 100
    page_size_query_param = "page_size"
    max_page_size = 200

class StudentBillSummaryView(APIView):
    permission_classes = [StudentAccessPolicy]
    """
    Get bill summary for students grouped by grade level, section, or individual students
    for a selected academic year.
    
    Query Parameters:
    - academic_year_id: Required. Academic year to get summary for (use "current" for current year)
    - view_type: Required. One of 'grade_level', 'section', 'student'
    - grade_level_id: Required if view_type is 'section' or 'student'
    - section_id: Required if view_type is 'student'
    - search: Optional. Search by student name, grade level name, or section name
    
    Example URLs:
    - Grade Level Summary: /api/students/bill-summary/?academic_year_id=current&view_type=grade_level
    - Section Summary: /api/students/bill-summary/?academic_year_id=current&view_type=section&grade_level_id={grade_id}
    - Student Summary: /api/students/bill-summary/?academic_year_id=current&view_type=student&section_id={section_id}
    """
    pagination_class = BillSummaryPagination

    def get(self, request):
        try:
            
            # Get query parameters
            academic_year_id = request.query_params.get("academic_year_id")
            view_type = request.query_params.get("view_type")
            grade_level_id = request.query_params.get("grade_level_id")
            section_id = request.query_params.get("section_id")
            search = request.query_params.get("search", "").strip()

            # Validate required parameters
            validation_error = self._validate_parameters(
                academic_year_id, view_type, grade_level_id, section_id
            )
            if validation_error:
                return validation_error

            # Get academic year
            academic_year = self._get_academic_year(academic_year_id)
            if not academic_year:
                return Response(
                    {"detail": "Academic year not found or no current academic year set"}, 
                    status=status.HTTP_404_NOT_FOUND
                )

            # Route to appropriate handler based on view_type
            if view_type == "grade_level":
                return self._get_grade_level_summary(request, academic_year, search)
            elif view_type == "section":
                return self._get_section_summary(request, academic_year, grade_level_id, search)
            elif view_type == "student":
                return self._get_student_summary(request, academic_year, section_id, search)

        except Exception as e:
            return Response(
                {"detail": f"Error retrieving bill summary: {str(e)}"}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def _validate_parameters(self, academic_year_id, view_type, grade_level_id, section_id):
        """Validate request parameters and return error response if invalid"""
        if not academic_year_id:
            return Response(
                {"detail": "academic_year_id is required"}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        if not view_type or view_type not in ['grade_level', 'section', 'student']:
            return Response(
                {
                    "detail": "view_type must be one of: grade_level, section, student",
                    "valid_options": ['grade_level', 'section', 'student']
                }, 
                status=status.HTTP_400_BAD_REQUEST
            )

        if view_type in ['section'] and not grade_level_id:
            return Response(
                {"detail": f"grade_level_id is required when view_type is '{view_type}'"}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        if view_type == 'student' and not section_id:
            return Response(
                {"detail": "section_id is required when view_type is 'student'"}, 
                status=status.HTTP_400_BAD_REQUEST
            )

        return None

    def _get_academic_year(self, academic_year_id):
        """Get academic year by ID or current academic year"""
        try:
            if academic_year_id == "current":
                return AcademicYear.objects.filter(active=True).first()
            else:
                return AcademicYear.objects.filter(id=academic_year_id).first()
        except Exception:
            return None

    def _get_school_currency(self):
        """Get the default currency information"""
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

    def _get_grade_level_summary(self, request, academic_year, search):
        """Get bill summary grouped by grade level and enrolled_as"""
        
        # Base query for enrollments with their grade levels (tenant-filtered)
        enrollments_query = Enrollment.objects.filter(
            academic_year=academic_year,
            section__grade_level__active=True
        ).select_related('section__grade_level', 'student')

        # Apply search filter on grade level
        if search:
            enrollments_query = enrollments_query.filter(
                Q(section__grade_level__name__icontains=search) | 
                Q(section__grade_level__short_name__icontains=search)
            )

        # Group by grade level and enrolled_as, then aggregate from accounting bills.
        grade_level_summaries = enrollments_query.values(
            'section__grade_level__id',
            'section__grade_level__name', 
            'section__grade_level__level',
            'enrolled_as'
        ).annotate(
            student_count=Count('student', distinct=True)
        ).order_by('section__grade_level__level', 'enrolled_as')

        for summary in grade_level_summaries:
            enrollment_ids = list(
                enrollments_query.filter(
                section__grade_level__id=summary['section__grade_level__id'],
                enrolled_as=summary['enrolled_as']
                ).values_list('id', flat=True)
            )

            accounting_totals = AccountingStudentBill.objects.filter(
                enrollment_id__in=enrollment_ids,
                academic_year=academic_year,
            ).aggregate(
                total_bills=Sum('net_amount', output_field=DecimalField(max_digits=15, decimal_places=2)),
                total_paid=Sum('paid_amount', output_field=DecimalField(max_digits=15, decimal_places=2)),
                total_concessions=Sum('concession_amount', output_field=DecimalField(max_digits=15, decimal_places=2)),
            )

            summary['total_bills'] = accounting_totals.get('total_bills') or 0
            summary['total_paid'] = accounting_totals.get('total_paid') or 0
            summary['total_concessions'] = accounting_totals.get('total_concessions') or 0
            
            # Calculate correct average bill per student
            if summary['student_count'] > 0 and summary['total_bills']:
                summary['avg_bill_per_student'] = round(
                    summary['total_bills'] / summary['student_count'], 2
                )
            else:
                summary['avg_bill_per_student'] = 0

        # Paginate results
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(grade_level_summaries, request)
        
        # Get currency information
        currency = self._get_school_currency()
        
        if page is not None:
            serializer = BillSummaryGradeLevelSerializer(page, many=True)
            paginated_response = paginator.get_paginated_response(serializer.data)
            # Add currency to paginated response
            paginated_response.data['currency'] = currency
            paginated_response.data['academic_year'] = {
                "id": academic_year.id,
                "name": academic_year.name,
                "current": academic_year.current
            }
            paginated_response.data['view_type'] = "grade_level"
            return paginated_response

        serializer = BillSummaryGradeLevelSerializer(grade_level_summaries, many=True)
        
        # Calculate totals for the response
        total_summary = self._calculate_school_totals(academic_year)
        
        # Get currency information
        currency = self._get_school_currency()
        
        return Response({
            "results": serializer.data,
            "academic_year": {
                "id": academic_year.id,
                "name": academic_year.name,
                "current": academic_year.current
            },
            "currency": currency,
            "school_summary": total_summary,
            "view_type": "grade_level"
        }, status=status.HTTP_200_OK)

    def _get_section_summary(self, request, academic_year, grade_level_id, search):
        """Get bill summary grouped by section and enrolled_as within a grade level"""
        
        # Get and validate grade level (tenant-filtered)
        grade_level = get_object_or_404(
            GradeLevel.objects.filter(active=True), 
            id=grade_level_id
        )

        # Base query for enrollments in sections within the grade level (tenant-filtered)
        enrollments_query = Enrollment.objects.filter(
            academic_year=academic_year,
            section__grade_level=grade_level,
            section__active=True
        ).select_related('section', 'student')

        # Apply search filter on section name
        if search:
            enrollments_query = enrollments_query.filter(section__name__icontains=search)

        # Group by section and enrolled_as, then aggregate from accounting bills.
        section_summaries = enrollments_query.values(
            'section__id',
            'section__name',
            'enrolled_as'
        ).annotate(
            student_count=Count('student', distinct=True)
        ).order_by('section__name', 'enrolled_as')

        for summary in section_summaries:
            enrollment_ids = list(
                enrollments_query.filter(
                section__id=summary['section__id'],
                enrolled_as=summary['enrolled_as']
                ).values_list('id', flat=True)
            )

            accounting_totals = AccountingStudentBill.objects.filter(
                enrollment_id__in=enrollment_ids,
                academic_year=academic_year,
            ).aggregate(
                total_bills=Sum('net_amount', output_field=DecimalField(max_digits=15, decimal_places=2)),
                total_paid=Sum('paid_amount', output_field=DecimalField(max_digits=15, decimal_places=2)),
                total_concessions=Sum('concession_amount', output_field=DecimalField(max_digits=15, decimal_places=2)),
            )

            summary['total_bills'] = accounting_totals.get('total_bills') or 0
            summary['total_paid'] = accounting_totals.get('total_paid') or 0
            summary['total_concessions'] = accounting_totals.get('total_concessions') or 0
            
            # Calculate correct average bill per student
            if summary['student_count'] > 0 and summary['total_bills']:
                summary['avg_bill_per_student'] = round(
                    summary['total_bills'] / summary['student_count'], 2
                )
            else:
                summary['avg_bill_per_student'] = 0

        # Paginate results
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(section_summaries, request)
        
        # Get currency information
        currency = self._get_school_currency()
        
        if page is not None:
            serializer = BillSummarySectionSerializer(page, many=True)
            paginated_response = paginator.get_paginated_response(serializer.data)
            # Add currency to paginated response
            paginated_response.data['currency'] = currency
            paginated_response.data['academic_year'] = {
                "id": academic_year.id,
                "name": academic_year.name,
                "current": academic_year.current
            }
            paginated_response.data['grade_level'] = {
                "id": grade_level.id,
                "name": grade_level.name,
                "level": grade_level.level
            }
            paginated_response.data['view_type'] = "section"
            return paginated_response

        serializer = BillSummarySectionSerializer(section_summaries, many=True)
        
        # Calculate grade level totals
        grade_level_summary = self._calculate_grade_level_totals(grade_level, academic_year)
        
        # Get currency information
        currency = self._get_school_currency()
        
        return Response({
            "results": serializer.data,
            "academic_year": {
                "id": academic_year.id,
                "name": academic_year.name,
                "current": academic_year.current
            },
            "currency": currency,
            "grade_level": {
                "id": grade_level.id,
                "name": grade_level.name,
                "level": grade_level.level
            },
            "grade_level_summary": grade_level_summary,
            "view_type": "section"
        }, status=status.HTTP_200_OK)

    def _get_student_summary(self, request, academic_year, section_id, search):
        """Get bill summary for individual students within a section"""
        
        # Get and validate section (tenant-filtered)
        section = get_object_or_404(
            Section.objects.filter(active=True).select_related('grade_level'), 
            id=section_id
        )

        # Base query for students enrolled in the section for the academic year (tenant-filtered)
        students_query = Student.objects.filter(
            active=True,
            enrollments__academic_year=academic_year,
            enrollments__section=section
        ).distinct()

        # Apply search filter
        if search:
            students_query = students_query.filter(
                Q(first_name__icontains=search) | 
                Q(last_name__icontains=search) |
                Q(id_number__icontains=search)
            )

        # Annotate enrollment presence only; billing figures are pulled from accounting tables.
        students = students_query.annotate(
            enrollment_status=Count(
                'enrollments',
                filter=Q(
                    enrollments__academic_year=academic_year,
                    enrollments__section=section
                )
            )
        ).order_by('last_name', 'first_name')

        for student in students:
            accounting_totals = AccountingStudentBill.objects.filter(
                student=student,
                academic_year=academic_year,
            ).aggregate(
                total_bills=Sum('net_amount', output_field=DecimalField(max_digits=15, decimal_places=2)),
                total_paid=Sum('paid_amount', output_field=DecimalField(max_digits=15, decimal_places=2)),
                total_concessions=Sum('concession_amount', output_field=DecimalField(max_digits=15, decimal_places=2)),
            )

            student.total_bills = accounting_totals.get('total_bills') or 0
            student.total_paid = accounting_totals.get('total_paid') or 0
            student.total_concessions = accounting_totals.get('total_concessions') or 0
            student.gross_total_bills = (student.total_bills or 0) + (student.total_concessions or 0)

        # Paginate results
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(students, request)
        
        # Get currency information
        currency = self._get_school_currency()
        
        if page is not None:
            serializer = BillSummaryStudentSerializer(page, many=True, context={
                'academic_year': academic_year,
                'section': section
            })
            paginated_response = paginator.get_paginated_response(serializer.data)
            # Add currency to paginated response
            paginated_response.data['currency'] = currency
            paginated_response.data['academic_year'] = {
                "id": academic_year.id,
                "name": academic_year.name,
                "current": academic_year.current
            }
            paginated_response.data['section'] = {
                "id": section.id,
                "name": section.name,
                "grade_level": {
                    "id": section.grade_level.id,
                    "name": section.grade_level.name,
                    "level": section.grade_level.level
                }
            }
            paginated_response.data['view_type'] = "student"
            return paginated_response

        serializer = BillSummaryStudentSerializer(students, many=True, context={
            'academic_year': academic_year,
            'section': section
        })
        
        # Calculate section totals
        section_summary = self._calculate_section_totals(section, academic_year)
        
        # Get currency information
        currency = self._get_school_currency()
        
        return Response({
            "results": serializer.data,
            "academic_year": {
                "id": academic_year.id,
                "name": academic_year.name,
                "current": academic_year.current
            },
            "currency": currency,
            "section": {
                "id": section.id,
                "name": section.name,
                "grade_level": {
                    "id": section.grade_level.id,
                    "name": section.grade_level.name,
                    "level": section.grade_level.level
                }
            },
            "section_summary": section_summary,
            "view_type": "student"
        }, status=status.HTTP_200_OK)

    def _calculate_school_totals(self, academic_year):
        """Calculate total bill summary using optimized queries (tenant-filtered)"""
        bill_summary = AccountingStudentBill.objects.filter(
            academic_year=academic_year
        ).aggregate(
            total_students=Count('student', distinct=True),
            total_bills=Sum('net_amount', output_field=DecimalField(max_digits=15, decimal_places=2)),
            total_paid=Sum('paid_amount', output_field=DecimalField(max_digits=15, decimal_places=2)),
            total_concessions=Sum('concession_amount', output_field=DecimalField(max_digits=15, decimal_places=2)),
        )

        bill_summary['total_bills'] = bill_summary.get('total_bills') or 0
        bill_summary['total_paid'] = bill_summary.get('total_paid') or 0
        bill_summary['total_concessions'] = bill_summary.get('total_concessions') or 0
        return bill_summary

    def _calculate_grade_level_totals(self, grade_level, academic_year):
        """Calculate total bill summary for a grade level using optimized queries"""
        bill_summary = AccountingStudentBill.objects.filter(
            academic_year=academic_year,
            enrollment__section__grade_level=grade_level,
        ).aggregate(
            total_students=Count('student', distinct=True),
            total_bills=Sum('net_amount', output_field=DecimalField(max_digits=15, decimal_places=2)),
            total_paid=Sum('paid_amount', output_field=DecimalField(max_digits=15, decimal_places=2)),
            total_concessions=Sum('concession_amount', output_field=DecimalField(max_digits=15, decimal_places=2)),
        )

        bill_summary['total_bills'] = bill_summary.get('total_bills') or 0
        bill_summary['total_paid'] = bill_summary.get('total_paid') or 0
        bill_summary['total_concessions'] = bill_summary.get('total_concessions') or 0
        return bill_summary

    def _calculate_section_totals(self, section, academic_year):
        """Calculate total bill summary for a section using optimized queries"""
        bill_summary = AccountingStudentBill.objects.filter(
            academic_year=academic_year,
            enrollment__section=section,
        ).aggregate(
            total_students=Count('student', distinct=True),
            total_bills=Sum('net_amount', output_field=DecimalField(max_digits=15, decimal_places=2)),
            total_paid=Sum('paid_amount', output_field=DecimalField(max_digits=15, decimal_places=2)),
            total_concessions=Sum('concession_amount', output_field=DecimalField(max_digits=15, decimal_places=2)),
        )

        bill_summary['total_bills'] = bill_summary.get('total_bills') or 0
        bill_summary['total_paid'] = bill_summary.get('total_paid') or 0
        bill_summary['total_concessions'] = bill_summary.get('total_concessions') or 0
        return bill_summary

class StudentBillSummaryDownloadView(APIView):
    permission_classes = [StudentAccessPolicy]
    """
    Download student billing summary as Excel or CSV file with optional filters.
    
    Query Parameters:
    - academic_year_id: Optional. Academic year to filter by (use "current" for current year). Defaults to current.
    - grade_level_id: Optional. Filter by specific grade level
    - section_id: Optional. Filter by specific section
    - enrolled_as: Optional. Filter by enrollment type (boarder, day_student, etc.)
    - status: Optional. Filter by enrollment status (active, inactive, etc.)
    - format: Optional. File format - 'csv' or 'excel'. Defaults to 'excel'
    
    Example URLs:
    - All students: /api/students/bill-summary/download/
    - Current year only: /api/students/bill-summary/download/?academic_year_id=current
    - Specific grade: /api/students/bill-summary/download/?grade_level_id={grade_id}
    - Specific section: /api/students/bill-summary/download/?section_id={section_id}
    - Boarders only: /api/students/bill-summary/download/?enrolled_as=boarder
    - CSV format: /api/students/bill-summary/download/?format=csv
    """
    
    def get(self, request):
        try:
            
            # Get query parameters
            academic_year_id = request.query_params.get("academic_year_id", "current")
            grade_level_id = request.query_params.get("grade_level_id")
            section_id = request.query_params.get("section_id")
            enrolled_as = request.query_params.get("enrolled_as")
            enrollment_status = request.query_params.get("status")
            file_format = request.query_params.get("file_format", "excel").lower()
            
            # Validate format
            if file_format not in ['csv', 'excel']:
                return Response(
                    {"detail": "format must be either 'csv' or 'excel'"}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Get academic year (tenant-filtered)
            if academic_year_id == "current":
                academic_year = AcademicYear.objects.filter(active=True).first()
            else:
                academic_year = AcademicYear.objects.filter(id=academic_year_id).first()
            
            if not academic_year:
                return Response(
                    {"detail": "Academic year not found or no current academic year set"}, 
                    status=status.HTTP_404_NOT_FOUND
                )
            
            # OPTIMIZATION: Use select_related and prefetch_related for efficient querying
            # Build base query with optimized joins (tenant-filtered)
            students_query = Student.objects.filter(
                enrollments__academic_year=academic_year
            ).distinct()
            
            # Build enrollment filter
            enrollment_filters = Q(academic_year=academic_year)
            
            # Apply optional filters
            if grade_level_id:
                grade_level = GradeLevel.objects.filter(id=grade_level_id).first()
                if not grade_level:
                    return Response(
                        {"detail": "Grade level not found"}, 
                        status=status.HTTP_404_NOT_FOUND
                    )
                enrollment_filters &= Q(section__grade_level=grade_level)
            
            if section_id:
                section = Section.objects.filter(id=section_id).first()
                if not section:
                    return Response(
                        {"detail": "Section not found"}, 
                        status=status.HTTP_404_NOT_FOUND
                    )
                enrollment_filters &= Q(section=section)
            
            if enrolled_as:
                enrollment_filters &= Q(enrolled_as=enrolled_as)
            
            if enrollment_status:
                enrollment_filters &= Q(status=enrollment_status)
            
            # OPTIMIZATION: Prefetch enrollments with related data to avoid N+1 queries
            enrollments_prefetch = Prefetch(
                'enrollments',
                queryset=Enrollment.objects.filter(enrollment_filters).select_related(
                    'section__grade_level'
                ).prefetch_related(
                    Prefetch(
                        'accounting_bills',
                        queryset=AccountingStudentBill.objects.filter(
                            academic_year=academic_year
                        ).prefetch_related(
                            'lines__fee_item'
                        )
                    )
                )
            )
            
            # Apply prefetch and get students
            students = students_query.prefetch_related(
                enrollments_prefetch,
            ).order_by('last_name', 'first_name')
            
            # Get currency
            currency = Currency.objects.first()
            currency_symbol = currency.symbol if currency else ''
            
            # OPTIMIZATION: Process data in memory efficiently
            student_data = self._prepare_student_data_optimized(
                students, 
                academic_year, 
                enrollment_filters
            )
            
            # Generate file using reusable file generator
            return self._generate_download(
                student_data, 
                academic_year, 
                currency_symbol, 
                file_format
            )
                
        except Exception as e:
            return Response(
                {"detail": f"Error generating download: {str(e)}"}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def _prepare_student_data_optimized(self, students, academic_year, enrollment_filters):
        """
        OPTIMIZED: Prepare student data using prefetched relationships
        This avoids N+1 queries by using prefetched data
        """
        student_data = []
        
        for student in students:
            # Use prefetched enrollments (no additional query)
            enrollment = None
            for enr in student.enrollments.all():
                if enr.academic_year_id == academic_year.id:
                    enrollment = enr
                    break
            
            if not enrollment:
                continue
            
            # OPTIMIZATION: Calculate bills from prefetched accounting bills (no additional query)
            tuition = 0
            other_fees = 0
            gross_total_bills = 0
            total_concessions = 0
            net_total_bills = 0
            total_paid = 0

            for bill in enrollment.accounting_bills.all():
                gross_total_bills += float(bill.gross_amount or 0)
                total_concessions += float(bill.concession_amount or 0)
                net_total_bills += float(bill.net_amount or 0)
                total_paid += float(bill.paid_amount or 0)

                for line in bill.lines.all():
                    line_amount = float(line.line_amount or 0)
                    category = getattr(getattr(line, 'fee_item', None), 'category', '')
                    if category == 'tuition':
                        tuition += line_amount
                    else:
                        other_fees += line_amount
            
            # Calculate balance and percent paid
            balance = net_total_bills - total_paid
            percent_paid = 0
            if net_total_bills > 0:
                percent_paid = (total_paid / net_total_bills) * 100
            
            student_data.append({
                'student_id': student.id_number or student.id,
                'student_name': f"{student.first_name} {student.last_name}",
                'grade_level': enrollment.section.grade_level.name if enrollment.section else '',
                'section': enrollment.section.name if enrollment.section else '',
                'en_as': enrollment.get_enrolled_as_display() if enrollment else '',
                'tuition': tuition,
                'others': other_fees,
                'gross_total_bills': gross_total_bills,
                'total_concessions': total_concessions,
                'total_bills': net_total_bills,
                'total_paid': total_paid,
                'balance': balance,
                'percent_paid': round(percent_paid, 2),
            })
        
        return student_data
    
    def _generate_download(self, student_data, academic_year, currency_symbol, file_format):
        """
        Generate download file using reusable file generator utility
        """
        # Configure file generation
        config = FileGeneratorConfig(
            title="Student Billing Summary",
            filename_prefix=f"student_billing_summary_{academic_year.name.replace(' ', '_')}",
            headers=[
                'Student ID',
                'Student Name',
                'Grade Level',
                'Section',
                'En. As',
                f'Tuition ({currency_symbol})',
                f'Others ({currency_symbol})',
                f'Concession ({currency_symbol})',
                f'Total Bills ({currency_symbol})',
                f'Total Paid ({currency_symbol})',
                f'Balance ({currency_symbol})',
                'Percent Paid (%)',
            ],
            metadata={
                'Academic Year': academic_year.name,
            }
        )
        
        # Define totals calculator
        def calculate_totals(data, headers):
            if not data:
                return []
            
            total_tuition = sum(row['tuition'] for row in data)
            total_others = sum(row['others'] for row in data)
            total_concessions = sum(row['total_concessions'] for row in data)
            total_bills = sum(row['total_bills'] for row in data)
            total_paid = sum(row['total_paid'] for row in data)
            total_balance = sum(row['balance'] for row in data)
            avg_percent = (total_paid / total_bills * 100) if total_bills > 0 else 0
            
            return [
                'TOTALS',
                f'{len(data)} students',
                '',
                '',
                '',
                total_tuition,
                total_others,
                total_concessions,
                total_bills,
                total_paid,
                total_balance,
                round(avg_percent, 2),
            ]
        
        # Generate file
        return FileGenerator.generate_file(
            data=student_data,
            config=config,
            file_format=file_format,
            include_totals=True,
            totals_calculator=calculate_totals
        )

