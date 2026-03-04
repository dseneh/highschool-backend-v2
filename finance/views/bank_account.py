import json
from datetime import datetime

from django.db import transaction
from django.db.models import Q
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView
from ..access_policies import FinanceAccessPolicy

from common.secure_response import secure_response
from common.utils import (
    create_model_data,
    encrypt_data,
    update_model_fields,
    validate_required_fields,
)

from ..models import BankAccount
from ..serializers import BankAccountDetailSerializer, BankAccountSerializer

class BankAccountPageNumberPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100

class BankAccountListView(APIView):
    permission_classes = [FinanceAccessPolicy]
    """
    View to list all bank accounts or create a new bank account.
    Supports filtering by tenant, name, etc.
    """

    def get(self, request):
        
        # Check analysis parameters
        include_analysis_param = request.query_params.get('include_analysis', 'false').lower()
        include_analysis = include_analysis_param in ['true', '1', 'yes', 'on']
        
        include_basic_analysis_param = request.query_params.get('include_basic_analysis', 'false').lower()
        include_basic_analysis = include_basic_analysis_param in ['true', '1', 'yes', 'on']
        
        # Full analysis takes precedence over basic analysis
        if include_analysis:
            include_basic_analysis = False
        
        bank_accounts_queryset = BankAccount.objects.all()
        
        if include_analysis:
            # If full analysis is requested, prefetch all related data
            from django.db.models import Prefetch
            bank_accounts_queryset = bank_accounts_queryset.prefetch_related(
                Prefetch(
                    'transactions',
                    queryset=self.get_optimized_transaction_queryset()
                )
            )
        elif include_basic_analysis:
            # If basic analysis is requested, prefetch minimal transaction data
            from django.db.models import Prefetch
            bank_accounts_queryset = bank_accounts_queryset.prefetch_related(
                Prefetch(
                    'transactions',
                    queryset=self.get_basic_transaction_queryset()
                )
            )
        else:
            # If no analysis needed, use minimal fields for performance
            bank_accounts_queryset = bank_accounts_queryset.only(
                "id", "number", "name", "description", "active"
            )
        
        # Apply pagination for large datasets
        paginator = BankAccountPageNumberPagination()
        paginated_accounts = paginator.paginate_queryset(bank_accounts_queryset, request)
        
        if paginated_accounts is not None:
            serializer = BankAccountSerializer(
                paginated_accounts, 
                many=True, 
                include_analysis=include_analysis,
                include_basic_analysis=include_basic_analysis
            )
            response_data = paginator.get_paginated_response(serializer.data).data
        else:
            # Fallback for non-paginated requests
            bank_accounts = list(bank_accounts_queryset[:100])  # Limit to 100 for safety
            serializer = BankAccountSerializer(
                bank_accounts, 
                many=True, 
                include_analysis=include_analysis,
                include_basic_analysis=include_basic_analysis
            )
            response_data = serializer.data
        
        # Add metadata about the request
        analysis_type = "full" if include_analysis else ("basic" if include_basic_analysis else "none")
        if analysis_type != "none" and isinstance(response_data, dict):
            response_data["meta"] = {
                "analysis_type": analysis_type,
                "include_analysis": include_analysis,
                "include_basic_analysis": include_basic_analysis,
                "analysis_timestamp": datetime.now().isoformat()
            }
        elif analysis_type != "none":
            # For non-paginated response
            response_data = {
                "results": response_data,
                "meta": {
                    "analysis_type": analysis_type,
                    "include_analysis": include_analysis,
                    "include_basic_analysis": include_basic_analysis,
                    "count": len(response_data),
                    "analysis_timestamp": datetime.now().isoformat()
                }
            }

        return secure_response(response_data)
    
    def get_basic_transaction_queryset(self):
        """Get minimal transaction queryset for basic analysis."""
        from finance.models import Transaction
        return Transaction.objects.select_related('type').only(
            'id', 'amount', 'status', 'type__type'
        )
    
    def get_optimized_transaction_queryset(self):
        """Get optimized transaction queryset for analysis."""
        from finance.models import Transaction
        return Transaction.objects.select_related(
            'type', 'payment_method'
        ).only(
            'id', 'amount', 'status', 'date', 'type__type', 'payment_method__name'
        )

    def post(self, request):
        """Create a new bank account"""
        req_data = request.data
        number = req_data.get("number")

        # Validate required fields
        required_fields = ["name"]
        validate_required_fields(request, required_fields)

        # Generate a unique bank account number if not provided
        number = "0001"
        # 🔥 MEMORY FIX: Use order_by and last() more efficiently
        last_account = BankAccount.objects.order_by("number").last()

        if last_account:
            last_number = int(last_account.number)
            number = str(last_number + 1).zfill(4)

        if BankAccount.objects.filter(number=number).exists():
            return Response(
                {"detail": "Bank account with this number already exists"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if BankAccount.objects.filter(name__iexact=req_data["name"]).exists():
            return Response(
                {"detail": "Bank account with this name already exists"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Create bank account data
        data = {
            "number": number,
            "name": req_data["name"],
            "bank_number": req_data.get("bank_number", ""),
            "description": req_data.get("description", ""),
        }

        bank_account = create_model_data(
            request, data, BankAccount, BankAccountDetailSerializer
        )
        return bank_account

class BankAccountDetailView(APIView):
    permission_classes = [FinanceAccessPolicy]
    """
    View to retrieve, update or delete a specific bank account.
    """

    def get_object(self, pk, include_analysis=False):
        """Helper method to get a bank account object by primary key."""
        try:
            queryset = BankAccount.objects.all()
            
            if include_analysis:
                # Prefetch related data for analysis
                queryset = queryset.prefetch_related(
                    'transactions__type',
                    'transactions__payment_method',
                    'transactions__student',
                    'transactions__academic_year'
                )
            
            return queryset.get(pk=pk)
        except BankAccount.DoesNotExist:
            raise NotFound("Bank account not found")

    def get(self, request, id):
        """Get a specific bank account"""
        include_analysis_param = request.query_params.get('include_analysis', 'false').lower()
        include_analysis = include_analysis_param in ['true', '1', 'yes', 'on']
        
        include_basic_analysis_param = request.query_params.get('include_basic_analysis', 'false').lower()
        include_basic_analysis = include_basic_analysis_param in ['true', '1', 'yes', 'on']
        
        # Full analysis takes precedence over basic analysis
        if include_analysis:
            include_basic_analysis = False
        
        bank_account = self.get_object(id, include_analysis=(include_analysis or include_basic_analysis))
        
        serializer = BankAccountDetailSerializer(
            bank_account, 
            include_analysis=include_analysis,
            include_basic_analysis=include_basic_analysis
        )
        
        response_data = serializer.data
        
        # Add metadata about the request
        analysis_type = "full" if include_analysis else ("basic" if include_basic_analysis else "none")
        if analysis_type != "none":
            response_data["meta"] = {
                "analysis_type": analysis_type,
                "include_analysis": include_analysis,
                "include_basic_analysis": include_basic_analysis,
                "analysis_generated_at": datetime.now().isoformat()
            }
        
        return Response(response_data)

    def put(self, request, id):
        """Update a specific bank account"""
        bank_account = self.get_object(id, include_analysis=False)

        update_fields = ["name", "description", "bank_number"]

        serializer = update_model_fields(
            request, bank_account, update_fields, BankAccountDetailSerializer
        )

        return serializer

    def delete(self, request, id):
        """Delete a specific bank account"""
        bank_account = self.get_object(id, include_analysis=False)

        if bank_account.transactions.exists():
            # disable bank account instead of deleting
            bank_account.active = False
            bank_account.save()
            return Response(
                {
                    "detail": "Cannot delete bank account with associated transactions, please delete those transactions first."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        bank_account.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
