"""
Reusable validation functions for transaction fields
"""
from datetime import date, datetime
from decimal import Decimal

from django.db.models import Q, Sum
from rest_framework import status
from rest_framework.response import Response

from academics.models import AcademicYear
from common.utils import get_object_by_uuid_or_fields
from finance.models import BankAccount, Currency, PaymentMethod, TransactionType
from students.models.student import Student


def get_student_net_remaining_balance(student, academic_year):
    """
    Remaining balance for validation:
    net bill - approved income transactions
    """
    if not student or not academic_year:
        return Decimal("0")

    enrollment = student.enrollments.filter(academic_year=academic_year).first()
    if not enrollment:
        return Decimal("0")

    gross_total_bills = enrollment.student_bills.aggregate(total=Sum("amount"))["total"] or Decimal("0")

    total_concession = Decimal("0")
    try:
        from students.models.billing import calculate_concessions_for_enrollment

        concession_data = calculate_concessions_for_enrollment(enrollment)
        total_concession = Decimal(str(concession_data.get("total_concession", 0)))
    except Exception:
        total_concession = Decimal("0")

    net_total_bills = gross_total_bills - total_concession
    if net_total_bills < 0:
        net_total_bills = Decimal("0")

    approved_income_paid = (
        student.transactions.filter(
            academic_year=academic_year,
            status="approved",
            type__type="income",
        ).aggregate(total=Sum("amount"))["total"]
        or Decimal("0")
    )

    remaining_balance = net_total_bills - approved_income_paid
    if remaining_balance < 0:
        remaining_balance = Decimal("0")

    return Decimal(str(remaining_balance))


def validate_amount(amount, student=None, transaction_type=None, academic_year=None):
    """
    Validate transaction amount
    """
    if not amount or amount <= 0:
        return Response(
            {"detail": "Amount is not valid. Must be greater than 0"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Additional validation for student balance if it's an income transaction
    if student and transaction_type and transaction_type.type == "income":
        remaining_balance = get_student_net_remaining_balance(student, academic_year)

        if remaining_balance <= 0:
            return Response(
                {"detail": "Student has no balance due. Cannot create transaction."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if Decimal(str(amount)) > remaining_balance:
            return Response(
                {
                    "detail": f"Transaction amount exceeds student balance due of {remaining_balance:,.2f}."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

    return None  # No error


def validate_student(student_id, required=False):
    """
    Validate and retrieve student
    """
    if not student_id:
        if required:
            return None, Response(
                {"detail": "Student is required"}, status=status.HTTP_400_BAD_REQUEST
            )
        return None, None

    student = get_object_by_uuid_or_fields(
        Student,
        student_id,
        ["id_number", "prev_id_number"],
    )

    if not student:
        return None, Response(
            {"detail": "Student does not exist with this id"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return student, None


def validate_transaction_type(type_id):
    """
    Validate and retrieve transaction type
    """
    if not type_id:
        return None, Response(
            {"detail": "Transaction type is required"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    transaction_type = get_object_by_uuid_or_fields(
        TransactionType,
        type_id,
        fields=['id', 'name', 'type_code']
    )
    if not transaction_type:
        return None, Response(
            {"detail": "Transaction type does not exist with this id"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return transaction_type, None


def validate_payment_method(payment_method_id):
    """
    Validate and retrieve payment method
    """
    if not payment_method_id:
        return None, Response({"detail": "Payment method is required"}, status=400)

    try:
        payment_method = PaymentMethod.objects.get(id=payment_method_id)
    except PaymentMethod.DoesNotExist:
        return None, Response(
            {"detail": "Payment method does not exist with this id"}, status=400
        )

    if not payment_method.active:
        return None, Response({"detail": "Payment method is disabled"}, status=400)

    return payment_method, None


def validate_currency(currency_id):
    """
    Validate and retrieve currency
    """
    currencies = Currency.objects.all()

    if len(currencies) == 1 or not currency_id:
        return currencies.first(), None

    try:
        currency = Currency.objects.get(
            Q(id=currency_id) | Q(name__iexact=currency_id) | Q(code__iexact=currency_id)
        )
    except Currency.DoesNotExist:
        return None, Response(
            {"detail": "Currency does not exist with this id"}, status=400
        )
    return currency, None


def validate_bank_account(account_id):
    """
    Validate and retrieve bank account
    """
    accounts = BankAccount.objects.all()

    if len(accounts) == 1 or not account_id:
        return accounts.first(), None

    try:
        account = BankAccount.objects.get(Q(id=account_id) | Q(number=account_id))
    except BankAccount.DoesNotExist:
        return None, Response(
            {"detail": "Bank account does not exist with this id"}, status=400
        )
    return account, None


def validate_pending_transactions_limit(student, limit=2, is_update=False):
    """
    Validate that student doesn't exceed pending transactions limit
    """
    if not student:
        return None

    if not is_update:
        pending_count = student.transactions.filter(status="pending").count()
        if pending_count >= limit:
            return Response(
                {
                    "detail": f"Cannot create more than {limit} pending transactions for a student. Please wait until pending transactions are approved or canceled."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

    return None  # No error


def validate_account_balance(account, amount, transaction_type):
    """
    Validate account has sufficient balance for expense transactions
    """
    if transaction_type.type == "expense" and hasattr(account, "balance"):
        if (
            float(account.balance) + float(amount) <= 0
        ):  # amount is negative for expenses
            return Response({"detail": "Insufficient funds in the account"}, status=400)

    return None  # No error


def validate_transaction_date(transaction_date):
    """
    Validate transaction date - should not be in the future
    """
    if not transaction_date:
        return None  # No error if date is not provided (will use default)

    # Convert string to date if needed
    if isinstance(transaction_date, str):
        try:
            transaction_date = datetime.strptime(transaction_date, "%Y-%m-%d").date()
        except ValueError:
            return Response(
                {"detail": "Invalid date format. Use YYYY-MM-DD format."},
                status=status.HTTP_400_BAD_REQUEST,
            )

    # Check if date is in the future
    today = date.today()
    if transaction_date > today:
        return Response(
            {"detail": "Transaction date cannot be in the future."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    return None  # No error


def validate_transaction_data(
    req_data, is_update=False, required_fields=None
):
    """
    Comprehensive validation for transaction data
    Returns: (validated_data_dict, error_response)
    """

    if not required_fields:
        required_fields = ["amount", "type", "payment_method", "account", "date"]

    # Validate required fields for create
    if not is_update:
        missing_fields = [field for field in required_fields if not req_data.get(field)]
        if missing_fields:
            return None, Response(
                {"detail": f"Missing required fields: {', '.join(missing_fields)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
    validated_data = {}

    # Validate transaction date (if provided)
    transaction_date = req_data.get("date")
    if transaction_date:
        date_error = validate_transaction_date(transaction_date)
        if date_error:
            return None, date_error
        validated_data["date"] = transaction_date

    # Resolve academic year from date (or fallback to current)
    resolved_date = validated_data.get("date") or date.today()
    if isinstance(resolved_date, str):
        resolved_date = datetime.strptime(resolved_date, "%Y-%m-%d").date()

    academic_year = AcademicYear.objects.filter(
        (Q(start_date__lte=resolved_date) & Q(end_date__gte=resolved_date)) | Q(current=True)
    ).first()
    validated_data["academic_year"] = academic_year

    # Validate amount (if provided)
    amount = req_data.get("amount")
    if amount is not None:
        amount_error = validate_amount(amount)
        if amount_error:
            return None, amount_error
        validated_data["amount"] = amount

    # Validate student (optional)
    student_id = req_data.get("student")
    student, error = validate_student(student_id, required=False)
    if error:
        return None, error
    validated_data["student"] = student

    # Validate transaction type (if provided)
    type_id = req_data.get("type")
    transaction_type = None
    if type_id:
        transaction_type, error = validate_transaction_type(type_id)
        if error:
            return None, error
        validated_data["type"] = transaction_type

    # Validate payment method (if provided)
    payment_method_id = req_data.get("payment_method")
    if payment_method_id:
        payment_method, error = validate_payment_method(payment_method_id)
        if error:
            return None, error
        validated_data["payment_method"] = payment_method

    # Validate bank account (if provided)
    account_id = req_data.get("account")
    account = None
    if account_id or not is_update:
        account, error = validate_bank_account(account_id)
        if error:
            return None, error
        validated_data["account"] = account

    from_account_id = req_data.get("from_account")
    from_account = None
    if from_account_id or not is_update:
        from_account, error = validate_bank_account(from_account_id)
        if error:
            return None, error
        validated_data["from_account"] = from_account

    to_account_id = req_data.get("to_account")
    to_account = None
    if to_account_id or not is_update:
        to_account, error = validate_bank_account(to_account_id)
        if error:
            return None, error
        validated_data["to_account"] = to_account

    # Additional validations if we have all required data
    if student and transaction_type and amount:
        # Validate amount against student balance
        amount_error = validate_amount(amount, student, transaction_type, academic_year)
        if amount_error:
            return None, amount_error

        # Validate pending transactions limit
        pending_error = validate_pending_transactions_limit(
            student, is_update=is_update
        )
        if pending_error:
            return None, pending_error

    # Validate account balance for income
    if account and transaction_type and amount:
        if transaction_type.type == "income":
            amount = abs(amount)  # Ensure income amounts are positive
            validated_data["amount"] = amount

            balance_error = validate_account_balance(account, amount, transaction_type)
            if balance_error:
                return None, balance_error

    # Validate account balance for expenses
    if account and transaction_type and amount:
        if transaction_type.type == "expense":
            amount = -abs(amount)  # Ensure expense amounts are negative
            validated_data["amount"] = amount

            balance_error = validate_account_balance(account, amount, transaction_type)
            if balance_error:
                return None, balance_error

    # Validate account balance for expenses
    # if from_account and transaction_type and amount:
    #     amount = -abs(amount)
    #     validated_data["amount"] = amount

    #     balance_error = validate_account_balance(from_account, amount, transaction_type)
    #     if balance_error:
    #         return None, balance_error

    return validated_data, None
