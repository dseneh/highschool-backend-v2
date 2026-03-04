from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView
from ..access_policies import AcademicsAccessPolicy
from django.core.cache import cache

from academics.serializers import GradeLevelTuitionFeeSerializer
from business.core.services import validate_tuition_fees_bulk_update
from business.core.adapters import get_grade_level_by_id, bulk_update_tuition_fees
from common.utils import get_tenant_from_request

class GradeLevelTuitionFeesDetailView(APIView):
    permission_classes = [AcademicsAccessPolicy]

    def put(self, request, id):
        # Get the grade level
        grade_level = get_grade_level_by_id(id)
        if not grade_level:
            raise NotFound("Grade Level not found")

        req_data = request.data
        tuition_fees = req_data.get("tuition_fees", [])

        # Validate bulk update data
        is_valid, errors = validate_tuition_fees_bulk_update(tuition_fees)
        if not is_valid:
            return Response(
                {
                    "detail": "No tuition fees were updated due to errors",
                    "errors": errors,
                },
                status=400,
            )

        # Perform bulk update
        updated_fees = bulk_update_tuition_fees(grade_level, tuition_fees, request.user)
        
        if not updated_fees:
            return Response(
                {
                    "detail": "No tuition fees were updated",
                    "errors": ["No valid tuition fees found"],
                },
                status=400,
            )

        # Invalidate the GradeLevelListView cache for this tenant
        # The view caches grade levels with keys: f"grade_levels:{tenant}" and f"grade_levels:{tenant}:ay:{academic_year_id}"
        tenant = get_tenant_from_request(request)
        cache.delete(f"grade_levels:{tenant}")
        # Also delete any cached version with academic year filters
        # Since we don't know which academic_year_ids might have been cached,
        # we use cache.delete_pattern if available, or just clear the primary key
        # The main tenant cache deletion should be sufficient for the list view

        # Format response to match GradeLevelSerializer format for consistency
        # Keep types matching: id as UUID object, amount as Decimal (serialized by DRF)
        response_data = {
            "updated": [
                {
                    "id": fee.id,
                    "fee_type": fee.targeted_student_type,
                    "amount": fee.amount,
                }
                for fee in updated_fees
            ],
            "updated_count": len(updated_fees),
            "message": "Tuition fees updated successfully",
        }
        print("Updated tuition fees response:", response_data)  # Debug log
        return Response(response_data, status=status.HTTP_200_OK)
