from django.db.models import Prefetch, Q, Sum
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from ..access_policies import FinanceAccessPolicy

from academics.models import AcademicYear
from finance.models import (
    Transaction,
    get_student_payment_plan,
    get_student_payment_status,
)
from students.models import (
    Enrollment,
    Student,
    StudentEnrollmentBill,
    StudentPaymentSummary,
)
from students.serializers.student import (
    StudentSerializer,
    StudentPaymentStatusSerializer,
)

class StudentPaymentStatusListView(APIView):
    permission_classes = [FinanceAccessPolicy]
    """
    View to list students filtered by payment status.
    Supports filtering by:
    - payment_status: "delinquent" (overdue), "paid_in_full", "on_time"
    - academic_year_id: Filter by specific academic year (defaults to current)
    - school_id: Filter by school
    """

    def get(self, request, school_id):
        """
        Get students filtered by payment status.

        Query parameters:
        - payment_status: "delinquent" (overdue), "paid_in_full", "on_time", "all"
        - academic_year_id: Optional academic year ID (defaults to current)
        - section_id: Optional section filter
        - grade_level_id: Optional grade level filter
        - include_payment_plan: Optional boolean (true/false/1/0) to include payment plan in response
        - include_payment_status: Optional boolean (true/false/1/0) to include payment status in response (defaults to true)
        """
        # Get payment status filter
        payment_status_filter = request.query_params.get("payment_status", "all")
        academic_year_id = request.query_params.get("academic_year_id")
        section_id = request.query_params.get("section_id")
        grade_level_id = request.query_params.get("grade_level_id")

        # Get include_payment_plan parameter (defaults to False)
        include_payment_plan_param = request.query_params.get(
            "include_payment_plan", "false"
        ).lower()
        include_payment_plan = include_payment_plan_param in ("true", "1", "yes", "on")

        # Get include_payment_status parameter (defaults to True since this is a payment status endpoint)
        include_payment_status_param = request.query_params.get(
            "include_payment_status", "true"
        ).lower()
        include_payment_status = include_payment_status_param in (
            "true",
            "1",
            "yes",
            "on",
        )

        # Get academic year
        if academic_year_id:
            try:
                academic_year = AcademicYear.objects.get(
                    id=academic_year_id
                )
            except AcademicYear.DoesNotExist:
                return Response(
                    {
                        "detail": "Academic year not found or does not belong to this school"
                    },
                    status=400,
                )
        else:
            academic_year = AcademicYear.get_current_academic_year()
            if not academic_year:
                return Response(
                    {"detail": "No current academic year found for this school"},
                    status=400,
                )

        # Validate payment_status filter
        valid_statuses = ["delinquent", "paid_in_full", "on_time", "all"]
        if payment_status_filter not in valid_statuses:
            return Response(
                {
                    "detail": f"Invalid payment_status. Use one of: {', '.join(valid_statuses)}"
                },
                status=400,
            )

        # Optimize queries with Prefetch to avoid N+1 queries
        # Prefetch payment summaries for all enrollments (one-to-one relationship)
        enrollments_prefetch = Prefetch(
            "enrollments",
            queryset=Enrollment.objects.filter(
                academic_year=academic_year, status="active"
            )
            .select_related("academic_year", "section", "grade_level")
            .prefetch_related(
                Prefetch("student_bills", queryset=StudentEnrollmentBill.objects.all()),
                Prefetch(
                    "payment_summary",
                    queryset=StudentPaymentSummary.objects.filter(
                        academic_year=academic_year
                    ),
                ),
            ),
        )

        # Prefetch approved transactions for this academic year
        transactions_prefetch = Prefetch(
            "transactions",
            queryset=Transaction.objects.filter(
                academic_year=academic_year, status="approved"
            ),
        )

        # Get all enrolled students for this academic year with optimized queries
        students = (
            Student.objects.filter(
                enrollments__academic_year=academic_year,
                enrollments__status="active",
            )
            .select_related("grade_level")
            .prefetch_related(
                enrollments_prefetch,
                transactions_prefetch,
            )
            .distinct()
        )

        # Apply additional filters
        if section_id:
            students = students.filter(enrollments__section_id=section_id)

        if grade_level_id:
            students = students.filter(enrollments__grade_level_id=grade_level_id)

        # Convert students queryset to list to evaluate queries once
        # This ensures prefetches are loaded before we iterate
        students_list = list(students)

        # Bulk calculate total_bills for all enrollments to avoid N+1 queries
        from decimal import Decimal
        from django.db.models import Sum

        # Collect enrollment IDs from prefetched data (no queries)
        enrollment_ids = []
        for student in students_list:
            if (
                hasattr(student, "_prefetched_objects_cache")
                and "enrollments" in student._prefetched_objects_cache
            ):
                prefetched_enrollments = student._prefetched_objects_cache[
                    "enrollments"
                ]
                enrollment_ids.extend([e.id for e in prefetched_enrollments])
            else:
                # Fallback: query if not prefetched (shouldn't happen)
                enrollment_ids.extend(
                    [
                        e.id
                        for e in student.enrollments.filter(
                            academic_year=academic_year, status="active"
                        )
                    ]
                )

        # Bulk aggregate total_bills per enrollment (single query for all enrollments)
        bills_map = {}
        if enrollment_ids:
            bills_totals = (
                StudentEnrollmentBill.objects.filter(enrollment_id__in=enrollment_ids)
                .values("enrollment_id")
                .annotate(total=Sum("amount"))
            )
            bills_map = {
                item["enrollment_id"]: Decimal(str(item["total"] or 0))
                for item in bills_totals
            }

        # Filter by payment status and prepare data
        filtered_students_data = []
        import logging

        logger = logging.getLogger(__name__)

        for student in students_list:
            # Get current enrollment from prefetched data (no query)
            # The prefetch already filtered by academic_year and status="active"
            enrollment = None
            if (
                hasattr(student, "_prefetched_objects_cache")
                and "enrollments" in student._prefetched_objects_cache
            ):
                prefetched_enrollments = student._prefetched_objects_cache[
                    "enrollments"
                ]
                if prefetched_enrollments:
                    enrollment = prefetched_enrollments[0]
            else:
                # Fallback: use filter (shouldn't happen with proper prefetch)
                enrollment = next(
                    (
                        e
                        for e in student.enrollments.all()
                        if e.academic_year_id == academic_year.id
                        and e.status == "active"
                    ),
                    None,
                )

            if not enrollment:
                continue

            # Get payment summary from prefetched data (no query)
            payment_summary = None
            if (
                hasattr(enrollment, "_prefetched_objects_cache")
                and "payment_summary" in enrollment._prefetched_objects_cache
            ):
                prefetched_summaries = enrollment._prefetched_objects_cache[
                    "payment_summary"
                ]
                if prefetched_summaries:
                    payment_summary = prefetched_summaries[0]
            else:
                # Fallback: try to get from prefetched related manager
                try:
                    payment_summary = enrollment.payment_summary.first()
                except (AttributeError, StudentPaymentSummary.DoesNotExist):
                    payment_summary = None

            # Use payment status from summary table if available, otherwise calculate
            if payment_summary and payment_summary.payment_status:
                # Use pre-calculated payment status from summary table
                payment_status = payment_summary.payment_status.copy()

                # Get total_bills from bulk-calculated map (no query)
                total_bills = bills_map.get(enrollment.id, Decimal("0"))
                payment_status["total_bills"] = float(total_bills)

                # Use total_paid from summary table
                total_paid = float(payment_summary.total_paid or 0)
                payment_status["total_paid"] = total_paid

                # Calculate balance
                payment_status["overall_balance"] = float(
                    total_bills - Decimal(str(total_paid))
                )

                # Recalculate next_due_date dynamically (not persisted)
                from finance.models import _calculate_next_due_date_dynamic

                payment_status["next_due_date"] = _calculate_next_due_date_dynamic(
                    enrollment, academic_year
                )
            else:
                # Fallback: calculate payment status (should be rare after initial population)
                # Calculate and save to summary table for next time
                payment_status = get_student_payment_status(enrollment, academic_year)

                # Get total_bills from bulk-calculated map
                total_bills = bills_map.get(enrollment.id, Decimal("0"))
                payment_status["total_bills"] = float(total_bills)

                # Save to summary table so it's available next time (lazy population)
                try:
                    from finance.utils import calculate_student_payment_summary

                    calculate_student_payment_summary(enrollment, academic_year)
                except Exception as e:
                    # Don't fail the request if summary save fails
                    logger.warning(
                        f"Failed to save payment summary for enrollment {enrollment.id}: {e}"
                    )

            # Determine overall payment status for filtering
            is_delinquent = payment_status["overdue_count"] > 0 or (
                payment_status["total_bills"] > 0
                and payment_status["total_paid"] < payment_status["total_bills"]
                and not payment_status["is_on_time"]
            )
            # For paid_in_full, we want students who have bills AND have paid them in full
            # Check directly using balance: if total_bills > 0 and overall_balance <= 0, they're paid in full
            is_paid_in_full = (
                payment_status["total_bills"] > 0
                and payment_status["overall_balance"] <= 0
            )
            is_on_time = payment_status["is_on_time"] and not is_paid_in_full

            # Apply filter
            if payment_status_filter == "delinquent" and not is_delinquent:
                continue
            elif payment_status_filter == "paid_in_full" and not is_paid_in_full:
                continue
            elif payment_status_filter == "on_time" and not is_on_time:
                continue
            # "all" includes everyone, so no filtering needed

            # Remove duplicate fields that will be in billing_summary
            # These are calculated in get_enrollment_bill_summary, so remove from payment_status
            payment_status_clean = {
                k: v
                for k, v in payment_status.items()
                if k not in ["total_bills", "total_paid", "overall_balance"]
            }

            # Store student and payment data for serialization
            student_data_item = {
                "student": student,
                "payment_status": payment_status_clean,
            }

            filtered_students_data.append(student_data_item)

        # Serialize results using minimal serializer for reduced payload
        students_list = [item["student"] for item in filtered_students_data]
        serializer = StudentPaymentStatusSerializer(
            students_list,
            many=True,
            context={
                "request": request,
                "include_payment_plan": include_payment_plan,
                "include_payment_status": include_payment_status,
            },
        )

        # Add payment status and optionally payment plan to each student
        response_data = []
        for student_data, item in zip(serializer.data, filtered_students_data):
            # student_data["payment_status"] = item["payment_status"]

            # Add payment plan if it was requested and available
            # if include_payment_plan and "payment_plan" in item:
            #     student_data["payment_plan"] = item["payment_plan"]

            response_data.append(student_data)

        return Response(
            {
                "count": len(response_data),
                "results": response_data,
                "filters": {
                    "payment_status": payment_status_filter,
                    "academic_year": {
                        "id": academic_year.id,
                        "name": academic_year.name,
                    },
                },
            }
        )
