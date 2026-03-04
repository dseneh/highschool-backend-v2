from django.db.models import Q
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.views import APIView
from ..access_policies import FinanceAccessPolicy

from common.utils import (
    create_model_data,
    update_model_fields,
    validate_required_fields,
)
from finance.models import PaymentMethod
from finance.serializers import PaymentMethodSerializer

class PaymentMethodListView(APIView):
    permission_classes = [FinanceAccessPolicy]
    """
    View to list all payment methods or create a new payment method.
    Tenant context is provided by x-tenant header via middleware.
    """

    def get(self, request):
        # Payment methods are tenant-scoped via middleware
        payment_methods = PaymentMethod.objects.select_related().only(
            "id", "name", "description", "active", "is_editable"
        )
        serializer = PaymentMethodSerializer(payment_methods, many=True)
        
        return Response(serializer.data)

    def post(self, request):
        """Create a new payment method"""
        req_data = request.data

        required_fields = ["name", "description"]
        validate_required_fields(request, required_fields)

        if PaymentMethod.objects.filter(name__iexact=req_data["name"]).exists():
            return Response(
                {"detail": "Payment method with this name already exists"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        data = {
            "name": req_data["name"],
            "description": req_data.get("description", ""),
        }

        payment_method = create_model_data(
            request, data, PaymentMethod.objects, PaymentMethodSerializer
        )

        return payment_method

class PaymentMethodDetailView(APIView):
    permission_classes = [FinanceAccessPolicy]
    """
    View to retrieve, update or delete a specific transaction type.
    """

    def get_object(self, pk):
        try:
            return PaymentMethod.objects.get(pk=pk)
        except PaymentMethod.DoesNotExist:
            raise NotFound("Transaction type does not exist with this id")

    def get(self, request, pk):
        """Get a specific transaction type"""
        payment_method = self.get_object(pk)
        serializer = PaymentMethodSerializer(payment_method)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def put(self, request, pk):
        """Update a specific payment method"""
        payment_method = self.get_object(pk)
        req_data = request.data

        # Handle name update (check for uniqueness)
        if "name" in req_data and req_data["name"] != payment_method.name:
            if PaymentMethod.objects.filter(name=req_data["name"]).exists():
                return Response(
                    {"detail": "Transaction type with this name already exists"},
                    status=400,
                )

        update_fields = ["name", "description", "active"]
        serializer = update_model_fields(
            request, payment_method, update_fields, PaymentMethodSerializer
        )

        return serializer

    def delete(self, request, pk):
        """Delete a specific payment method"""

        payment_method = self.get_object(pk)

        if not payment_method.is_editable:
            return Response(
                {"detail": "Cannot delete payment method that is not editable"},
                status=400,
            )

        # Check if payment method has associated transactions
        if payment_method.transactions.exists():
            payment_method.active = False
            payment_method.save()
            return Response(
                {"detail": "Cannot delete payment method with associated transactions"},
                status=400,
            )

        payment_method.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
