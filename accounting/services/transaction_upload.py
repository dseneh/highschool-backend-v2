"""
Template-based transaction upload service.

Supports three templates:
1. Student Tuition Payment (requires student_id_number, auto-uses TUITION trans type)
2. Staff Salaries (requires staff_id_number, auto-uses STAFF_* trans type)
3. General Transactions (requires transaction_type_code from file)

Transaction type is auto-assigned for tuition/salary.
User can override GL account on preview screen.
"""

import io
import uuid
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal, InvalidOperation

import pandas as pd
from django.db import transaction

from accounting.models import (
    AccountingBankAccount,
    AccountingCashTransaction,
    AccountingCurrency,
    AccountingLedgerAccount,
    AccountingPaymentMethod,
    AccountingTransactionType,
)
from staff.models import Staff
from students.models import Student


MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
ALLOWED_EXTENSIONS = (".csv", ".xlsx", ".xls")
BULK_CHUNK_SIZE = 500

# Template types
TEMPLATE_TUITION = "tuition"
TEMPLATE_SALARY = "salary"
TEMPLATE_GENERAL = "general"

VALID_TEMPLATES = {TEMPLATE_TUITION, TEMPLATE_SALARY, TEMPLATE_GENERAL}

# Template-specific required columns
TEMPLATE_REQUIRED_COLUMNS = {
    TEMPLATE_TUITION: {"transaction_date", "student_id_number", "amount", "description"},
    TEMPLATE_SALARY: {"transaction_date", "staff_id_number", "amount", "description"},
    TEMPLATE_GENERAL: {"transaction_date", "transaction_type_code", "amount", "description"},
}

# Optional columns for all templates
OPTIONAL_COLUMNS = {"reference_number", "payer_payee"}


def _read_file_to_dataframe(uploaded_file) -> pd.DataFrame:
    """Parse an uploaded CSV or Excel file into a DataFrame."""
    name = uploaded_file.name.lower()
    content = uploaded_file.read()
    buf = io.BytesIO(content)

    if name.endswith(".csv"):
        df = pd.read_csv(buf, dtype=str, keep_default_na=False)
    elif name.endswith((".xlsx", ".xls")):
        df = pd.read_excel(buf, dtype=str, keep_default_na=False, engine="openpyxl")
    else:
        raise ValueError("Unsupported file type. Upload CSV or Excel (.xlsx/.xls).")

    # Normalize column names: lowercase, strip whitespace, replace spaces with _
    df.columns = [col.strip().lower().replace(" ", "_") for col in df.columns]
    return df


def _validate_file(uploaded_file):
    """Common file-level validation."""
    if not uploaded_file:
        raise ValueError("No file provided.")
    if not uploaded_file.name.lower().endswith(ALLOWED_EXTENSIONS):
        raise ValueError(f"Unsupported file type. Allowed: {', '.join(ALLOWED_EXTENSIONS)}")
    if uploaded_file.size > MAX_FILE_SIZE:
        raise ValueError(f"File too large ({uploaded_file.size / (1024 * 1024):.1f} MB). Max: 10 MB.")


def _cell(row, col, default=""):
    """Safely get a cell value as stripped string."""
    val = row.get(col, default)
    if pd.isna(val):
        return ""
    return str(val).strip()


def _generate_ref(prefix: str = "TXN") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def _resolve_transaction_type_with_fallback(transaction_types: dict, code: str, override_gl_account):
    """
    Resolve transaction type primarily by code; if missing, fall back to
    transaction types linked to the selected GL override account.
    """
    normalized_code = (code or "").strip().lower()
    if normalized_code:
        by_code = transaction_types.get(normalized_code)
        if by_code:
            return by_code

    if not override_gl_account:
        return None

    # Fallback 1: tx type code equals selected GL account code.
    by_gl_code = transaction_types.get((override_gl_account.code or "").strip().lower())
    if by_gl_code:
        return by_gl_code

    # Fallback 2: first active tx type whose default ledger account is this GL account.
    return (
        AccountingTransactionType.objects.filter(
            is_active=True,
            default_ledger_account=override_gl_account,
        )
        .order_by("name")
        .first()
    )


def _get_tuition_transaction_type(transaction_types: dict):
    """Get the dedicated TUITION transaction type."""
    tx_type = transaction_types.get("tuition")
    if tx_type:
        return tx_type
    # Fallback: query the database
    return AccountingTransactionType.objects.filter(
        code__iexact="TUITION", is_active=True
    ).first()


def _get_staff_transaction_type(transaction_types: dict):
    """Get a transaction type with 'STAFF_' prefix."""
    # Look for any transaction type starting with STAFF_
    for code, tx_type in transaction_types.items():
        if code.startswith("staff_"):
            return tx_type
    # Fallback: query the database
    return AccountingTransactionType.objects.filter(
        code__istartswith="STAFF_", is_active=True
    ).order_by("code").first()


def _validate_student_id(student_id: str) -> tuple[bool, str]:
    """
    Validate that student_id exists in the Student table.
    Returns: (is_valid, error_message)
    """
    if not student_id or not student_id.isdigit() or len(student_id) < 5:
        return False, f"Student ID '{student_id}' must be at least 5 digits"
    
    try:
        Student.objects.get(id_number=student_id)
        return True, ""
    except Student.DoesNotExist:
        return False, f"Student with ID '{student_id}' not found"


def _validate_staff_id(staff_id: str) -> tuple[bool, str]:
    """
    Validate that staff_id exists in the Staff table.
    Returns: (is_valid, error_message)
    """
    if not staff_id:
        return False, "Staff ID is required"

    try:
        Staff.objects.get(id_number=staff_id)
        return True, ""
    except Staff.DoesNotExist:
        return False, f"Staff member with ID '{staff_id}' not found"


def _prefetch_students_by_id_number(df: pd.DataFrame) -> dict[str, Student]:
    if "student_id_number" not in df.columns:
        return {}
    id_numbers = {
        str(value).strip()
        for value in df["student_id_number"].tolist()
        if str(value).strip()
    }
    if not id_numbers:
        return {}
    return {
        student.id_number: student
        for student in Student.objects.filter(id_number__in=id_numbers)
    }


def _prefetch_staff_by_id_number(df: pd.DataFrame) -> dict[str, Staff]:
    if "staff_id_number" not in df.columns:
        return {}
    id_numbers = {
        str(value).strip()
        for value in df["staff_id_number"].tolist()
        if str(value).strip()
    }
    if not id_numbers:
        return {}
    return {
        staff.id_number: staff
        for staff in Staff.objects.filter(id_number__in=id_numbers)
    }


def upload_transactions(
    uploaded_file,
    template_type: str,
    bank_account_id: str | None = None,
    gl_account_override: str | None = None,
    status_override: str | None = None,
    replace_by_ref_number: bool = False,
    progress_callback: Callable[[int, int], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> dict:
    """Parse an uploaded file and persist cash transactions."""
    _validate_file(uploaded_file)
    df = _read_file_to_dataframe(uploaded_file)
    return execute_transaction_upload(
        df,
        template_type=template_type,
        bank_account_id=bank_account_id,
        gl_account_override=gl_account_override,
        status_override=status_override,
        replace_by_ref_number=replace_by_ref_number,
        progress_callback=progress_callback,
        cancel_check=cancel_check,
    )


def execute_transaction_upload(
    df: pd.DataFrame,
    template_type: str,
    bank_account_id: str | None = None,
    gl_account_override: str | None = None,
    status_override: str | None = None,
    replace_by_ref_number: bool = False,
    progress_callback: Callable[[int, int], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> dict:
    """
    Parse and create/update cash transactions from a prepared DataFrame.

    Returns:
        {
            "created": count,
            "updated": count,
            "errors": [{"row": n, "errors": [...]}, ...],
            "total_rows": count,
            "warnings": [...],
        }
    """
    if template_type not in VALID_TEMPLATES:
        raise ValueError(f"Invalid template type. Must be one of: {', '.join(sorted(VALID_TEMPLATES))}")

    if df.empty:
        raise ValueError("File is empty.")

    # Check required columns for this template
    required_cols = TEMPLATE_REQUIRED_COLUMNS[template_type]
    missing_cols = required_cols - set(df.columns)
    if missing_cols:
        raise ValueError(f"Missing required columns: {', '.join(sorted(missing_cols))}")

    errors: list[dict] = []
    transactions_to_create: list[dict] = []
    warnings: list[str] = []
    students_by_id_number = _prefetch_students_by_id_number(df)
    staff_by_id_number = _prefetch_staff_by_id_number(df)

    # Pre-fetch lookups
    bank_accounts = {
        a.account_number.lower(): a for a in AccountingBankAccount.objects.filter(status="active")
    }
    transaction_types = {
        t.code.lower(): t for t in AccountingTransactionType.objects.filter(is_active=True)
    }
    ledger_accounts = {
        a.code.lower(): a for a in AccountingLedgerAccount.objects.filter(is_active=True)
    }

    # Get default payment method
    default_payment_method = (
        AccountingPaymentMethod.objects.filter(code__iexact="cash", is_active=True).first()
        or AccountingPaymentMethod.objects.filter(is_active=True).first()
    )
    if not default_payment_method:
        raise ValueError("No active payment method found. Create at least one payment method.")

    # Get default currency (base currency)
    default_currency = AccountingCurrency.objects.filter(is_base_currency=True).first()
    if not default_currency:
        raise ValueError("No base currency found. Create a base currency first.")

    # Resolve bank account override
    override_bank_account = None
    if bank_account_id:
        try:
            override_bank_account = AccountingBankAccount.objects.get(id=bank_account_id, status="active")
        except AccountingBankAccount.DoesNotExist:
            raise ValueError(f"Bank account {bank_account_id} not found or inactive.")

    # Resolve GL account override
    override_gl_account = None
    if gl_account_override:
        override_gl_account = ledger_accounts.get(gl_account_override.lower())
        if not override_gl_account:
            raise ValueError(f"GL account with code '{gl_account_override}' not found.")

    # Parse and validate rows
    for idx, row in df.iterrows():
        row_num = idx + 2  # 1-indexed + header row
        row_errors: list[str] = []

        transaction_date_str = _cell(row, "transaction_date")
        transaction_type_code = _cell(row, "transaction_type_code").lower()
        amount_str = _cell(row, "amount")
        description = _cell(row, "description")
        reference_number = _cell(row, "reference_number") or _generate_ref()
        payer_payee = _cell(row, "payer_payee")

        # Validate transaction date
        if not transaction_date_str:
            row_errors.append("transaction_date is required")
        else:
            try:
                transaction_date = pd.to_datetime(transaction_date_str).date()
            except Exception as e:
                row_errors.append(f"Invalid transaction_date format: {str(e)}")
                transaction_date = None

        # Resolve transaction type based on template
        tx_type = None
        if template_type == TEMPLATE_TUITION:
            # Auto-assign TUITION transaction type
            tx_type = _get_tuition_transaction_type(transaction_types)
            if not tx_type:
                row_errors.append("TUITION transaction type not found. Create a transaction type with code 'TUITION'")
        
        elif template_type == TEMPLATE_SALARY:
            # Auto-assign STAFF_* transaction type
            tx_type = _get_staff_transaction_type(transaction_types)
            if not tx_type:
                row_errors.append("No transaction type with 'STAFF_' prefix found. Create a transaction type with code starting with 'STAFF_'")
        
        else:  # TEMPLATE_GENERAL
            # Use transaction_type_code from file with fallback to GL override
            transaction_type_code = _cell(row, "transaction_type_code").lower()
            if not transaction_type_code:
                row_errors.append("transaction_type_code is required for general template")
            else:
                tx_type = _resolve_transaction_type_with_fallback(
                    transaction_types,
                    transaction_type_code,
                    override_gl_account,
                )
                if not tx_type:
                    row_errors.append(
                        f"Transaction type with code '{transaction_type_code}' not found and no active type is linked to selected GL override"
                    )

        # Validate amount
        if not amount_str:
            row_errors.append("amount is required")
        else:
            try:
                amount = Decimal(amount_str)
                if amount <= 0:
                    row_errors.append("amount must be greater than 0")
            except InvalidOperation:
                row_errors.append(f"Invalid amount: {amount_str}")
                amount = None

        # Validate description
        if not description:
            row_errors.append("description is required")

        # Validate template-specific fields with server-side checks
        if template_type == TEMPLATE_TUITION:
            student_id_number = _cell(row, "student_id_number")
            if not student_id_number:
                row_errors.append("student_id_number is required for tuition template")
            elif (
                not student_id_number.isdigit()
                or len(student_id_number) < 5
            ):
                row_errors.append(
                    f"Student ID '{student_id_number}' must be at least 5 digits"
                )
            elif student_id_number not in students_by_id_number:
                row_errors.append(
                    f"Student validation failed: Student with ID '{student_id_number}' not found"
                )

        elif template_type == TEMPLATE_SALARY:
            staff_id_number = _cell(row, "staff_id_number")
            if not staff_id_number:
                row_errors.append("staff_id_number is required for salary template")
            elif staff_id_number not in staff_by_id_number:
                row_errors.append(
                    f"Staff validation failed: Staff member with ID '{staff_id_number}' not found"
                )

        # Collect errors
        if row_errors:
            errors.append({"row": row_num, "errors": row_errors})
            continue

        # Resolve GL account for this row
        row_gl_account = override_gl_account  # Use override if provided

        # Use transaction type's default GL account if not overridden
        if not row_gl_account and tx_type:
            row_gl_account = tx_type.default_ledger_account

        # Resolve the student object up-front for tuition rows so we can
        # stamp the direct FK on the cash transaction. Validation above
        # already guarantees existence, so this lookup is cheap and safe.
        student_obj = None
        if template_type == TEMPLATE_TUITION:
            student_id_number = _cell(row, "student_id_number")
            if student_id_number:
                student_obj = students_by_id_number.get(student_id_number)

        # Prepare transaction data. The ``student`` reference is the
        # only "identity" carrier we need downstream — earlier versions
        # of this code captured a free-form ``id_number`` value which
        # was never read by the create/update paths below.
        parsed = {
            "transaction_date": transaction_date,
            "transaction_type": tx_type,
            "amount": amount,
            "description": description,
            "reference_number": reference_number,
            "payer_payee": payer_payee,
            "ledger_account": row_gl_account,
            "bank_account": override_bank_account,
            "template_type": template_type,
            "student": student_obj,
            "_row": row_num,
        }

        transactions_to_create.append(parsed)

    # Determine status to use
    status_to_use = AccountingCashTransaction.TransactionStatus.PENDING
    if status_override:
        status_lower = status_override.lower()
        if status_lower == "approved":
            status_to_use = AccountingCashTransaction.TransactionStatus.APPROVED
        elif status_lower == "rejected":
            status_to_use = AccountingCashTransaction.TransactionStatus.REJECTED
        elif status_lower == "pending":
            status_to_use = AccountingCashTransaction.TransactionStatus.PENDING

    default_bank_account = override_bank_account or _get_default_bank_account()
    if not default_bank_account:
        raise ValueError("No active bank account found. Create or activate a bank account first.")

    created_count, updated_count, recompute_pairs = _persist_transactions(
        transactions_to_create,
        template_type=template_type,
        default_bank_account=default_bank_account,
        default_payment_method=default_payment_method,
        default_currency=default_currency,
        status_to_use=status_to_use,
        replace_by_ref_number=replace_by_ref_number,
        errors=errors,
        progress_callback=progress_callback,
        cancel_check=cancel_check,
    )

    if recompute_pairs:
        _recompute_tuition_payments(recompute_pairs)

    return {
        "created": created_count,
        "updated": updated_count,
        "errors": errors,
        "total_rows": len(df),
        "warnings": warnings,
    }


def _persist_transactions(
    transactions_to_create: list[dict],
    *,
    template_type: str,
    default_bank_account,
    default_payment_method,
    default_currency,
    status_to_use: str,
    replace_by_ref_number: bool,
    errors: list[dict],
    progress_callback: Callable[[int, int], None] | None,
    cancel_check: Callable[[], bool] | None,
) -> tuple[int, int, list[tuple[Student, object]]]:
    created_count = 0
    updated_count = 0
    recompute_pairs: list[tuple[Student, object]] = []
    total = len(transactions_to_create)

    from accounting.signals import suppress_cash_tx_recompute

    with suppress_cash_tx_recompute():
        if replace_by_ref_number:
            for index, tx_data in enumerate(transactions_to_create, start=1):
                if cancel_check and cancel_check():
                    break
                row_num = tx_data.get("_row", 0)
                bank_account = tx_data["bank_account"] or default_bank_account
                try:
                    with transaction.atomic():
                        common_fields = _build_tx_fields(
                            tx_data,
                            bank_account=bank_account,
                            default_payment_method=default_payment_method,
                            default_currency=default_currency,
                            status_to_use=status_to_use,
                        )
                        _obj, created = AccountingCashTransaction.objects.update_or_create(
                            reference_number=tx_data["reference_number"],
                            defaults=common_fields,
                        )
                        if created:
                            created_count += 1
                        else:
                            updated_count += 1
                        recompute_pairs.extend(
                            _tuition_recompute_pair(
                                template_type,
                                tx_data,
                                status_to_use,
                            )
                        )
                except Exception as exc:
                    errors.append(
                        {
                            "row": row_num,
                            "errors": [f"Failed to save transaction: {exc}"],
                        }
                    )
                if progress_callback:
                    progress_callback(index, total)
        else:
            pending_objects: list[AccountingCashTransaction] = []
            processed = 0

            for tx_data in transactions_to_create:
                if cancel_check and cancel_check():
                    break
                bank_account = tx_data["bank_account"] or default_bank_account
                common_fields = _build_tx_fields(
                    tx_data,
                    bank_account=bank_account,
                    default_payment_method=default_payment_method,
                    default_currency=default_currency,
                    status_to_use=status_to_use,
                )
                pending_objects.append(
                    AccountingCashTransaction(
                        reference_number=tx_data["reference_number"],
                        **common_fields,
                    )
                )
                recompute_pairs.extend(
                    _tuition_recompute_pair(template_type, tx_data, status_to_use)
                )

                if len(pending_objects) >= BULK_CHUNK_SIZE:
                    created_count += _bulk_insert_chunk(
                        pending_objects,
                        errors,
                        processed + 1,
                    )
                    processed += len(pending_objects)
                    pending_objects = []
                    if progress_callback:
                        progress_callback(processed, total)

            if pending_objects and not (cancel_check and cancel_check()):
                created_count += _bulk_insert_chunk(
                    pending_objects,
                    errors,
                    processed + 1,
                )
                processed += len(pending_objects)
                if progress_callback:
                    progress_callback(processed, total)

    return created_count, updated_count, recompute_pairs


def _build_tx_fields(
    tx_data: dict,
    *,
    bank_account,
    default_payment_method,
    default_currency,
    status_to_use: str,
) -> dict:
    return {
        "bank_account": bank_account,
        "transaction_date": tx_data["transaction_date"],
        "transaction_type": tx_data["transaction_type"],
        "payment_method": default_payment_method,
        "ledger_account": tx_data["ledger_account"],
        "amount": tx_data["amount"],
        "currency": default_currency,
        "exchange_rate": Decimal("1"),
        "base_amount": tx_data["amount"],
        "payer_payee": tx_data["payer_payee"],
        "description": tx_data["description"],
        "status": status_to_use,
        "source_reference": f"{tx_data['template_type'].upper()}-UPLOAD",
        "student": tx_data.get("student"),
    }


def _tuition_recompute_pair(
    template_type: str,
    tx_data: dict,
    status_to_use: str,
) -> list[tuple[Student, object]]:
    student = tx_data.get("student")
    if (
        template_type == TEMPLATE_TUITION
        and student
        and status_to_use == AccountingCashTransaction.TransactionStatus.APPROVED
    ):
        return [(student, tx_data["transaction_date"])]
    return []


def _bulk_insert_chunk(
    pending_objects: list[AccountingCashTransaction],
    errors: list[dict],
    start_row: int,
) -> int:
    try:
        with transaction.atomic():
            AccountingCashTransaction.objects.bulk_create(
                pending_objects,
                batch_size=BULK_CHUNK_SIZE,
            )
        return len(pending_objects)
    except Exception as exc:
        errors.append(
            {
                "row": start_row,
                "errors": [
                    f"Failed to save transaction batch starting at row {start_row}: {exc}"
                ],
            }
        )
        return 0


def _recompute_tuition_payments(pairs: list[tuple[Student, object]]) -> None:
    """Refresh student bill paid_amount once per (student, academic year)."""
    from academics.models import AcademicYear
    from accounting.services.payment_allocation import recompute_student_year_payments

    seen: set[tuple] = set()
    for student, tx_date in pairs:
        academic_year = AcademicYear.objects.filter(
            start_date__lte=tx_date,
            end_date__gte=tx_date,
        ).first()
        if not academic_year:
            continue
        key = (student.pk, academic_year.pk)
        if key in seen:
            continue
        seen.add(key)
        recompute_student_year_payments(student, academic_year)


def _get_default_bank_account() -> AccountingBankAccount | None:
    """Get the first active bank account."""
    return AccountingBankAccount.objects.filter(status="active").first()
