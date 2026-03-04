from django.db import transaction
from django.db.models import Q
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView
from ..access_policies import FinanceAccessPolicy
import logging

from common.utils import create_model_data, update_model_fields_core
from common.cache_service import DataCache
from academics.models import Section
from finance.models import GeneralFeeList, SectionFee
from finance.serializers import SectionFeeSerializer

logger = logging.getLogger(__name__)

class SectionFeeListView(APIView):
    permission_classes = [FinanceAccessPolicy]
    # permission_classes = [AllowAny]
    def get_section_object(self, id):
        try:
            return Section.objects.get(id=id)
        except Section.DoesNotExist:
            raise NotFound("Section does not exist with this id")
    
    def _invalidate_cache(self, request, section: Section = None):
        """Invalidate section caches after fee modifications"""
        # DataCache.invalidate_sections expects request object, not school_id string
        DataCache.invalidate_sections(request)
        logger.debug("Invalidated section cache")

    def get(self, request, section_id):
        section = self.get_section_object(section_id)

        # 🔥 MEMORY FIX: Use select_related + only + iterator for optimisation
        fee = (
            section.section_fees.select_related("section", "general_fee")
            .only(
                "id",
                "section_id",
                "general_fee_id", 
                "amount",
                "active",
                "section__name",
                "general_fee__name",
                "general_fee__description",
                "general_fee__student_target",
            )
            .iterator(chunk_size=100)
        )
        serializer = SectionFeeSerializer(fee, many=True)

        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request, section_id):
        section = self.get_section_object(section_id)
        req_data: dict = request.data

        fee_ids = req_data.get("fees", [])

        if not fee_ids:
            return Response({"detail": "fee ids are required"}, status=400)

        created_fees = []
        errors = []

        try:
            with transaction.atomic():
                for fee_id in fee_ids:
                    fee = GeneralFeeList.objects.filter(id=fee_id).first()

                    if not fee:
                        errors.append(f"Fee with id '{fee_id}' does not exist")
                        continue

                    data = {
                        "section_id": section.id,
                        "general_fee_id": fee.id,
                        "amount": fee.amount,
                        "created_by_id": request.user.id,
                        "updated_by_id": request.user.id,
                    }

                    section_fee, created = section.section_fees.get_or_create(**data)
                    if created:
                        created_fees.append(section_fee)
                    else:
                        continue
                        # errors.append(f"Fee '{fee.name}' is already assigned to this section")

                # If there are any errors, rollback the transaction
                if errors:
                    raise Exception("Transaction rolled back due to errors")

        except Exception as e:
            # All changes are rolled back automatically
            if "Transaction rolled back" not in str(e):
                errors.append(f"Database error: {str(e)}")
            return Response(
                {"detail": "No fees were created due to errors", "errors": errors},
                status=400,
            )

        # If we reach here, all fees were created successfully
        if created_fees:
            # Invalidate sections cache to refresh tuition_fees
            self._invalidate_cache(request, section)
            
            serializer = SectionFeeSerializer(created_fees, many=True)
            response_data = {
                "created": serializer.data,
                "created_count": len(created_fees),
                "message": "All fees assigned successfully",
            }
            return Response(response_data, status=status.HTTP_201_CREATED)
        else:
            return Response(
                {
                    "detail": "No new fees were assigned (all fees already exist in this section)"
                },
                status=200,
            )

class SectionFeeDetailView(APIView):
    permission_classes = [FinanceAccessPolicy]
    # permission_classes = [IsAuthenticatedOrReadOnly, IsAdminOrSystemAdmin]
    def get_object(self, id):
        try:
            return SectionFee.objects.get(id=id)
        except SectionFee.DoesNotExist:
            raise NotFound("SectionFee does not exist with this id")

    def get(self, request, id):
        fee = self.get_object(id)
        serializer = SectionFeeSerializer(fee)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def put(self, request, id):
        fee = self.get_object(id)

        allowed_fields = [
            "active",
            "amount",
        ]

        # Update the model fields
        update_model_fields_core(
            fee, request.data, allowed_fields, request.user
        )
        
        # Invalidate sections cache to refresh tuition_fees
        self._invalidate_cache(request, fee.section)
        
        # Serialize and return the updated fee
        serializer = SectionFeeSerializer(fee)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def delete(self, request, id):
        fee = self.get_object(id)
        section = fee.section  # Get section before deletion
        fee.delete()
        
        # Invalidate sections cache to refresh tuition_fees
        self._invalidate_cache(request, section)
        
        return Response(status=status.HTTP_204_NO_CONTENT)
    
    def _invalidate_cache(self, request, section: Section = None):
        """Invalidate section caches after fee modifications"""
        # DataCache.invalidate_sections expects request object, not school_id string
        DataCache.invalidate_sections(request)
        logger.debug("Invalidated section cache")
