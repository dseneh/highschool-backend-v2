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

from ..models import TransactionType
from ..serializers import TransactionTypeSerializer

class TransactionTypePageNumberPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100

class TransactionTypeListView(APIView):
    permission_classes = [FinanceAccessPolicy]
    """
    View to list all transaction types or create a new transaction type.
    Tenant context is provided by x-tenant header via middleware.
    """

    def get(self, request):
        # Transaction types are tenant-scoped via middleware
        include_hidden = request.query_params.get('include_hidden', 'false').lower() == 'true'
        
        queryset = TransactionType.objects.all()
        if not include_hidden:
            queryset = queryset.filter(is_hidden=False)
        
        transaction_types = queryset.select_related().only(
            "id", "name", "description", "type", "type_code", "is_hidden", "is_editable", "active"
        )
        
        # Text search across name and description
        search = request.query_params.get("search")
        if search:
            queryset = transaction_types.filter(
                Q(name__icontains=search) | Q(description__icontains=search)
            )
        
        serializer = TransactionTypeSerializer(transaction_types, many=True)
        return Response(serializer.data)

    def post(self, request):
        """Create a new transaction type"""
        req_data = request.data
        typ = req_data.get("type")

        # Validate required fields
        required_fields = ["name", "type"]
        validate_required_fields(request, required_fields)

        if TransactionType.objects.filter(name__iexact=req_data["name"]).exists():
            return Response(
                {"detail": "Transaction type with this name already exists"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if typ not in ["expense", "income"]:
            return Response(
                {"detail": "Invalid transaction type. Must be 'expense' or 'income'"},
                status=400,
            )

        # Generate unique type_code like "EXP-001", "INC-001" etc.
        counter = TransactionType.objects.count() + 1
        type_code = f"{typ.upper()}_{counter:03d}"

        # check if type_code already exists, if so, create a new one
        max_attempts = 1000  # Safety limit to prevent infinite loops
        attempts = 0
        while TransactionType.objects.filter(type_code=type_code).exists() and attempts < max_attempts:
            counter += 1
            type_code = f"{typ.upper()}_{counter:03d}"
            attempts += 1
        
        if attempts >= max_attempts:
            return Response(
                {"detail": "Unable to generate unique transaction type code after maximum attempts"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        data = {
            "name": req_data["name"],
            "description": req_data.get("description", ""),
            "type": typ,
            "type_code": type_code,
            "is_hidden": req_data.get("is_hidden", False),
            "is_editable": req_data.get("is_editable", True),
        }

        transaction_type = create_model_data(
            request, data, TransactionType.objects, TransactionTypeSerializer
        )

        return transaction_type

class TransactionTypeDetailView(APIView):
    permission_classes = [FinanceAccessPolicy]
    """
    View to retrieve, update or delete a specific transaction type.
    """

    def get_object(self, pk):
        f = Q(id=pk) | Q(type_code__iexact=pk)
        try:
            return TransactionType.objects.get(pk=pk)
        except TransactionType.DoesNotExist:
            raise NotFound("Transaction type does not exist with this id")

    def get(self, request, pk):
        """Get a specific transaction type"""
        transaction_type = self.get_object(pk)
        serializer = TransactionTypeSerializer(transaction_type)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def put(self, request, pk):
        """Update a specific transaction type"""
        transaction_type = self.get_object(pk)
        req_data = request.data

        # Handle name update (check for uniqueness)
        if "name" in req_data and req_data["name"] != transaction_type.name:
            if TransactionType.objects.filter(
                name=req_data["name"]
            ).exists():
                return Response(
                    {"detail": "Transaction type with this name already exists"},
                    status=400,
                )
        typ = req_data.get("type")
        if typ and typ != transaction_type.type:
            counter = TransactionType.objects.count() + 1
            type_code = f"{typ.upper()}_{counter:03d}"
            
            # check if type_code already exists, if so, create a new one
            max_attempts = 1000  # Safety limit to prevent infinite loops
            attempts = 0
            while TransactionType.objects.filter(type_code=type_code).exists() and attempts < max_attempts:
                counter += 1
                type_code = f"{typ.upper()}_{counter:03d}"
                attempts += 1
            
            if attempts >= max_attempts:
                return Response(
                    {"detail": "Unable to generate unique transaction type code after maximum attempts"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

            request.data["type_code"] = type_code

        update_fields = [
            "name",
            "description",
            "type",
            "type_code",
            "is_hidden",
            "is_editable",
        ]
        serializer = update_model_fields(
            request, transaction_type, update_fields, TransactionTypeSerializer
        )

        return serializer

    def delete(self, request, pk):
        """Delete a specific transaction type"""

        transaction_type = self.get_object(pk)

        # Check if transaction type has associated transactions
        if transaction_type.transactions.exists():
            transaction_type.active = False
            transaction_type.save()
            return Response(
                {
                    "detail": "Cannot delete transaction type with associated transactions"
                },
                status=400,
            )

        transaction_type.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
