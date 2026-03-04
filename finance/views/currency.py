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

from ..models import Currency
from ..serializers import CurrencySerializer


class CurrencyListView(APIView):
    permission_classes = [FinanceAccessPolicy]
    """
    View to list all currencies or create a new currency.
    Tenant context is provided by x-tenant header via middleware.
    """

    def get(self, request):
        # Currencies are tenant-scoped via middleware
        # Query all currencies in current tenant schema
        currencies = Currency.objects.select_related().only(
            "id", "name", "symbol", "code"
        )
        serializer = CurrencySerializer(currencies, many=True)
        return Response(serializer.data)

    def post(self, request):
        """Create a new currency"""
        req_data = request.data

        required_fields = ["name", "symbol", "code"]
        validate_required_fields(req_data, required_fields)

        if Currency.objects.filter(name__iexact=req_data["name"]).exists():
            return Response(
                {"detail": "Currency with this name already exists"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        data = {
            "name": req_data["name"],
            "symbol": req_data["symbol"],
            "code": req_data["code"],
        }

        currency = create_model_data(
            request, data, Currency.objects, CurrencySerializer
        )

        return currency


class CurrencyDetailView(APIView):
    permission_classes = [FinanceAccessPolicy]
    """
    View to retrieve, update or delete a specific currency.
    """

    def get_object(self, pk):
        try:
            f = Q(id=pk) | Q(code=pk)
            return Currency.objects.get(f)
        except Currency.DoesNotExist:
            raise NotFound("Currency does not exist with this id")

    def get(self, request, pk):
        """Get a specific currency"""
        currency = self.get_object(pk)
        serializer = CurrencySerializer(currency)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def put(self, request, pk):
        """Update a specific currency"""
        currency = self.get_object(pk)
        req_data = request.data

        # Handle name update (check for uniqueness)
        if "name" in req_data and req_data["name"] != currency.name:
            if Currency.objects.filter(name=req_data["name"]).exists():
                return Response(
                    {"detail": "Currency with this name already exists"},
                    status=400,
                )

        update_fields = ["name", "symbol", "code"]
        serializer = update_model_fields(
            request, currency, update_fields, CurrencySerializer
        )

        return serializer

    def delete(self, request, pk):
        """Delete a specific currency"""

        currency = self.get_object(pk)

        # Check if currency has associated transactions
        if currency.transactions.exists():
            currency.active = False
            currency.save()
            return Response(
                {"detail": "Cannot delete currency with associated transactions"},
                status=400,
            )

        currency.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
