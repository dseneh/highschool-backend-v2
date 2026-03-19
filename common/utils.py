import base64
import os
import random
import uuid
from datetime import datetime

import pandas as pd
import gc
from typing import Iterator, List, Optional
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from django.conf import settings
from django.core.exceptions import ValidationError as DjangoCoreValidationError
from django.core.validators import validate_email
from django.db.models import Sum, Max, Q
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from finance.models import Transaction



def generate_uuid_hex():
    return uuid.uuid4().hex


def get_object_by_uuid_or_fields(model_class, lookup_value, fields=None):
    """
    Generic utility to get an object by UUID or multiple fallback fields.
    
    This function tries to find an object by:
    1. UUID (if the lookup_value is a valid UUID)
    2. Any of the provided field names
    
    Args:
        model_class: The Django model class to query (e.g., Student, Staff)
        lookup_value: The value to search for (can be UUID string, id_number, etc.)
        fields: List of field names to search. Defaults to ['id_number']
                Example: ['id_number', 'prev_id_number']
    
    Returns:
        Model instance if found
        
    Raises:
        model_class.DoesNotExist: If object not found with the given criteria
        
    Examples:
        >>> # Search Student by id_number or prev_id_number
        >>> student = get_object_by_uuid_or_fields(
        ...     Student, 
        ...     "500001", 
        ...     fields=['id_number', 'prev_id_number']
        ... )
        
        >>> # Search by UUID
        >>> student = get_object_by_uuid_or_fields(
        ...     Student, 
        ...     "123e4567-e89b-12d3-a456-426614174000",
        ...     fields=['id_number']
        ... )
        
        >>> # Search Staff by just id_number (default)
        >>> staff = get_object_by_uuid_or_fields(Staff, "800001")
    """
    if fields is None:
        fields = ['id_number']

    lookup_str = str(lookup_value)

    # Parse UUID once. We only query UUID-backed fields when parsing succeeds.
    parsed_uuid = None
    try:
        parsed_uuid = uuid.UUID(lookup_str)
    except (ValueError, TypeError, AttributeError):
        parsed_uuid = None

    query = Q()
    has_conditions = False

    # Build query for provided fields safely (skip UUID fields for non-UUID input)
    for field in fields:
        try:
            model_field = model_class._meta.get_field(field)
        except Exception:
            continue

        is_uuid_field = getattr(model_field, "get_internal_type", lambda: "")() == "UUIDField"
        if is_uuid_field:
            if parsed_uuid is None:
                continue
            query |= Q(**{field: parsed_uuid})
        else:
            query |= Q(**{field: lookup_value})
        has_conditions = True

    # Add direct ID lookup only when lookup_value is a valid UUID
    if parsed_uuid is not None:
        query |= Q(id=parsed_uuid)
        has_conditions = True

    if not has_conditions:
        raise model_class.DoesNotExist(
            f"{model_class.__name__} does not exist with lookup value '{lookup_value}'"
        )
    
    try:
        return model_class.objects.get(query)
    except model_class.DoesNotExist:
        raise model_class.DoesNotExist(
            f"{model_class.__name__} does not exist with lookup value '{lookup_value}'"
        )


def get_tenant_from_request(request):
    if request:
        # Try request.headers first (Django 2.2+), fallback to META
        if hasattr(request, 'headers'):
            tenant_header = request.headers.get("x-tenant") or request.headers.get("X-Tenant")
            if tenant_header:
                return tenant_header
        # Fallback to META dictionary (always available)
        tenant_header = request.META.get("HTTP_X_TENANT") or request.META.get("http_x_tenant")
        return tenant_header


# create a function to generate unique digits id number
def generate_unique_id_number(class_name, instance):
    # Generate a unique 8-digit number
    while True:
        id_number = str(random.randint(10000000, 99999999))
        if not class_name.objects.filter(id_number=id_number).exists():
            return id_number


def generate_student_id_number(school, student_model=None):
    """
    Generate a unique student ID for SaaS application with school-specific prefix.
    Supports dynamic digit expansion when reaching limits (4-digit -> 5-digit -> 6-digit etc.)

    Format: [School ID last 2 digits][variable-digit sequential number]
    Examples: "120001", "120002", ..., "129999", "1200001", "1200002"

    Args:
        school: School instance
        student_model: Student model class (defaults to importing dynamically)

    Returns:
        str: Unique student ID
    """
    if student_model is None:
        from students.models import Student

        student_model = Student

    from django.db import transaction

    # School ID last 2 digits as prefix
    school_prefix = str(school.id_number)[-2:].zfill(2)

    # Use database transaction to ensure atomicity
    with transaction.atomic():
        # Get all existing student IDs for this school with locking
        existing_students = (
            student_model.objects.filter(id_number__startswith=school_prefix
            )
            .select_for_update()
            .values_list("id_number", flat=True)
        )

        # Group by digit length and find max for each length
        max_by_length = {}

        for id_num in existing_students:
            try:
                seq_part = id_num[len(school_prefix) :]  # Remove school prefix
                if seq_part.isdigit():
                    digit_length = len(seq_part)
                    seq_number = int(seq_part)

                    if digit_length not in max_by_length:
                        max_by_length[digit_length] = seq_number
                    else:
                        max_by_length[digit_length] = max(
                            max_by_length[digit_length], seq_number
                        )
            except (ValueError, IndexError):
                continue

        # Determine the appropriate digit length to use
        if not max_by_length:
            # No existing students, start with 4 digits
            digit_length = 4
            next_number = 1
        else:
            # Find the highest digit length that hasn't reached its maximum
            max_digit_length = max(max_by_length.keys())

            # Always use the highest digit length to maintain proper sorting
            digit_length = max_digit_length
            max_for_current_length = max_by_length[digit_length]
            max_possible = int("9" * digit_length)

            if max_for_current_length < max_possible:
                # Continue with current highest digit length
                next_number = max_for_current_length + 1
            else:
                # Current length is maxed out, expand to next length
                digit_length = max_digit_length + 1
                # Start with all 9s from previous length + 1
                # e.g., after 9999 (4-digit), start with 100000 (6-digit) to maintain sort order
                next_number = int("1" + "0" * (digit_length - 1))

        # Ensure minimum digit length for proper sorting
        if digit_length < 4:
            digit_length = 4

        # Format the sequential part with appropriate zero-padding
        sequential_part = str(next_number).zfill(digit_length)
        student_id = f"{school_prefix}{sequential_part}"

        # Final safety check (should not be needed with proper logic)
        attempts = 0
        while (
            student_model.objects.filter(id_number=student_id).exists() and attempts < 5
        ):
            next_number += 1

            # Check if we need to expand digits
            if len(str(next_number)) > digit_length:
                digit_length += 1

            sequential_part = str(next_number).zfill(digit_length)
            student_id = f"{school_prefix}{sequential_part}"
            attempts += 1

        if attempts >= 5:
            # Last resort fallback with timestamp
            import time

            timestamp = str(int(time.time()))[-6:]  # 6-digit timestamp
            student_id = f"{school_prefix}{timestamp}"

        return student_id


def generate_student_id_number_advanced(
    school, format_type="simple", student_model=None
):
    """
    Advanced student ID generator with multiple format options for SaaS application.
    Supports dynamic digit expansion when reaching limits.

    Args:
        school: School instance
        format_type: "simple", "workspace", or "academic_year"
        student_model: Student model class (defaults to importing dynamically)

    Returns:
        str: Unique student ID

    Format Types:
        - "simple": [School ID last 2 digits][variable-digit sequential] (e.g., "120001" -> "1200001")
        - "workspace": [Workspace first 2 chars][variable-digit sequential] (e.g., "AB0001" -> "AB00001")
        - "academic_year": [Year][School code][variable-digit sequential] (e.g., "2025AB001" -> "2025AB0001")
    """
    if student_model is None:
        from students.models import Student

        student_model = Student

    from django.db.models import Max, Q

    if format_type == "simple":
        school_prefix = str(school.id)[-2:].zfill(2)
        prefix_length = 2
        min_sequential_length = 4  # Start with 4 digits

    elif format_type == "workspace":
        # Format: [Workspace first 2 chars][variable-digit sequential]
        workspace = getattr(school, "workspace", str(school.id))
        school_prefix = workspace[:2].upper().ljust(2, "X")
        prefix_length = 2
        min_sequential_length = 4  # Start with 4 digits

    elif format_type == "academic_year":
        # Format: [Year][School code][variable-digit sequential]
        current_year = datetime.now().year
        workspace = getattr(school, "workspace", str(school.id))
        school_code = workspace[:2].upper().ljust(2, "X")
        school_prefix = f"{current_year}{school_code}"
        prefix_length = 6
        min_sequential_length = 3  # Start with 3 digits

    else:
        raise ValueError(
            "Invalid format_type. Use 'simple', 'workspace', or 'academic_year'"
        )

    # Get all existing students with this prefix
    existing_students = student_model.objects.filter(
        id_number__startswith=school_prefix
    ).values_list("id_number", flat=True)

    # Group by digit length and find max for each length
    max_by_length = {}

    for id_num in existing_students:
        try:
            seq_part = id_num[prefix_length:]
            if seq_part.isdigit():
                digit_length = len(seq_part)
                seq_number = int(seq_part)

                if digit_length not in max_by_length:
                    max_by_length[digit_length] = seq_number
                else:
                    max_by_length[digit_length] = max(
                        max_by_length[digit_length], seq_number
                    )
        except (ValueError, IndexError):
            continue

    # Determine the appropriate digit length to use
    if not max_by_length:
        # No existing students, start with minimum digits
        digit_length = min_sequential_length
        next_number = 1
    else:
        # Always use the highest digit length to maintain proper sorting
        max_digit_length = max(max_by_length.keys())
        digit_length = max_digit_length
        max_for_current_length = max_by_length[digit_length]
        max_possible = int("9" * digit_length)

        if max_for_current_length < max_possible:
            # Continue with current highest digit length
            next_number = max_for_current_length + 1
        else:
            # Current length is maxed out, expand to next length
            digit_length = max_digit_length + 1
            # Start with proper value to maintain sort order
            next_number = int("1" + "0" * (digit_length - 1))

    # Ensure minimum digit length
    if digit_length < min_sequential_length:
        digit_length = min_sequential_length

    # Format the sequential part
    sequential_part = str(next_number).zfill(digit_length)
    student_id = f"{school_prefix}{sequential_part}"

    # Final safety check
    attempts = 0
    while student_model.objects.filter(id_number=student_id).exists() and attempts < 5:
        next_number += 1

        # Check if we need to expand digits
        if len(str(next_number)) > digit_length:
            digit_length += 1

        sequential_part = str(next_number).zfill(digit_length)
        student_id = f"{school_prefix}{sequential_part}"
        attempts += 1

    if attempts >= 5:
        # Fallback with timestamp
        import time

        timestamp = str(int(time.time()))[-digit_length:]
        student_id = f"{school_prefix}{timestamp}"

    return student_id


def create_model_data(request, data, model, serializer):
    """
    Creates a new instance of a model, serializes it, and returns a response.
    Args:
        request (HttpRequest): The HTTP request object containing the user information.
        data (dict): A dictionary of data to be used for creating the model instance.
        model (Model): The Django model class to create an instance of.
        serializer (Serializer): The serializer class to serialize the created model instance.
    Returns:
        Response: A Django REST framework Response object containing the serialized data
                  and a status code of 201 if successful, or an error message and a
                  status code of 400 if an exception occurs.
    """

    try:
        data["updated_by"] = request.user
        data["created_by"] = request.user

        obj = model.objects.create(**data)
        serializer = serializer(obj, context={"request": request})

        return Response(serializer.data, status=201)
    except Exception as e:
        return Response({"detail": str(e)}, status=400)


def update_model_fields(request, model, allowed_fields, serializer_class, context=None):
    """
    Updates the fields of a given model instance based on the provided request data.
    Args:
        request (Request): The HTTP request object containing the data to update the model.
        model (Model): The model instance to be updated.
        allowed_fields (list): A list of field names that are allowed to be updated.
        serializer_class (Serializer): The serializer class used to validate and serialize the updated model.
    Returns:
        Serializer: An instance of the serializer class containing the updated model data.
    """
    # Use the core update function
    update_fields = update_model_fields_core(
        model, request.data, allowed_fields, request.user
    )

    try:
        # Only serialize fields that were updated
        data = {
            key: request.data.get(key) for key in update_fields if key in request.data
        }

        # Use provided context or default to request context
        serializer_context = context if context is not None else {"request": request}
        serializer = serializer_class(
            model, data=data, partial=True, context=serializer_context
        )
        # Validate the serializer
        if not serializer.is_valid():
            raise ValidationError(serializer.errors)  # Raise validation errors if any

        return Response(serializer.data, status=200)
    except Exception as e:
        raise ValidationError(str(e))


def update_model_fields_core(model, data, allowed_fields, user=None):
    """
    Core function to update model instance fields from data dictionary.
    This is the reusable core logic used by both view layer and service layer.

    Args:
        model: Model instance to update
        data: Dictionary of field values to update
        allowed_fields: List of allowed field names
        user: Optional user for updated_by field

    Returns:
        list: List of fields that were actually updated
    """
    # Filter out fields that have the same value as the existing model instance
    update_data = {
        key: data.get(key)
        for key in data.keys()
        if key in allowed_fields and getattr(model, key, None) != data.get(key)
    }

    if update_data:
        # Add metadata fields if user is provided
        if user:
            if hasattr(model, "updated_by"):
                update_data["updated_by"] = user
            if hasattr(model, "updated_at"):
                update_data["updated_at"] = timezone.now()

        # Set all field values
        for key, value in update_data.items():
            setattr(model, key, value)

        # Save only the changed fields
        model.save(update_fields=list(update_data.keys()))

        return list(update_data.keys())

    return []


def validate_required_fields(request, required_fields):
    """
    Validates that the required fields are present in the request data.
    Args:
        request (Request): The HTTP request object containing the data to validate.
        required_fields (list): A list of field names that are required.
    Raises:
        ValidationError: If any of the required fields are missing in the request data.
    """
    validation_errors = []

    for field in required_fields:
        if field not in request.data:
            validation_errors.append(f"{field} is required")

    if validation_errors:
        raise ValidationError({"details": validation_errors}, code=400)

    return True



def get_enrollment_bill_summary(
    enrollment, include_payment_plan=False, include_payment_status=False
):
    """
    Get billing summary for an enrollment including separated fees, tuition, total amount, paid amount, and balance.
    Optimized to use prefetched data when available to avoid N+1 queries.

    Args:
        enrollment: Enrollment instance (should have prefetched student_bills and payment_summary)
        include_payment_plan: Whether to include payment plan
        include_payment_status: Whether to include payment status

    Returns:
        dict: Contains total_fees, tuition, total_amount, amount_paid, balance
    """
    from decimal import Decimal

    # Get total fees (excluding tuition)
    # Define bill type categories for clarity
    FEE_TYPES = {"fee", "other", "general", "General"}
    TUITION_TYPES = {"tuition", "Tuition Fee", "Tuition"}

    # Use prefetched student_bills if available, otherwise query
    if (
        hasattr(enrollment, "_prefetched_objects_cache")
        and "student_bills" in enrollment._prefetched_objects_cache
    ):
        # Use prefetched bills (no query)
        prefetched_bills = enrollment._prefetched_objects_cache["student_bills"]
        total_fees = sum(
            float(bill.amount) for bill in prefetched_bills if bill.type in FEE_TYPES
        )
        tuition = sum(
            float(bill.amount)
            for bill in prefetched_bills
            if bill.type in TUITION_TYPES
        )
    else:
        # Fallback: query if not prefetched
        total_fees = (
            enrollment.student_bills.filter(type__in=FEE_TYPES).aggregate(
                total=Sum("amount")
            )["total"]
            or 0
        )
        tuition = (
            enrollment.student_bills.filter(type__in=TUITION_TYPES).aggregate(
                total=Sum("amount")
            )["total"]
            or 0
        )

    # Calculate gross total amount (before concessions)
    gross_total_bill = Decimal(str(total_fees)) + Decimal(str(tuition))
    # Calculate concessions
    concession_data = {"items": [], "total_concession": Decimal("0")}
    try:
        from students.models.billing import calculate_concessions_for_enrollment
        concession_data = calculate_concessions_for_enrollment(enrollment)
    except Exception:
        pass

    total_concession = Decimal(str(concession_data.get("total_concession", 0)))
    concession_items = concession_data.get("items", [])
    # Calculate net total amount (after concessions)
    net_total_bill = gross_total_bill - total_concession
    if net_total_bill < 0:
        net_total_bill = Decimal("0")

    # Get transactional paid amount from transactions
    # Try to use prefetched transactions first
    # Only count approved income transactions for the current academic year
    transactional_paid = Decimal("0")
    academic_year = enrollment.academic_year
    try:
        if (
            hasattr(enrollment.student, "_prefetched_objects_cache")
            and "transactions" in enrollment.student._prefetched_objects_cache
        ):
            # Use prefetched transactions (no query)
            prefetched_transactions = enrollment.student._prefetched_objects_cache[
                "transactions"
            ]
            transactional_paid = sum(
                Decimal(str(t.amount))
                for t in prefetched_transactions
                if t.status == "approved" 
                and getattr(t, "academic_year_id", None) == academic_year.id
                and getattr(getattr(t, "type", None), "type", None) == "income"
            )
        else:
            # Fallback: query if not prefetched
            transactional_paid = Decimal(
                str(
                    enrollment.student.transactions.filter(
                        status="approved",
                        academic_year=academic_year,
                        type__type="income"  # Only income transactions (payments received)
                    ).aggregate(
                        total=Sum("amount")
                    )["total"]
                    or 0
                )
            )
    except (ImportError, AttributeError):
        # Fallback if Transaction model doesn't exist or different structure
        transactional_paid = Decimal("0")
    # Get payment plan and payment status.
    # IMPORTANT: Always calculate these with live helpers so installment
    # schedules are based on net bill (gross - concessions), not stale snapshots.
    payment_plan = []
    payment_status = {}
    try:
        from finance.models import (
            get_student_payment_plan,
            get_student_payment_status,
        )

        academic_year = enrollment.academic_year
        if include_payment_plan:
            payment_plan = get_student_payment_plan(enrollment, academic_year) or []

        if include_payment_status:
            payment_status = get_student_payment_status(enrollment, academic_year) or {}
            # Remove duplicate fields that are already in billing_summary
            payment_status.pop("total_bills", None)
            payment_status.pop("total_paid", None)
            payment_status.pop("overall_balance", None)
    except Exception:
        # If payment plan/status cannot be generated, return defaults
        pass

    # Payments should always reflect transactional payments only.
    # Concessions reduce the bill (net total) and are not counted as paid cash.
    amount_paid = transactional_paid

    # Balance is always computed from net bill.
    balance = net_total_bill - amount_paid
    if balance < 0:
        balance = Decimal("0")

    return {
        "total_fees": float(total_fees),
        "tuition": float(tuition),
        "gross_total_bill": float(gross_total_bill),
        "net_total_bill": float(net_total_bill),
        "total_concession": float(total_concession),
        "concessions": concession_items,
        "total_bill": float(net_total_bill),
        "paid": float(amount_paid),
        "balance": float(balance),
        "payment_plan": payment_plan,
        "payment_status": payment_status,
    }

def encrypt_data(plaintext: str) -> dict:
    key = base64.b64decode(settings.SECRET_AES_KEY)
    iv = os.urandom(16)
    cipher = Cipher(algorithms.AES(key), modes.CFB(iv))
    encryptor = cipher.encryptor()
    encrypted = encryptor.update(plaintext.encode()) + encryptor.finalize()
    return {
        "iv": base64.b64encode(iv).decode(),
        "data": base64.b64encode(encrypted).decode(),
    }


# =============================================================================
# IMPORT UTILITIES
# =============================================================================


class StudentImportValidator:
    """Handles validation for student import operations"""

    # Configuration constants
    MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
    MAX_ROWS = 10000  # Maximum rows to process
    CHUNK_SIZE = 500  # Process in chunks for memory efficiency

    REQUIRED_FIELDS = [
        "first_name",
        "last_name",
        "date_of_birth",
        "gender",
        "country",
        "enrolled_as",
    ]

    VALID_ENROLLMENT_STATUS = {"new", "returning", "transferred"}
    VALID_GENDERS = {"male", "female"}

    @classmethod
    def validate_file_safety(cls, file_obj):
        """
        Validate file safety and integrity

        Args:
            file_obj: Uploaded file object

        Returns:
            list: List of error messages
        """
        errors = []

        # Check file size
        if file_obj.size > cls.MAX_FILE_SIZE:
            errors.append(
                f"File too large. Maximum size is {cls.MAX_FILE_SIZE / (1024*1024):.0f}MB"
            )

        # Check file extension
        if not file_obj.name.lower().endswith(".csv"):
            errors.append("Only CSV files are supported")

        # Check content type
        if file_obj.content_type and "csv" not in file_obj.content_type.lower():
            errors.append("Invalid file content type")

        # Basic file corruption check - try to read first few bytes
        try:
            file_obj.seek(0)
            first_chunk = file_obj.read(1024)
            file_obj.seek(0)

            # Check for null bytes (sign of corruption)
            if b"\x00" in first_chunk:
                errors.append("File appears to be corrupted (contains null bytes)")

            # Check if it's actually text
            try:
                first_chunk.decode("utf-8")
            except UnicodeDecodeError:
                errors.append("File encoding is not supported (must be UTF-8)")
        except Exception:
            errors.append("Unable to read file - may be corrupted")

        return errors

    @classmethod
    def validate_csv_structure(cls, df):
        """
        Validate CSV structure and data integrity

        Args:
            df: Pandas DataFrame

        Returns:
            list: List of error messages
        """
        errors = []

        # Check if DataFrame is empty
        if df.empty:
            errors.append("CSV file is empty")
            return errors

        # Check row count
        if len(df) > cls.MAX_ROWS:
            errors.append(f"Too many rows. Maximum allowed: {cls.MAX_ROWS}")

        # Check for required columns
        missing_fields = [
            field for field in cls.REQUIRED_FIELDS if field not in df.columns
        ]
        if missing_fields:
            errors.append(f"Missing required columns: {', '.join(missing_fields)}")

        # Check for completely empty rows
        empty_rows = df.isnull().all(axis=1).sum()
        if empty_rows > 0:
            errors.append(f"Found {empty_rows} completely empty rows")

        # Reuse the same duplicate logic as student POST (check_student_exists)
        # so single-create and bulk-import enforce the same behavior.
        if all(col in df.columns for col in ['first_name', 'last_name', 'date_of_birth']):
            from business.students.adapters import check_student_exists

            # Track duplicates within file using the same matching semantics:
            # - first_name + last_name + date_of_birth
            # - and prev_id_number only when provided
            seen_keys = {}
            in_file_duplicate_info = []
            existing_duplicate_info = []

            for idx, row in df.iterrows():
                first_name = clean_csv_value(row.get('first_name'))
                last_name = clean_csv_value(row.get('last_name'))
                date_of_birth = clean_csv_value(row.get('date_of_birth'))
                prev_id_number = clean_csv_value(row.get('prev_id_number'))

                if not first_name or not last_name or not date_of_birth:
                    continue

                normalized_prev = prev_id_number.lower() if prev_id_number else ""
                key = (
                    first_name.strip().lower(),
                    last_name.strip().lower(),
                    date_of_birth.strip(),
                    normalized_prev,
                )

                if key in seen_keys:
                    first_seen_row = seen_keys[key]
                    in_file_duplicate_info.append(
                        f"{first_name.title()} {last_name.title()} (DOB: {date_of_birth}) duplicated in rows {first_seen_row} and {idx + 2}"
                    )
                else:
                    seen_keys[key] = idx + 2

                # Check existing DB records with the exact same logic used by POST endpoint
                if check_student_exists(
                    first_name,
                    last_name,
                    date_of_birth,
                    prev_id_number or None,
                ):
                    existing_duplicate_info.append(
                        f"{first_name.title()} {last_name.title()} (DOB: {date_of_birth}) already exists"
                    )

            if in_file_duplicate_info:
                error_msg = (
                    f"Found {len(in_file_duplicate_info)} duplicate student(s) in the file: "
                    f"{', '.join(in_file_duplicate_info[:3])}"
                )
                if len(in_file_duplicate_info) > 3:
                    error_msg += f" and {len(in_file_duplicate_info) - 3} more..."
                errors.append(error_msg)

            if existing_duplicate_info:
                unique_existing = list(dict.fromkeys(existing_duplicate_info))
                error_msg = (
                    f"Found {len(unique_existing)} student(s) that already exist: "
                    f"{', '.join(unique_existing[:3])}"
                )
                if len(unique_existing) > 3:
                    error_msg += f" and {len(unique_existing) - 3} more..."
                errors.append(error_msg)

        return errors

    @classmethod
    def validate_row_data(cls, row, row_number):
        """
        Validate individual row data

        Args:
            row: Pandas Series representing a row
            row_number: Row number for error reporting

        Returns:
            list: List of error messages
        """
        errors = []

        try:
            # Check required fields
            for field in cls.REQUIRED_FIELDS:
                field_value = clean_csv_value(row.get(field))
                if not field_value:
                    errors.append(f"Row {row_number}: {field} is required")

            # Email validation
            try:
                email = clean_csv_value(row.get("email"))
                if email:
                    validate_email(email)
            except DjangoCoreValidationError:
                errors.append(f"Row {row_number}: Invalid email format")

            # Gender validation
            gender = clean_csv_value(row.get("gender")).lower()
            if gender and gender not in cls.VALID_GENDERS:
                errors.append(
                    f"Row {row_number}: Invalid gender '{gender}'. Must be 'male' or 'female'"
                )

            # Enrollment status validation
            enrolled_status = clean_csv_value(row.get("enrolled_as")).lower()
            if enrolled_status and enrolled_status not in cls.VALID_ENROLLMENT_STATUS:
                errors.append(
                    f"Row {row_number}: Invalid enrolled_as '{enrolled_status}'. Must be one of: {', '.join(cls.VALID_ENROLLMENT_STATUS)}"
                )

            # Date validation with proper format support
            try:
                date_of_birth = row.get("date_of_birth")
                if not pd.isna(date_of_birth) and date_of_birth is not None:
                    parse_date_safely(date_of_birth)
            except ValueError as e:
                errors.append(f"Row {row_number}: Invalid date_of_birth - {str(e)}")

            try:
                entry_date = row.get("entry_date")
                if not pd.isna(entry_date) and entry_date is not None:
                    parse_date_safely(entry_date)
            except ValueError as e:
                errors.append(f"Row {row_number}: Invalid entry_date - {str(e)}")

        except Exception as e:
            errors.append(f"Row {row_number}: Validation error - {str(e)}")

        return errors


def parse_date_safely(date_value):
    """
    Parse date value supporting multiple formats

    Args:
        date_value: Date value from CSV (could be string, datetime, etc.)

    Returns:
        datetime.date: Parsed date object

    Raises:
        ValueError: If date cannot be parsed
    """
    if pd.isna(date_value) or date_value is None:
        raise ValueError("Date value is null or empty")

    # If it's already a datetime object, extract the date
    if hasattr(date_value, "date"):
        return date_value.date()

    # Convert to string for parsing
    date_str = str(date_value).strip()

    # Handle common null representations
    if date_str.lower() in ["<na>", "nan", "null", "none", ""]:
        raise ValueError("Date value is null or empty")

    # Try different date formats
    date_formats = [
        "%m/%d/%Y",  # mm/dd/yyyy (e.g., 12/25/2000)
        "%m/%d/%y",  # mm/dd/yy (e.g., 12/25/00)
        "%Y-%m-%d",  # yyyy-mm-dd (e.g., 2000-12-25)
        "%d/%m/%Y",  # dd/mm/yyyy (e.g., 25/12/2000)
        "%d-%m-%Y",  # dd-mm-yyyy (e.g., 25-12-2000)
        "%Y/%m/%d",  # yyyy/mm/dd (e.g., 2000/12/25)
    ]

    # First try pandas to_datetime which is very flexible
    try:
        parsed_date = pd.to_datetime(date_str, infer_datetime_format=True)
        return parsed_date.date()
    except:
        pass

    # If pandas fails, try manual parsing with specific formats
    for date_format in date_formats:
        try:
            parsed_date = datetime.strptime(date_str, date_format)
            return parsed_date.date()
        except ValueError:
            continue

    # If all formats fail, raise an error
    raise ValueError(
        f"Unable to parse date '{date_str}'. Supported formats: mm/dd/yyyy, yyyy-mm-dd, dd/mm/yyyy"
    )


def clean_csv_value(value):
    """
    Clean CSV value by handling null values and stripping whitespace

    Args:
        value: Raw value from CSV

    Returns:
        str: Cleaned string value or empty string for null values
    """
    if pd.isna(value) or value is None:
        return ""

    str_value = str(value).strip()

    # Handle pandas string representations of null
    if str_value.lower() in ["<na>", "nan", "null", "none", ""]:
        return ""

    return str_value


class StudentBulkProcessor:
    """Handles bulk processing of student data"""

    @staticmethod
    def _resolve_school_code() -> int:
        """Resolve school_code from the active tenant schema."""
        try:
            from django.db import connection
            from core.models import Tenant

            tenant = Tenant.objects.filter(schema_name=connection.schema_name).first()
            if tenant and tenant.id_number:
                return int(str(tenant.id_number)[-2:])
        except Exception:
            pass

        return 1

    @staticmethod
    def generate_unique_id(school=None):
        """
        Generate a unique student ID - simplified version for sequential numbering

        Args:
            school: School instance

        Returns:
            str: Unique student ID
        """
        if school:
            return generate_student_id_number(school)
        else:
            # Fallback to the old method if no school provided
            year = datetime.now().year
            return f"{year}{uuid.uuid4().hex[:6]}"

    @staticmethod
    def process_chunk(chunk, grade_level, request_user):
        """
        Process a chunk of students with bulk operations

        Args:
            chunk: Pandas DataFrame chunk
            grade_level: GradeLevel instance
            request_user: User making the request

        Returns:
            tuple: (students_to_create, users_to_create, chunk_errors)
        """
        from students.models import Student

        students_to_create = []
        users_to_create = []
        chunk_errors = []
        school_code = StudentBulkProcessor._resolve_school_code()

        for index, row in chunk.iterrows():
            try:
                # Get student name for error reporting
                first_name = clean_csv_value(row.get("first_name"))
                last_name = clean_csv_value(row.get("last_name"))
                student_name = f"{first_name} {last_name}"

                # Allocate sequential student ID with robust conflict resolution
                student_seq = StudentBulkProcessor._get_next_available_sequence(
                    school_code, student_name
                )

                # Handle entry_date with null checking
                entry_date = row.get("entry_date")
                if pd.isna(entry_date) or not entry_date:
                    entry_date = timezone.now().date()
                else:
                    try:
                        entry_date = parse_date_safely(entry_date)
                    except ValueError:
                        entry_date = timezone.now().date()

                # Handle date_of_birth with null checking
                date_of_birth = row.get("date_of_birth")
                if pd.isna(date_of_birth):
                    raise ValidationError(
                        "date_of_birth is required and cannot be empty"
                    )

                try:
                    date_of_birth = parse_date_safely(date_of_birth)
                except ValueError as e:
                    raise ValidationError(f"Invalid date_of_birth format: {str(e)}")

                # Prepare student data with proper null handling
                student_data = {
                    "school_code": school_code,
                    "student_seq": student_seq,
                    "first_name": first_name,
                    "middle_name": clean_csv_value(row.get("middle_name")),
                    "last_name": last_name,
                    "date_of_birth": date_of_birth,
                    "gender": clean_csv_value(row.get("gender")).lower(),
                    "email": clean_csv_value(row.get("email")),
                    "phone_number": clean_csv_value(row.get("phone_number")),
                    "address": clean_csv_value(row.get("address")),
                    "city": clean_csv_value(row.get("city")),
                    "state": clean_csv_value(row.get("state")),
                    "postal_code": clean_csv_value(row.get("postal_code")),
                    "country": clean_csv_value(row.get("country")),
                    "place_of_birth": clean_csv_value(row.get("place_of_birth")),
                    "entry_date": entry_date,
                    "grade_level": grade_level,
                    "created_by": request_user,
                    "updated_by": request_user,
                    "status": "active",
                    "entry_as": clean_csv_value(row.get("enrolled_as")).lower(),
                }

                students_to_create.append(Student(**student_data))

            except Exception as e:
                # Create consistent error format with student name if available
                student_name = f"{clean_csv_value(row.get('first_name', ''))} {clean_csv_value(row.get('last_name', ''))}".strip()
                if student_name:
                    error_message = f"Row Student {student_name}: {str(e)}"
                else:
                    error_message = f"Row {index + 2}: {str(e)}"
                chunk_errors.append(error_message)

        return students_to_create, users_to_create, chunk_errors

    @staticmethod
    def _get_next_available_sequence(school_code, student_name):
        """
        Get the next available sequence number that won't cause ID conflicts.

        This method handles cases where the sequence counter is out of sync
        by finding gaps in the sequence or advancing beyond conflicts.
        """
        from students.models import Student, StudentSequence
        from django.db import transaction

        max_attempts = 100  # Reasonable upper limit

        with transaction.atomic():
            # Get or create sequence counter
            sequence_obj, created = (
                StudentSequence.objects.select_for_update().get_or_create()
            )

            # If this is a fresh sequence counter, sync it with existing data
            if created or sequence_obj.last_seq == 0:
                max_existing_seq = (
                    Student.objects.all().aggregate(
                        max_seq=Max("student_seq")
                    )["max_seq"]
                    or 0
                )
                sequence_obj.last_seq = max_existing_seq
                sequence_obj.save()

            starting_seq = sequence_obj.last_seq

            for attempt in range(max_attempts):
                # Try the next sequence number
                test_seq = starting_seq + attempt + 1
                test_id = compute_id_number(school_code, test_seq)

                # Check if this ID is available
                if not Student.objects.filter(id_number=test_id).exists():
                    # Found an available sequence
                    sequence_obj.last_seq = test_seq
                    sequence_obj.save()
                    return test_seq

            # If we've exhausted all attempts, there might be a systematic issue
            # Try to find the actual maximum sequence and jump beyond it
            all_students = Student.objects.all()
            if all_students.exists():
                max_actual_seq = all_students.aggregate(max_seq=Max("student_seq"))[
                    "max_seq"
                ]
                # Jump to a safe position beyond all existing sequences
                safe_seq = max_actual_seq + 100  # Give some buffer

                # Verify this safe sequence works
                safe_id = compute_id_number(school_code, safe_seq)
                if not Student.objects.filter(id_number=safe_id).exists():
                    sequence_obj.last_seq = safe_seq
                    sequence_obj.save()
                    return safe_seq

            # Last resort: use a timestamp-based approach
            import time

            timestamp_seq = int(time.time()) % 100000  # Use last 5 digits of timestamp
            sequence_obj.last_seq = timestamp_seq
            sequence_obj.save()

            raise ValidationError(
                f"Unable to generate unique sequence for student {student_name}. "
                f"Database may have sequence synchronization issues that require manual intervention."
            )

    @staticmethod
    def create_user_accounts(created_students, request_user):
        """
        Create user accounts for newly created students and link them

        Args:
            created_students: List of Student instances
            request_user: User making the request

        Returns:
            list: Created User instances
        """
        from django.db import transaction

        from users.models import User

        user_accounts = []
        with transaction.atomic():

            for student in created_students:
                user_accounts.append(
                    User(
                        id_number=student.id_number,
                        username=student.id_number,
                        email=student.email,
                        gender=student.gender,
                        role="student",
                        created_by=request_user,
                        updated_by=request_user,
                        is_active=True,
                    )
                )

            if user_accounts:
                # Create user accounts in bulk
                created_users = User.objects.bulk_create(
                    user_accounts, batch_size=100
                )

                # Create a mapping of id_number to user for efficient lookup
                user_mapping = {user.id_number: user for user in created_users}

                students_to_update = []
                for student in created_students:
                    if student.id_number in user_mapping:
                        # Store the user's id_number as reference (not FK)
                        student.user_account_id_number = student.id_number
                        students_to_update.append(student)

                # Bulk update students with their user account references
                if students_to_update:
                    from students.models import Student

                    Student.objects.bulk_update(
                        students_to_update, ["user_account_id_number"], batch_size=100
                    )

            return created_users
        return []


def read_csv_safely(file_obj):
    """
    Safely read CSV file with proper encoding and parameters

    Args:
        file_obj: Uploaded file object

    Returns:
        pandas.DataFrame: The CSV data

    Raises:
        Exception: If CSV cannot be read
    """
    df = pd.read_csv(
        file_obj,
        encoding="utf-8",
        skipinitialspace=True,
        na_filter=True,
        keep_default_na=True,
        dtype=str,  # Read everything as string initially
    )

    # Clean up the DataFrame to handle common issues
    # Replace empty strings with NaN for consistent null handling
    df = df.replace("", pd.NA)

    # Strip whitespace from all string columns and handle <NA> strings
    for col in df.columns:
        if df[col].dtype == "object":
            # Replace pandas <NA> string representations with actual NaN
            df[col] = df[col].replace(["<NA>", "nan", "NaN", "null", "NULL"], pd.NA)
            # Strip whitespace only from non-null values
            df[col] = df[col].apply(lambda x: str(x).strip() if not pd.isna(x) else x)

    return df


def read_csv_stream(
    csv_file,
    *,
    chunksize: int = StudentImportValidator.CHUNK_SIZE,
    max_rows: int = StudentImportValidator.MAX_ROWS,
    usecols: Optional[List[str]] = None,
) -> Iterator[pd.DataFrame]:
    """
    Read a CSV file in streaming chunks to reduce memory usage.
    Yields each DataFrame chunk and frees memory after processing.
    """
    for df_chunk in pd.read_csv(
        csv_file,
        encoding="utf-8",
        skipinitialspace=True,
        na_filter=True,
        keep_default_na=True,
        dtype=str,
        chunksize=chunksize,
        nrows=max_rows,
        usecols=usecols,
    ):
        # Remove rows that are completely blank
        df_chunk = df_chunk.dropna(how="all")
        yield df_chunk
        # Free memory for processed chunk
        del df_chunk
        gc.collect()


def validate_sample_data(df, sample_size=100):
    """
    Validate a sample of the data for quick feedback

    Args:
        df: Pandas DataFrame
        sample_size: Number of rows to validate

    Returns:
        list: List of validation errors
    """
    validation_errors = []
    sample_size = min(sample_size, len(df))

    for index, row in df.head(sample_size).iterrows():
        row_errors = StudentImportValidator.validate_row_data(row, index + 2)
        validation_errors.extend(row_errors)

    return validation_errors


def format_import_response(total_created, all_errors, success=True):
    """
    Format the import response with consistent structure

    Args:
        total_created: Number of students created
        all_errors: List of all errors encountered
        success: Whether the import was successful

    Returns:
        dict: Formatted response data with consistent error format
    """
    # Normalize all errors to string format for consistent frontend handling
    normalized_errors = []
    for error in all_errors or []:
        if isinstance(error, dict) and "row" in error and "error" in error:
            # Convert {row: X, error: Y} format to "Row X: Y" string
            normalized_errors.append(f"Row {error['row']}: {error['error']}")
        elif isinstance(error, str):
            # Keep string errors as-is
            normalized_errors.append(error)
        else:
            # Convert any other type to string
            normalized_errors.append(str(error))

    return {
        "success": success,
        "created": total_created,
        "errors": normalized_errors[:20],  # Limit to first 20 errors
        "total_errors": len(all_errors) if all_errors else 0,
        "message": f"Successfully imported {total_created} students"
        + (f" with {len(all_errors)} errors" if all_errors else ""),
    }


def compute_id_number(school_code: int, student_seq: int) -> str:
    """
    Format: <2-digit school_code><sequence with at least 4 digits, then grows>.
    Examples: 01 + 1 -> 010001 ; 01 + 10000 -> 0110000
    """
    seq = str(int(student_seq))
    width = max(4, len(seq))  # 0001..9999 -> 4, then 10000 -> 5, etc.
    return f"{int(school_code):02}{int(student_seq):0{width}d}"
