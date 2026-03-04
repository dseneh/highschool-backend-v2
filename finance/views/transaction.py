from datetime import datetime, timezone
from uuid import uuid4

from django.db import transaction
from django.db.models import Q
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from academics.models import AcademicYear
from common.filter import get_transaction_queryparams
from common.utils import create_model_data, get_object_by_uuid_or_fields, update_model_fields
from finance.access_policies import TransactionAccessPolicy
from finance.models import BankAccount, PaymentMethod, Transaction, TransactionType
from finance.serializers import TransactionDetailSerializer, TransactionSerializer
from finance.validators import validate_transaction_data
from students.models import Student


class TransactionPageNumberPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class TransactionViewSet(viewsets.ModelViewSet):
    """
    ModelViewSet for finance transactions.

    Key endpoints (router paths can be adjusted in urls.py):
      - list/create:        /transactions/
      - retrieve/update:    /transactions/<pk>/
      - status change:      /transactions/<pk>/status/
      - student history:    /transactions/student/<student_id>/
      - account transfer:   /transactions/account-transfer/
      - delete by reference /transactions/by-reference/<reference_id>/
      - bulk create:        /transactions/bulk/<transaction_type_id>/
    """

    permission_classes = [TransactionAccessPolicy]
    pagination_class = TransactionPageNumberPagination
    serializer_class = TransactionDetailSerializer

    def get_queryset(self):
        qs = Transaction.objects.select_related(
            "student",
            "academic_year",
            "account",
            "type",
            "payment_method",
        )

        ordering = self.request.query_params.get("ordering", "-updated_at")
        return qs.order_by(ordering)

    def get_serializer_class(self):
        if self.action in ["list", "student_transactions"]:
            return TransactionSerializer
        return TransactionDetailSerializer

    def list(self, request, *args, **kwargs):
        transactions = self.get_queryset()

        query = get_transaction_queryparams(request.query_params.copy())
        if query:
            transactions = transactions.filter(query)

        page = self.paginate_queryset(transactions)
        serializer = self.get_serializer(page or transactions, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def create(self, request, *args, **kwargs):
        """Create a new transaction"""
        validated_data, error = validate_transaction_data(
            request.data, is_update=False
        )
        if error:
            return error

        student = validated_data.get("student")
        transaction_type = validated_data["type"]
        account = validated_data["account"]
        date = validated_data.get("date", datetime.now(timezone.utc).date())

        academic_year = AcademicYear.objects.filter(
            (Q(start_date__lte=date) & Q(end_date__gte=date)) | Q(current=True)
        ).first()

        trans_id = uuid4().hex[:10]

        data = {
            "student": validated_data.get("student"),
            "type": transaction_type,
            "account": account,
            "payment_method": validated_data["payment_method"],
            "amount": validated_data["amount"],
            "academic_year": academic_year,
            "status": request.data.get("status", "pending"),
            "transaction_id": trans_id,
            "reference": request.data.get("reference"),
            "notes": request.data.get("notes"),
            "date": date,
            "updated_by": request.user,
            "created_by": request.user,
        }
        description = f"{transaction_type.name} transaction"
        if student:
            description += f" for {student.get_full_name()}"
        data["description"] = description

        serializer = create_model_data(
            request, data, Transaction, TransactionDetailSerializer
        )
        return serializer

    def _update_transaction(self, request, transaction_obj, partial=False):
        validated_data, error = validate_transaction_data(
            request.data, is_update=True
        )
        if error:
            return error

        mutable_data = request.data.copy()
        for field, value in validated_data.items():
            if field in mutable_data:
                mutable_data[field] = value

        allowed_fields = [
            "amount",
            "reference",
            "description",
            "account",
            "payment_method",
            "type",
            "notes",
            "date",
            "status",
        ]

        date = mutable_data.get("date", transaction_obj.date)
        if date != transaction_obj.date:
            academic_year = AcademicYear.objects.filter(
                Q(start_date__lte=date) & Q(end_date__gte=date)
            ).first()
            mutable_data["academic_year"] = academic_year

        # Set status to pending for updates
        mutable_data["status"] = "pending"

        # Replace request.data with our mutated copy for downstream helpers
        request._full_data = mutable_data  # type: ignore[attr-defined]

        return update_model_fields(
            request, transaction_obj, allowed_fields, TransactionDetailSerializer
        )

    def update(self, request, *args, **kwargs):
        transaction_obj = self.get_object()
        return self._update_transaction(request, transaction_obj, partial=False)

    def partial_update(self, request, *args, **kwargs):
        transaction_obj = self.get_object()
        return self._update_transaction(request, transaction_obj, partial=True)

    def destroy(self, request, *args, **kwargs):
        transaction_obj = self.get_object()
        if transaction_obj.status == "approved":
            return Response(
                {"detail": "Cannot delete approved transactions"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        transaction_obj.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    def _set_status_action(self, request, transaction_obj, new_status):
        """Shared status update logic used by dedicated actions."""
        notes = request.data.get("notes")

        valid_statuses = ["pending", "approved", "rejected", "canceled"]
        if new_status not in valid_statuses:
            return Response(
                {
                    "detail": f"Invalid status. Must be one of: {', '.join(valid_statuses)}"
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        current_status = transaction_obj.status

        if current_status in ["rejected", "canceled"] and new_status == "approved":
            return Response(
                {"detail": f"Cannot approve a {current_status} transaction"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if transaction_obj.student and new_status == "approved":
            student_balance = transaction_obj.student.balance_due
            if transaction_obj.amount > student_balance:
                return Response(
                    {
                        "detail": (
                            f"Transaction amount exceeds student balance due of "
                            f"{student_balance:,.2f}. "
                            "Please adjust the transaction amount or contact the finance department."
                        )
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        update_data = {"status": new_status}
        if notes:
            update_data["notes"] = notes

        request._full_data = update_data  # type: ignore[attr-defined]

        allowed_fields = ["status", "notes", "updated_by"]

        return update_model_fields(
            request, transaction_obj, allowed_fields, TransactionDetailSerializer
        )

    @action(detail=True, methods=["put"], url_path="status")
    def set_status(self, request, pk=None, *args, **kwargs):
        transaction_obj = self.get_object()
        new_status = request.data.get("status")
        if not new_status:
            return Response(
                {"detail": "Status is required"}, status=status.HTTP_400_BAD_REQUEST
            )
        return self._set_status_action(request, transaction_obj, new_status)

    @action(detail=True, methods=["put"], url_path="approve")
    def approve(self, request, pk=None, *args, **kwargs):
        transaction_obj = self.get_object()
        return self._set_status_action(request, transaction_obj, "approved")

    @action(detail=True, methods=["put"], url_path="cancel")
    def cancel(self, request, pk=None, *args, **kwargs):
        transaction_obj = self.get_object()
        return self._set_status_action(request, transaction_obj, "canceled")

    # @action(detail=True, methods=["delete"], url_path="delete")
    # def delete_action(self, request, pk=None, *args, **kwargs):
    #     """Explicit delete action to allow separate permission control."""
    #     return self.destroy(request, pk, *args, **kwargs)

    @action(detail=False, methods=["get"], url_path=r"students/(?P<student_id>[^/.]+)")
    def student_transactions(self, request, student_id=None, *args, **kwargs):
        academic_year_id = request.query_params.get("academic_year")

        year_filter = Q(academic_year__id=academic_year_id) | Q(
            academic_year__name_iexact=academic_year_id
        )
        if not academic_year_id:
            year_filter = Q(academic_year__current=True)

        student = get_object_by_uuid_or_fields(
                    Student, 
                    student_id,
                    fields=['id_number', 'prev_id_number']
                )

        transactions = student.transactions.filter(year_filter).order_by("-updated_at")

        status_filter = request.query_params.get("status")
        if status_filter:
            transactions = transactions.filter(status=status_filter)

        transaction_type_filter = request.query_params.get("transaction_type")
        if transaction_type_filter:
            transactions = transactions.filter(type__name=transaction_type_filter)

        serializer = TransactionSerializer(transactions, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["post"], url_path="account-transfer")
    def account_transfer(self, request, *args, **kwargs):
        """Create an account-to-account transfer"""
        req_data = request.data

        required_fields = ["from_account", "to_account", "amount", "date"]
        validated_data, error = validate_transaction_data(
            req_data, is_update=False, required_fields=required_fields
        )
        if error:
            return error

        payment_method = PaymentMethod.objects.filter(name__iexact="system").first()

        if not payment_method:
            return Response(
                {"detail": "System payment method not found. Please create one first."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from_account = validated_data["from_account"]
        to_account = validated_data["to_account"]

        transaction_type_out = TransactionType.objects.filter(
            type_code__iexact="TRANSFER_OUT"
        ).first()
        transaction_type_in = TransactionType.objects.filter(
            type_code__iexact="TRANSFER_IN"
        ).first()

        if not transaction_type_out or not transaction_type_in:
            return Response(
                {"detail": "Transfer transaction types not found. Please create TRANSFER_OUT and TRANSFER_IN transaction types."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        amount = validated_data["amount"]
        date = validated_data["date"]

        academic_year = AcademicYear.objects.filter(
            Q(start_date__lte=date) & Q(end_date__gte=date)
        ).first()

        d = datetime.now(timezone.utc)

        ref = datetime.now().strftime("%Y%m%d%H%M%S")
        generated_ref = f"A2A_{ref}_{uuid4().hex[:2]}".upper()

        if amount > from_account.balance:
            return Response(
                {"detail": "Insufficient balance. Cannot transfer more than balance."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        data = {
            "payment_method": payment_method,
            "academic_year": academic_year,
            "status": "approved",
            "reference": generated_ref,
            "notes": req_data.get("notes"),
            "date": req_data.get("date", d.date()),
            "updated_by": request.user,
            "created_by": request.user,
        }

        transfer_out = data.copy()
        transfer_out["account"] = from_account
        transfer_out["type"] = transaction_type_out
        transfer_out["amount"] = -abs(amount)
        transfer_out["transaction_id"] = uuid4().hex[:10]
        transfer_out["description"] = f"Transfer to {to_account.name}"

        transfer_in = data.copy()
        transfer_in["account"] = to_account
        transfer_in["type"] = transaction_type_in
        transfer_in["amount"] = amount
        transfer_in["transaction_id"] = uuid4().hex[:10]
        transfer_in["description"] = f"Transfer from {from_account.name}"

        with transaction.atomic():
            try:
                d1 = from_account.transactions.create(**transfer_out)
                serializer1 = TransactionDetailSerializer(d1)

                d2 = to_account.transactions.create(**transfer_in)
                serializer2 = TransactionDetailSerializer(d2)

                combined_data = [serializer1.data, serializer2.data]

                return Response(combined_data, status=status.HTTP_201_CREATED)
            except Exception as e:
                return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(
        detail=False,
        methods=["delete"],
        url_path=r"by-reference/(?P<reference_id>[^/.]+)",
    )
    def delete_by_reference(self, request, reference_id=None, *args, **kwargs):
        transaction_obj = Transaction.objects.filter(reference=reference_id)
        transaction_obj.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(
        detail=False, methods=["post"], url_path=r"bulk/(?P<transaction_type_id>[^/.]+)"
    )
    def bulk_create(self, request, transaction_type_id=None, *args, **kwargs):
        """
        Create multiple transactions in one request.
        """
        req_data = request.data

        if isinstance(req_data, list):
            transactions_payload = req_data
            override_by_reference = False
        else:
            transactions_payload = req_data.get("transactions")
            override_by_reference = (
                req_data.get("override_existing", False)
                or request.query_params.get("override_existing", "false").lower()
                == "true"
            )

        if not transactions_payload or not isinstance(transactions_payload, list):
            return Response(
                {
                    "success": False,
                    "error": {
                        "detail": "Expected a list of transactions under 'transactions'.",
                    },
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        def get_student_info(student_id):
            """Get student information (id, id_number, full_name) if available"""
            if not student_id:
                return None

            student_info = None
            student_obj = None

            try:
                student_obj = Student.objects.filter(
                    Q(id=student_id) | Q(id_number=student_id)
                ).first()
            except Exception:
                return None

            if student_obj:
                try:
                    student_info = {
                        "id": str(student_obj.id),
                        "id_number": student_obj.id_number,
                        "full_name": student_obj.get_full_name(),
                    }
                except Exception:
                    pass

            return student_info

        seen_keys = set()
        for idx, item in enumerate(transactions_payload):
            if not isinstance(item, dict):
                student_info = (
                    get_student_info(student_id=item.get("student"))
                    if hasattr(item, "get")
                    else None
                )
                transaction_data = item.copy() if isinstance(item, dict) else item
                if student_info and isinstance(transaction_data, dict):
                    transaction_data["student"] = student_info

                error_response = {
                    "success": False,
                    "error": {
                        "row_index": idx,
                        "detail": f"Item at index {idx} must be an object.",
                        "transaction_data": transaction_data,
                    },
                }
                if student_info:
                    error_response["error"]["student"] = student_info
                return Response(error_response, status=status.HTTP_400_BAD_REQUEST)

            if override_by_reference and item.get("reference"):
                continue

            key = (
                str(item.get("student") or ""),
                str(item.get("amount") or ""),
                str(item.get("date") or ""),
                str(item.get("reference") or ""),
            )
            if key in seen_keys:
                student_info = get_student_info(student_id=item.get("student"))
                transaction_data = item.copy()
                if student_info:
                    transaction_data["student"] = student_info

                error_response = {
                    "success": False,
                    "error": {
                        "row_index": idx,
                        "detail": (
                            "Duplicate transaction detected in bulk payload. "
                            "Each student/amount/date/reference combination "
                            "must be unique."
                        ),
                        "transaction_data": transaction_data,
                    },
                }
                if student_info:
                    error_response["error"]["student"] = student_info
                return Response(error_response, status=status.HTTP_400_BAD_REQUEST)
            seen_keys.add(key)

        created_transactions = []
        deleted_count = 0
        processed_references = set()
        errors = []

        type_qs = TransactionType.objects.filter(
            Q(id=transaction_type_id)
            | Q(type_code__iexact=transaction_type_id)
            | Q(name__iexact=transaction_type_id)
        )

        count = type_qs.count()
        if count == 0:
            return Response(
                {
                    "success": False,
                    "error": {
                        "detail": "Invalid transaction type for bulk transactions.",
                    },
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        if count > 1:
            return Response(
                {
                    "success": False,
                    "error": {
                        "detail": (
                            "Multiple transaction types match this identifier. "
                            "Please use a unique transaction type ID."
                        ),
                    },
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        transaction_type = type_qs.first()
        fee_payment_type_codes = {"TUITION"}
        require_student = transaction_type.type_code.upper() in fee_payment_type_codes

        def build_error_info(error_detail, student_id=None, item_data=None):
            transaction_data = (
                item_data.copy() if isinstance(item_data, dict) else item_data
            )

            student_info = None
            student_id_to_lookup = (
                student_id
                or (item_data.get("student") if isinstance(item_data, dict) else None)
                or (
                    transaction_data.get("student")
                    if isinstance(transaction_data, dict)
                    else None
                )
            )

            if student_id_to_lookup:
                try:
                    student_info = get_student_info(student_id=student_id_to_lookup)
                except Exception:
                    student_info = None

            if (
                student_info
                and isinstance(transaction_data, dict)
                and "student" in transaction_data
            ):
                transaction_data["student"] = student_info

            error_info = {
                "row_index": idx,
                "detail": error_detail,
                "transaction_data": transaction_data,
            }

            if student_info:
                error_info["student"] = student_info

            return error_info

        for idx, item in enumerate(transactions_payload):
            if not isinstance(item, dict):
                errors.append(
                    build_error_info(
                        "Each transaction must be an object.", item_data=item
                    )
                )
                continue

            item_data = item.copy()
            item_data["type"] = transaction_type.id

            try:
                with transaction.atomic():
                    if require_student and not item_data.get("student"):
                        raise ValueError(
                            "Student is required for fee/tuition payment transactions in bulk create."
                        )

                    validated_data, error = validate_transaction_data(
                        item_data, is_update=False
                    )
                    if error:
                        error_detail = "Validation failed"
                        if isinstance(error, Response):
                            try:
                                error_data = error.data
                                if isinstance(error_data, dict):
                                    if "detail" in error_data:
                                        detail = error_data["detail"]
                                        error_detail = (
                                            detail
                                            if isinstance(detail, str)
                                            else str(detail)
                                        )
                                    elif "errors" in error_data:
                                        error_detail = str(error_data["errors"])
                            except Exception:
                                error_detail = "Validation failed - unable to extract error details"
                        elif isinstance(error, dict):
                            error_detail = error.get("detail", str(error))
                        else:
                            error_detail = str(error)

                        raise ValueError(error_detail)

                    student = validated_data.get("student")
                    transaction_type_obj = validated_data["type"]
                    account = validated_data["account"]
                    payment_method = validated_data["payment_method"]

                    date = validated_data.get("date", datetime.now(timezone.utc).date())

                    academic_year = AcademicYear.objects.filter(
                        (Q(start_date__lte=date) & Q(end_date__gte=date))
                        | Q(current=True)
                    ).first()

                    trans_id = uuid4().hex[:10]

                    data = {
                        "student": student,
                        "type": transaction_type_obj,
                        "account": account,
                        "payment_method": payment_method,
                        "amount": validated_data["amount"],
                        "academic_year": academic_year,
                        "status": item.get("status", "pending"),
                        "transaction_id": trans_id,
                        "reference": item.get("reference"),
                        "notes": item.get("notes"),
                        "date": date,
                        "updated_by": request.user,
                        "created_by": request.user,
                    }

                    description = f"{transaction_type_obj.name} transaction"
                    if student:
                        description += f" for {student.get_full_name()}"
                    data["description"] = description

                    reference = item.get("reference")
                    if override_by_reference and reference:
                        if reference not in processed_references:
                            existing_count = Transaction.objects.filter(
                                reference=reference
                            ).count()

                            if existing_count > 0:
                                deleted = Transaction.objects.filter(
                                    reference=reference
                                ).delete()
                                deleted_count += deleted[0]
                                processed_references.add(reference)

                    obj = Transaction.objects.create(**data)
                    created_transactions.append(obj)

            except Exception as e:
                error_detail = str(e)
                errors.append(
                    build_error_info(
                        error_detail,
                        student_id=(
                            item_data.get("student") if isinstance(item, dict) else None
                        ),
                        item_data=item_data if isinstance(item, dict) else None,
                    )
                )
                continue

        serializer = TransactionDetailSerializer(created_transactions, many=True)

        has_errors = len(errors) > 0
        has_successes = len(created_transactions) > 0

        response_data = {
            "success": not has_errors or has_successes,
            "data": {
                "transactions": serializer.data,
            },
            "meta": {
                "created": len(created_transactions),
                "deleted": deleted_count,
                "total_processed": len(transactions_payload),
                "succeeded": len(created_transactions),
                "failed": len(errors),
            },
        }

        if errors:
            response_data["errors"] = errors

        if has_errors and not has_successes:
            status_code = status.HTTP_400_BAD_REQUEST
        elif has_errors and has_successes:
            status_code = status.HTTP_200_OK
        else:
            status_code = status.HTTP_201_CREATED

        return Response(response_data, status=status_code)

    @action(detail=False, methods=["post"], url_path="bulk-approve")
    def bulk_approve(self, request):
        """
        Bulk approve multiple pending transactions.
        
        Payload: {"transaction_ids": ["id1", "id2", ...]}
        """
        transaction_ids = request.data.get("transaction_ids", [])
        
        if not transaction_ids:
            return Response(
                {"detail": "transaction_ids is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        transactions = Transaction.objects.filter(
            id__in=transaction_ids,
            status="pending"
        )
        
        if not transactions.exists():
            return Response(
                {"detail": "No pending transactions found with the provided IDs"},
                status=status.HTTP_404_NOT_FOUND
            )
        
        updated_count = transactions.update(
            status="approved",
            updated_by=request.user,
            updated_at=datetime.now(timezone.utc)
        )
        
        return Response(
            {
                "success": True,
                "updated": updated_count,
                "message": f"{updated_count} transaction(s) approved successfully"
            },
            status=status.HTTP_200_OK
        )
    
    @action(detail=False, methods=["post"], url_path="bulk-cancel")
    def bulk_cancel(self, request):
        """
        Bulk cancel multiple approved transactions (non-transfer types).
        
        Payload: {"transaction_ids": ["id1", "id2", ...]}
        """
        transaction_ids = request.data.get("transaction_ids", [])
        
        if not transaction_ids:
            return Response(
                {"detail": "transaction_ids is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        transactions = Transaction.objects.filter(
            id__in=transaction_ids,
            status="approved"
        ).exclude(
            type__type="transfer"
        )
        
        if not transactions.exists():
            return Response(
                {"detail": "No approved non-transfer transactions found with the provided IDs"},
                status=status.HTTP_404_NOT_FOUND
            )
        
        updated_count = transactions.update(
            status="canceled",
            updated_at=datetime.now(timezone.utc)
        )
        
        return Response(
            {
                "success": True,
                "updated": updated_count,
                "message": f"{updated_count} transaction(s) canceled successfully"
            },
            status=status.HTTP_200_OK
        )
    
    @action(detail=False, methods=["post"], url_path="bulk-delete")
    def bulk_delete(self, request):
        """
        Bulk delete multiple pending/canceled transactions (non-transfer types).
        
        Payload: {"transaction_ids": ["id1", "id2", ...]}
        """
        transaction_ids = request.data.get("transaction_ids", [])
        
        if not transaction_ids:
            return Response(
                {"detail": "transaction_ids is required"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        transactions = Transaction.objects.filter(
            id__in=transaction_ids,
            status__in=["pending", "canceled"]
        ).exclude(
            type__type="transfer"
        )
        
        if not transactions.exists():
            return Response(
                {"detail": "No pending/canceled non-transfer transactions found with the provided IDs"},
                status=status.HTTP_404_NOT_FOUND
            )
        
        count = transactions.count()
        transactions.delete()
        
        return Response(
            {
                "success": True,
                "deleted": count,
                "message": f"{count} transaction(s) deleted successfully"
            },
            status=status.HTTP_200_OK
        )

