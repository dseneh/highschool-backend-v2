from django.db.models import Q
from django.db import connection
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView
from django_tenants.utils import get_public_schema_name, schema_context
from ..access_policies import StudentAccessPolicy

from common.utils import get_enrollment_bill_summary, get_object_by_uuid_or_fields
from core.models import Tenant
from finance.services.billing_pdf import generate_student_billing_pdf
from finance.models import Transaction

from ..models import Enrollment, Student, StudentEnrollmentBill
from ..serializers.student_bill import (
    StudentBillDetailSerializer,
    StudentBillSerializer,
)


class StudentBillPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class StudentEnrollmentBillListView(APIView):
    permission_classes = [StudentAccessPolicy]
    """
    List student enrollment bills with filtering options
    """

    pagination_class = StudentBillPagination

    def get(self, request, student_id):
        # try:
        # Get query parameters
        year_id = request.query_params.get("academic_year_id")
        include_payment_plan = request.query_params.get("include_payment_plan", "true").lower() == "true"
        include_payment_status = request.query_params.get("include_payment_status", "true").lower() == "true"

        if not student_id:
            return Response(
                {"detail": "Student ID is required"}, status=status.HTTP_400_BAD_REQUEST
            )

        student = get_object_by_uuid_or_fields(Student, student_id)
        if not student:
            return Response(
                {"detail": "Student not found"}, status=status.HTTP_404_NOT_FOUND
            )

        year_filter = Q(enrollment__academic_year_id=year_id) if year_id else Q()
        if not year_id or year_id == "current":
            year_filter = Q(enrollment__academic_year__current=True)

        # Build base queryset
        queryset = StudentEnrollmentBill.objects.select_related(
            "enrollment",
            "enrollment__student",
            "enrollment__academic_year",
            "enrollment__grade_level",
            "enrollment__section",
        ).order_by("-created_at")

        # Filter by student if student_id is provided

        f = Q(enrollment__student=student) & year_filter
        queryset = queryset.filter(f)
        # Filter by enrollment if enrollment_id is provided
        # if enrollment_id:
        #     enrollment = get_object_or_404(Enrollment, id=enrollment_id)
        #     queryset = queryset.filter(enrollment=enrollment)

        # Additional filtering from query parameters
        # bill_type = request.GET.get('type')
        # if bill_type:
        #     queryset = queryset.filter(type=bill_type)

        # # Search by name
        # search = request.GET.get('search')
        # if search:
        #     queryset = queryset.filter(
        #         Q(name__icontains=search) |
        #         Q(notes__icontains=search)
        #     )

        # Academic year filter
        # if academic_year_id:
        #     queryset = queryset.filter(enrollment__academic_year_id=academic_year_id)

        # Amount range filters
        min_amount = request.GET.get("min_amount")
        if min_amount:
            try:
                queryset = queryset.filter(amount__gte=float(min_amount))
            except ValueError:
                pass

        max_amount = request.GET.get("max_amount")
        if max_amount:
            try:
                queryset = queryset.filter(amount__lte=float(max_amount))
            except ValueError:
                pass

        # Pagination
        # paginator = self.pagination_class()
        # page = paginator.paginate_queryset(queryset, request)

        # if page is not None:
        #     serializer = StudentEnrollmentBillSerializer(page, many=True)
        #     return paginator.get_paginated_response(serializer.data)

        # If no pagination
        serializer = StudentBillSerializer(queryset, many=True)
        enrollment = queryset.first().enrollment if queryset else None
        data = {}
        if enrollment:
            data = {
                "bill": serializer.data,
                "summary": get_enrollment_bill_summary(
                    enrollment,
                    include_payment_plan=include_payment_plan,
                    include_payment_status=include_payment_status,
                ),
            }
        return Response(data, status=status.HTTP_200_OK)

        # except Exception as e:
        #     return Response({'detail': f'Error retrieving bills: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class StudentEnrollmentBillDetailView(APIView):
    permission_classes = [StudentAccessPolicy]
    """
    Retrieve a specific student enrollment bill
    """

    def get(self, request, pk, *args, **kwargs):
        try:
            bill = get_object_or_404(
                StudentEnrollmentBill.objects.select_related(
                    "enrollment",
                    "enrollment__student",
                    "enrollment__academic_year",
                    "enrollment__grade_level",
                    "enrollment__section",
                ),
                id=pk,
            )

            serializer = StudentBillDetailSerializer(bill)
            return Response(serializer.data, status=status.HTTP_200_OK)

        except StudentEnrollmentBill.DoesNotExist:
            return Response(
                {"detail": "Bill not found"}, status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            return Response(
                {"detail": f"Error retrieving bill: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class StudentBillingPDFView(APIView):
    permission_classes = [StudentAccessPolicy]
    """
    Generate and download student billing financial statement PDF
    """

    def get(self, request, student_id):
        try:
            tenant_schema_name = connection.schema_name
            with schema_context(get_public_schema_name()):
                school = Tenant.objects.filter(schema_name=tenant_schema_name).first()

            # Get student - try UUID first, fallback to id_number
            try:
                import uuid
                uuid_obj = uuid.UUID(str(student_id))
                student = get_object_or_404(
                    Student.objects.all(), 
                    id=uuid_obj
                )
            except (ValueError, AttributeError):
                student = get_object_or_404(
                    Student.objects.all(), 
                    id_number=student_id
                )

            # Get current enrollment with related data
            enrollment = Enrollment.objects.select_related(
                'grade_level', 
                'section', 
                'academic_year'
            ).filter(
                student=student,
                academic_year__current=True
            ).first()

            if not enrollment:
                return Response(
                    {"detail": "Student has no current enrollment"},
                    status=status.HTTP_404_NOT_FOUND
                )
            
            # Get billing summary from enrollment (include payment plan for PDF)
            billing_summary = get_enrollment_bill_summary(enrollment, include_payment_plan=True)
            
            # Get bill items
            bills = StudentEnrollmentBill.objects.filter(
                enrollment=enrollment
            ).values('name', 'amount')
            bill_items = [{"name": bill['name'], "amount": bill['amount']} for bill in bills]

            # Get payment plan from billing summary
            payment_plan_data = billing_summary.get('payment_plan', []) if billing_summary else []
            
            # Get transactions
            transactions = Transaction.objects.filter(
                student=student,
                academic_year=enrollment.academic_year,
                status='approved'
            ).select_related('type', 'payment_method').order_by('-date')

            transactions_list = [
                {
                    'date': str(transaction.date),
                    'reference': transaction.reference or '',
                    'type': {'name': transaction.type.name if transaction.type else 'N/A'},
                    'payment_method': {'name': transaction.payment_method.name if transaction.payment_method else 'N/A'},
                    'amount': transaction.amount
                }
                for transaction in transactions
            ]

            # Generate PDF
            response = generate_student_billing_pdf(
                student=student,
                school=school,
                enrollment=enrollment,
                billing_summary=billing_summary,
                bill_items=bill_items,
                payment_plan=payment_plan_data,
                transactions=transactions_list
            )

            return response

        except Student.DoesNotExist:
            return Response(
                {"detail": "Student not found"},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            import traceback
            print(f"Error generating PDF: {str(e)}")
            print(traceback.format_exc())
            return Response(
                {"detail": f"Error generating PDF: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
