"""
Student bill recreation utilities and views
"""
from datetime import datetime, timezone
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from ..access_policies import StudentAccessPolicy

from academics.models import GradeLevel, Section

from ..models import Enrollment, Student, StudentEnrollmentBill
from ..views.utils import create_student_bill

class BillRecreationView(APIView):
    permission_classes = [StudentAccessPolicy]
    """
    Recreate student bills by grade level, section, or individual student.
    
    This API efficiently handles:
    1. Deleting existing bills for the target scope
    2. Recreating bills based on current fee structures
    3. Bulk operations with database optimization
    
    Supported scopes:
    - grade_level: All students in a specific grade level
    - section: All students in a specific section
    - student: Individual student
    
    URL Parameters:
    - scope: Required. One of 'grade_level', 'section', 'student'
    - target_id: Required. ID of the grade level, section, or student
    - academic_year_id: Optional. Defaults to current academic year
    - diff_only: Optional. If 'true', only recreate bills for students with differences
    
    Example URLs:
    POST /api/students/bills/recreate/?scope=grade_level&target_id={grade_level_id}
    POST /api/students/bills/recreate/?scope=section&target_id={section_id}&diff_only=true
    POST /api/students/bills/recreate/?scope=student&target_id={student_id}
    """

    def post(self, request):
        """Recreate student bills based on the specified scope and target"""
        
        try:
            # Get and validate parameters
            scope = request.query_params.get('scope')
            target_id = request.query_params.get('target_id')
            academic_year_id = request.query_params.get('academic_year_id')
            diff_only = request.query_params.get('diff_only', '').lower() == 'true'
            
            if not scope or not target_id:
                return Response({
                    'detail': 'Both scope and target_id parameters are required',
                    'valid_scopes': ['grade_level', 'section', 'student']
                }, status=status.HTTP_400_BAD_REQUEST)
                
            if scope not in ['grade_level', 'section', 'student']:
                return Response({
                    'detail': 'Invalid scope. Must be one of: grade_level, section, student'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Get enrollments based on scope
            enrollments_query = self._get_enrollments_by_scope(scope, target_id, academic_year_id)
            
            if not enrollments_query.exists():
                return Response({
                    'detail': 'No enrollments found for the specified scope and target'
                }, status=status.HTTP_404_NOT_FOUND)
            
            # Filter for differential processing if requested
            if diff_only:
                enrollments_with_diffs = self._filter_enrollments_with_differences(enrollments_query)
                if not enrollments_with_diffs:
                    return Response({
                        'detail': 'No enrollments found with bill differences',
                        'message': 'All student bills are already up to date',
                        'scope': scope,
                        'target_id': target_id,
                        'diff_only': True,
                        'total_checked': enrollments_query.count(),
                        'with_differences': 0
                    }, status=status.HTTP_200_OK)
                
                enrollments_to_process = enrollments_with_diffs
                enrollment_count = len(enrollments_to_process)
            else:
                enrollments_to_process = enrollments_query
                enrollment_count = enrollments_query.count()
            
            # Import here to avoid circular imports
            from ..tasks import BillRecreationTaskManager, MockBillRecreationProcessor
            
            # Check if we should use background processing
            if BillRecreationTaskManager.should_use_background(enrollment_count):
                # Create background task
                task_id = BillRecreationTaskManager.create_recreation_task(
                    scope=scope,
                    target_id=target_id,
                    enrollment_count=enrollment_count,
                    academic_year_id=academic_year_id,
                    user_id=request.user.id,
                    diff_only=diff_only
                )
                
                # Start background processing
                MockBillRecreationProcessor.process_bill_recreation(task_id, request)
                
                return Response({
                    'task_id': task_id,
                    'status': 'pending',
                    'processing_mode': 'background',
                    'enrollment_count': enrollment_count,
                    'diff_only': diff_only,
                    'message': f'Bill recreation started in background for {enrollment_count} students' + 
                              (' (diff only)' if diff_only else ''),
                    'check_status_url': f'/api/students/bills/recreate/status/{task_id}/'
                }, status=status.HTTP_202_ACCEPTED)
            
            else:
                # Process synchronously for smaller datasets
                with transaction.atomic():
                    if diff_only:
                        result = self._recreate_bills_for_enrollments_list(enrollments_to_process, request)
                    else:
                        result = self._recreate_bills_for_enrollments(enrollments_to_process, request)
                    
                return Response({
                    'detail': 'Bills recreated successfully',
                    'scope': scope,
                    'target_id': target_id,
                    'processing_mode': 'synchronous',
                    'diff_only': diff_only,
                    'results': result
                }, status=status.HTTP_200_OK)
                
        except Exception as e:
            return Response({
                'detail': f'Error recreating bills: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def _get_enrollments_by_scope(self, scope, target_id, academic_year_id):
        """Get enrollments based on the specified scope"""
        
        # Base query with optimizations
        base_query = Enrollment.objects.select_related(
            'student', 'academic_year', 'grade_level', 'section'
        ).prefetch_related(
            'student_bills', 'section__section_fees__general_fee', 'grade_level__tuition_fees'
        )
        
        # Academic year filter
        if academic_year_id and academic_year_id != 'current':
            base_query = base_query.filter(academic_year_id=academic_year_id)
        else:
            base_query = base_query.filter(academic_year__current=True)
        
        if scope == 'grade_level':
            # Get all enrollments in the specified grade level
            grade_level = get_object_or_404(GradeLevel, id=target_id)
            return base_query.filter(section__grade_level=grade_level)
            
        elif scope == 'section':
            # Get all enrollments in the specified section
            section = get_object_or_404(Section, id=target_id)
            return base_query.filter(section=section)
            
        elif scope == 'student':
            # Get enrollment for the specified student
            f = Q(id=target_id) | Q(id_number=target_id)
            student = get_object_or_404(Student, f)
            return base_query.filter(student=student)
    
    def _filter_enrollments_with_differences(self, enrollments_query):
        """
        Filter enrollments to only those where current bills differ from estimated bills
        
        Returns:
            list: List of enrollment objects that have billing differences
        """
        enrollments_with_diffs = []
        
        for enrollment in enrollments_query:
            if self._enrollment_has_bill_differences(enrollment):
                enrollments_with_diffs.append(enrollment)
        
        return enrollments_with_diffs
    
    def _enrollment_has_bill_differences(self, enrollment):
        """
        Check if an enrollment has differences between current and estimated bills
        
        Returns:
            bool: True if there are differences, False otherwise
        """
        try:
            # Get current bills
            existing_bills = enrollment.student_bills.all()
            existing_bill_total = sum(bill.amount for bill in existing_bills)
            
            # Get estimated bills (reuse logic from preview)
            estimated_bills = self._estimate_bills_for_enrollment(enrollment)
            estimated_total = sum(bill['amount'] for bill in estimated_bills)
            
            # Check for differences in total amount
            if abs(float(estimated_total) - float(existing_bill_total)) > 0.01:  # 1 cent tolerance
                return True
            
            # Check for differences in bill count
            if len(estimated_bills) != existing_bills.count():
                return True
            
            # Check for differences in individual bill amounts (more detailed)
            existing_bills_dict = {}
            for bill in existing_bills:
                key = f"{bill.type}_{bill.name}"
                existing_bills_dict[key] = float(bill.amount)
            
            estimated_bills_dict = {}
            for bill in estimated_bills:
                key = f"{bill['type']}_{bill['name']}"
                estimated_bills_dict[key] = float(bill['amount'])
            
            # Compare bill-by-bill
            if existing_bills_dict != estimated_bills_dict:
                return True
            
            return False
            
        except Exception:
            # If we can't determine differences, assume there are differences (safer)
            return True
    
    def _estimate_bills_for_enrollment(self, enrollment):
        """
        Estimate what bills would be created for an enrollment
        (Extracted from BillRecreationPreviewView for reuse)
        """
        estimated_bills = []
        
        try:
            # Estimate section fees
            all_section_fees = enrollment.section.section_fees.select_related(
                "general_fee"
            ).filter(active=True)
            
            for section_fee in all_section_fees:
                target_type = section_fee.general_fee.student_target
                if target_type == enrollment.enrolled_as or not target_type or target_type == "":
                    estimated_bills.append({
                        'name': section_fee.general_fee.name,
                        'amount': float(section_fee.amount),
                        'type': 'General'
                    })
            
            # Estimate tuition fee
            tuition_fee = enrollment.grade_level.tuition_fees.filter(
                targeted_student_type=enrollment.enrolled_as
            ).first()
            
            if tuition_fee and tuition_fee.amount:
                estimated_bills.append({
                    'name': 'Tuition',
                    'amount': float(tuition_fee.amount),
                    'type': 'Tuition'
                })
                
        except Exception:
            # If estimation fails, return empty list
            pass
        
        return estimated_bills
    
    def _recreate_bills_for_enrollments(self, enrollments, request):
        """Efficiently recreate bills for the given enrollments"""
        
        # Get all enrollment IDs for bulk operations
        enrollment_ids = list(enrollments.values_list('id', flat=True))
        
        # Step 1: Bulk delete existing bills
        deleted_bills_count = StudentEnrollmentBill.objects.filter(
            enrollment_id__in=enrollment_ids
        ).delete()[0]
        
        # Step 2: Recreate bills for each enrollment
        created_bills = []
        failed_enrollments = []
        
        for enrollment in enrollments:
            try:
                # Use existing utility function to create bills
                bills = create_student_bill(enrollment, request)
                created_bills.extend(bills)
                
            except Exception as e:
                failed_enrollments.append({
                    'enrollment_id': enrollment.id,
                    'student_name': enrollment.student.get_full_name(),
                    'error': str(e)
                })
        
        return {
            'enrollments_processed': len(enrollment_ids),
            'bills_deleted': deleted_bills_count,
            'bills_created': len(created_bills),
            'failed_enrollments': failed_enrollments,
            'success_rate': f"{((len(enrollment_ids) - len(failed_enrollments)) / len(enrollment_ids) * 100):.1f}%" if enrollment_ids else "0%"
        }
    
    def _recreate_bills_for_enrollments_list(self, enrollments_list, request):
        """Efficiently recreate bills for a list of enrollment objects"""
        
        # Get all enrollment IDs for bulk operations
        enrollment_ids = [enrollment.id for enrollment in enrollments_list]
        
        # Step 1: Bulk delete existing bills
        deleted_bills_count = StudentEnrollmentBill.objects.filter(
            enrollment_id__in=enrollment_ids
        ).delete()[0]
        
        # Step 2: Recreate bills for each enrollment
        created_bills = []
        failed_enrollments = []
        
        for enrollment in enrollments_list:
            try:
                # Use existing utility function to create bills
                bills = create_student_bill(enrollment, request)
                created_bills.extend(bills)
                
            except Exception as e:
                failed_enrollments.append({
                    'enrollment_id': enrollment.id,
                    'student_name': enrollment.student.get_full_name(),
                    'error': str(e)
                })
        
        return {
            'enrollments_processed': len(enrollment_ids),
            'bills_deleted': deleted_bills_count,
            'bills_created': len(created_bills),
            'failed_enrollments': failed_enrollments,
            'success_rate': f"{((len(enrollment_ids) - len(failed_enrollments)) / len(enrollment_ids) * 100):.1f}%" if enrollment_ids else "0%"
        }

class BillRecreationPreviewView(APIView):
    permission_classes = [StudentAccessPolicy]
    """
    Preview what bills would be recreated without actually making changes.
    
    This endpoint allows users to see what will happen before executing the recreation.
    """
    
    def get(self, request):
        """Preview bill recreation without making changes"""
        
        try:
            # Get and validate parameters (same as recreation view)
            scope = request.query_params.get('scope')
            target_id = request.query_params.get('target_id')
            academic_year_id = request.query_params.get('academic_year_id')
            diff_only = request.query_params.get('diff_only', '').lower() == 'true'
            
            if not scope or not target_id:
                return Response({
                    'detail': 'Both scope and target_id parameters are required',
                    'valid_scopes': ['grade_level', 'section', 'student']
                }, status=status.HTTP_400_BAD_REQUEST)
                
            if scope not in ['grade_level', 'section', 'student']:
                return Response({
                    'detail': 'Invalid scope. Must be one of: grade_level, section, student'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Get enrollments
            recreation_view = BillRecreationView()
            enrollments_query = recreation_view._get_enrollments_by_scope(scope, target_id, academic_year_id)
            
            if not enrollments_query.exists():
                return Response({
                    'detail': 'No enrollments found for the specified scope and target'
                }, status=status.HTTP_404_NOT_FOUND)
            
            # Filter for differential preview if requested
            if diff_only:
                enrollments_with_diffs = recreation_view._filter_enrollments_with_differences(enrollments_query)
                if not enrollments_with_diffs:
                    return Response({
                        'scope': scope,
                        'target_id': target_id,
                        'diff_only': True,
                        'preview': {
                            'summary': {
                                'total_enrollments': 0,
                                'enrollments_with_differences': 0,
                                'total_checked': enrollments_query.count(),
                                'message': 'No students have bill differences - all are up to date'
                            },
                            'enrollments': []
                        }
                    }, status=status.HTTP_200_OK)
                
                enrollments_to_preview = enrollments_with_diffs
            else:
                enrollments_to_preview = list(enrollments_query)
            
            # Generate preview data
            preview_data = self._generate_preview(enrollments_to_preview, diff_only)
            
            return Response({
                'scope': scope,
                'target_id': target_id,
                'diff_only': diff_only,
                'preview': preview_data
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            return Response({
                'detail': f'Error generating preview: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def _generate_preview(self, enrollments, diff_only=False):
        """Generate preview data showing what would be recreated"""
        
        preview = {
            'summary': {
                'total_enrollments': 0,
                'total_existing_bills': 0,
                'total_current_amount': 0.0,
                'estimated_new_bills': 0,
                'estimated_new_amount': 0.0,
                'total_difference': 0.0,
                'percentage_change': 0.0,
                'diff_only': diff_only
            },
            'enrollments': []
        }
        
        # Handle both queryset and list inputs
        if hasattr(enrollments, 'count'):
            enrollments = list(enrollments)
        
        for enrollment in enrollments:
            # Count existing bills
            existing_bills = enrollment.student_bills.all()
            existing_bill_count = existing_bills.count()
            existing_bill_total = sum(bill.amount for bill in existing_bills)
            
            # Estimate new bills based on current fee structure
            recreation_view = BillRecreationView()
            estimated_bills = recreation_view._estimate_bills_for_enrollment(enrollment)
            estimated_count = len(estimated_bills)
            estimated_total = sum(bill['amount'] for bill in estimated_bills)
            
            # Calculate difference and percentage change
            difference = float(estimated_total) - float(existing_bill_total)
            percentage_change = 0.0
            if existing_bill_total > 0:
                percentage_change = round((difference / float(existing_bill_total)) * 100, 2)
            
            enrollment_preview = {
                'enrollment_id': enrollment.id,
                'student': {
                    'id': enrollment.student.id,
                    'name': enrollment.student.get_full_name(),
                    'id_number': enrollment.student.id_number
                },
                'section': {
                    'id': enrollment.section.id,
                    'name': enrollment.section.name,
                    'grade_level': enrollment.section.grade_level.name
                },
                'current_bills': {
                    'count': existing_bill_count,
                    'total_amount': float(existing_bill_total),
                    'bills': [
                        {
                            'id': bill.id,
                            'name': bill.name,
                            'amount': float(bill.amount),
                            'type': bill.type
                        } for bill in existing_bills
                    ]
                },
                'estimated_new_bills': {
                    'count': estimated_count,
                    'total_amount': float(estimated_total),
                    'bills': estimated_bills
                },
                'comparison': {
                    'amount_difference': difference,
                    'percentage_change': percentage_change,
                    'recommendation': self._get_recreation_recommendation(difference, percentage_change),
                    'impact_level': self._get_impact_level(abs(percentage_change))
                }
            }
            
            preview['enrollments'].append(enrollment_preview)
            
            # Update summary
            preview['summary']['total_enrollments'] += 1
            preview['summary']['total_existing_bills'] += existing_bill_count
            preview['summary']['total_current_amount'] += float(existing_bill_total)
            preview['summary']['estimated_new_bills'] += estimated_count
            preview['summary']['estimated_new_amount'] += float(estimated_total)
            preview['summary']['total_difference'] += difference
        
        # Calculate overall percentage change
        if preview['summary']['total_current_amount'] > 0:
            preview['summary']['percentage_change'] = round(
                (preview['summary']['total_difference'] / preview['summary']['total_current_amount']) * 100, 2
            )
        
        # Add overall recommendation
        preview['summary']['recommendation'] = self._get_recreation_recommendation(
            preview['summary']['total_difference'], 
            preview['summary']['percentage_change']
        )
        preview['summary']['impact_level'] = self._get_impact_level(
            abs(preview['summary']['percentage_change'])
        )
        
        return preview
    
    def _get_recreation_recommendation(self, difference, percentage_change):
        """Provide recommendation based on the financial impact"""
        
        abs_percentage = abs(percentage_change)
        
        if abs_percentage == 0:
            return "No change needed - bills are identical"
        elif abs_percentage < 1:
            return "Minor change - recreation optional"
        elif abs_percentage < 5:
            return "Small change - consider recreation if accuracy is important"
        elif abs_percentage < 15:
            return "Moderate change - recreation recommended"
        elif abs_percentage < 30:
            return "Significant change - recreation strongly recommended"
        else:
            return "Major change - recreation highly recommended"
    
    def _get_impact_level(self, abs_percentage_change):
        """Get impact level based on percentage change"""
        
        if abs_percentage_change == 0:
            return "none"
        elif abs_percentage_change < 1:
            return "minimal"
        elif abs_percentage_change < 5:
            return "low"
        elif abs_percentage_change < 15:
            return "moderate"
        elif abs_percentage_change < 30:
            return "high"
        else:
            return "critical"

class BillRecreationStatusView(APIView):
    permission_classes = [StudentAccessPolicy]
    """
    Check the status of background bill recreation tasks
    """
    
    def get(self, request, task_id):
        """Get task status and progress"""
        
        # Import here to avoid circular imports
        from ..tasks import BillRecreationTaskManager
        
        task_data = BillRecreationTaskManager.get_task(task_id)
        
        if not task_data:
            return Response({
                'detail': 'Task not found'
            }, status=status.HTTP_404_NOT_FOUND)
        
        # Calculate estimated time remaining if still processing
        eta = None
        if task_data['status'] == 'processing' and task_data['progress'] > 0:
            elapsed_time = (
                datetime.now(timezone.utc) - 
                datetime.fromisoformat(task_data['created_at'].replace('Z', '+00:00'))
            ).total_seconds()
            
            if task_data['progress'] > 5:  # Avoid division by very small numbers
                estimated_total_time = elapsed_time * (100 / task_data['progress'])
                eta = max(0, estimated_total_time - elapsed_time)
        
        response_data = {
            'task_id': task_id,
            'status': task_data['status'],
            'progress': task_data['progress'],
            'created_at': task_data['created_at'],
            'updated_at': task_data['updated_at'],
            'scope': task_data.get('scope'),
            'estimated_count': task_data.get('estimated_count', 0),
            'total_processed': task_data.get('total_processed', 0),
            'bills_deleted': task_data.get('bills_deleted', 0),
            'bills_created': task_data.get('bills_created', 0),
            'failed_count': len(task_data.get('failed_enrollments', [])),
            'eta_seconds': eta
        }
        
        # Add result data if completed
        if task_data['status'] == 'completed' and task_data.get('result'):
            response_data['result'] = task_data['result']
        
        # Add error if failed
        if task_data['status'] == 'failed' and task_data.get('error'):
            response_data['error'] = task_data['error']
        
        # Add failed enrollments if any
        if task_data.get('failed_enrollments'):
            response_data['failed_enrollments'] = task_data['failed_enrollments']
        
        return Response(response_data, status=status.HTTP_200_OK)
    
    def delete(self, request, task_id):
        """Cancel a background task (if still pending/processing)"""
        
        # Import here to avoid circular imports
        from ..tasks import BillRecreationTaskManager
        
        task_data = BillRecreationTaskManager.get_task(task_id)
        
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
        BillRecreationTaskManager.update_task(task_id, status='cancelled')
        
        return Response({
            'detail': 'Task cancelled successfully',
            'task_id': task_id
        }, status=status.HTTP_200_OK)