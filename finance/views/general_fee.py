from django.db import transaction
from django.db.models import Q
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView
from ..access_policies import FinanceAccessPolicy

from common.utils import (
    create_model_data,
    update_model_fields,
    validate_required_fields,
)
from academics.models import Section
from finance.models import GeneralFeeList, SectionFee
from finance.serializers import GeneralFeeSerializer, SectionFeeDetailSerializer

class GeneralFeeListView(APIView):
    permission_classes = [FinanceAccessPolicy]
    """
    Tenant context is provided by x-tenant header via middleware.
    """

    def get(self, request):
        # General fees are tenant-scoped via middleware
        general_fees = GeneralFeeList.objects.only(
            "id", "name", "description", "amount", "student_target", "active"
        )

        serializer = GeneralFeeSerializer(general_fees, many=True)
        return Response(serializer.data)

    def post(self, request):
        """Create a new general fee"""
        apply_to_all_sections = request.data.get("apply_to_all_sections", False)

        req_data = request.data

        required_fields = ["name", "amount", "student_target"]

        missing_fields = validate_required_fields(request, required_fields)
        # if missing_fields:
        #     return Response(
        #         {"detail": f"Missing required fields: {', '.join(missing_fields)}"},
        #         status=400,
        #     )

        data = {
            "name": req_data["name"],
            "amount": req_data["amount"],
            "student_target": req_data["student_target"],
            "description": req_data.get("description", ""),
        }

        try:
            with transaction.atomic():

                fees = GeneralFeeList.objects.create(**data)

                if apply_to_all_sections:
                    # Apply to all sections in current tenant
                    sections = (
                        Section.objects.filter(active=True)
                        .only("id")
                        .iterator(chunk_size=100)
                    )
                    for section in sections:
                        section_fee_data = {
                            "section": section,
                            "general_fee": fees,
                            "amount": data["amount"],
                        }

                        SectionFee.objects.update_or_create(
                            section=section, general_fee=fees, defaults=section_fee_data
                        )

                serializer = GeneralFeeSerializer(fees)
                return Response(serializer.data, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response({"detail": str(e)}, status=500)

class GeneralFeeDetailView(APIView):
    permission_classes = [FinanceAccessPolicy]
    """
    View to retrieve, update or delete a specific general fee.
    """

    def get_object(self, pk):
        try:
            return GeneralFeeList.objects.get(pk=pk)
        except GeneralFeeList.DoesNotExist:
            raise NotFound("General fee not found with this id")

    def get(self, request, pk):
        """Get a specific general fee"""
        general_fee = self.get_object(pk)
        serializer = GeneralFeeSerializer(general_fee)
        return Response(serializer.data)

    def put(self, request, id):
        """Update a specific general fee"""
        general_fee = self.get_object(id)
        req_data = request.data
        apply_to_all_sections = req_data.get("apply_to_all_sections", False)

        update_fields = ["name", "amount", "student_target", "active"]
        # validate_required_fields(request, required_fields)

        # Removed print statement to prevent memory leaks in production

        try:
            with transaction.atomic():
                fees = update_model_fields(
                    request, general_fee, update_fields, GeneralFeeSerializer
                )
                if apply_to_all_sections:
                    # update amount for all sections
                    section_fees = SectionFee.objects.filter(general_fee=general_fee)
                    section_fees.update(
                        amount=req_data.get("amount", general_fee.amount),
                    )

                return fees
        except Exception as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, id):
        """Delete a specific section fee"""
        general_fee = self.get_object(id)
        general_fee.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
