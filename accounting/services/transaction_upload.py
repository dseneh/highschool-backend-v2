"""
Template-based transaction upload service.

Supports three templates:
1. Student Tuition Payment (requires student id_number)
2. Staff Salaries (requires staff id_number)
3. General Transactions (no ID number required)

All templates require transaction_type code in the file.
User can override GL account on preview screen.
"""

import io
import uuid
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


MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
ALLOWED_EXTENSIONS = (".csv", ".xlsx", ".xls")

# Template types
TEMPLATE_TUITION = "tuition"
TEMPLATE_SALARY = "salary"
TEMPLATE_GENERAL = "general"

VALID_TEMPLATES = {TEMPLATE_TUITION, TEMPLATE_SALARY, TEMPLATE_GENERAL}

# Template-specific required columns
TEMPLATE_REQUIRED_COLUMNS = {
    TEMPLATE_TUITION: {"transaction_date", "transaction_type_code", "id_number", "amount", "description"},
    TEMPLATE_SALARY: {"transaction_date", "transaction_type_code", "id_number", "amount", "description"},
    TEMPLATE_GENERAL: {"transaction_date", "transaction_type_code", "amount", "description"},
}

# Optional columns for all templates
OPTIONAL_COLUMNS = {"reference_number", "payer_payee", "gl_account_code"}


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


def upload_transactions(
    uploaded_file,
    template_type: str,
    bank_account_id: str | None = None,
    gl_account_override: str | None = None,
) -> dict:
    """
    Parse and create cash transactions from CSV/Excel using template schema.

    Args:
        uploaded_file: Uploaded file object
        template_type: One of "tuition", "salary", or "general"
        bank_account_id: Optional override bank account ID
        gl_account_override: Optional override GL account code (applies to all rows)

    Returns:
        {
            "created": count,
            "errors": [{"row": n, "errors": [...]}, ...],
            "total_rows": count,
            "warnings": [...],
        }
    """
    _validate_file(uploaded_file)

    if template_type not in VALID_TEMPLATES:
        raise ValueError(f"Invalid template type. Must be one of: {', '.join(sorted(VALID_TEMPLATES))}")

    df = _read_file_to_dataframe(uploaded_file)

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
        gl_account_code = _cell(row, "gl_account_code").lower()

        # Validate transaction date
        if not transaction_date_str:
            row_errors.append("transaction_date is required")
        else:
            try:
                transaction_date = pd.to_datetime(transaction_date_str).date()
            except Exception as e:
                row_errors.append(f"Invalid transaction_date format: {str(e)}")
                transaction_date = None

        # Validate transaction type code
        if not transaction_type_code:
            row_errors.append("transaction_type_code is required")
        else:
            tx_type = transaction_types.get(transaction_type_code)
            if not tx_type:
                row_errors.append(f"Transaction type with code '{transaction_type_code}' not found")
                tx_type = None

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

        # Validate template-specific fields
        if template_type == TEMPLATE_TUITION:
            student_id_number = _cell(row, "id_number")
            if not student_id_number:
                row_errors.append("id_number (student) is required for tuition template")
            else:
                # Just validate format - don't FK lookup to students table yet
                if not student_id_number.isdigit() or len(student_id_number) != 6:
                    warnings.append(f"Row {row_num}: Student ID '{student_id_number}' may be invalid (expected 6 digits)")

        elif template_type == TEMPLATE_SALARY:
            staff_id_number = _cell(row, "id_number")
            if not staff_id_number:
                row_errors.append("id_number (staff) is required for salary template")
            # Staff ID can be various formats, just validate it's not empty

        # Collect errors
        if row_errors:
            errors.append({"row": row_num, "errors": row_errors})
            continue

        # Resolve GL account for this row
        row_gl_account = override_gl_account  # Use override if provided
        if not row_gl_account and gl_account_code:
            row_gl_account = ledger_accounts.get(gl_account_code)
            if not row_gl_account:
                errors.append({"row": row_num, "errors": [f"GL account with code '{gl_account_code}' not found"]})
                continue

        # Use transaction type's default GL account if not overridden
        if not row_gl_account and tx_type:
            row_gl_account = tx_type.default_ledger_account

        # Prepare transaction data
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
            "id_number": _cell(row, "id_number") if template_type != TEMPLATE_GENERAL else None,
        }

        transactions_to_create.append(parsed)

    # Create transactions atomically
    with transaction.atomic():
        created_count = 0

        for tx_data in transactions_to_create:
            bank_account = tx_data["bank_account"] or _get_default_bank_account()
            if not bank_account:
                errors.append({
                    "row": 0,
                    "errors": ["No active bank account found. Create or activate a bank account first."],
                })
                continue

            try:
                AccountingCashTransaction.objects.create(
                    bank_account=bank_account,
                    transaction_date=tx_data["transaction_date"],
                    reference_number=tx_data["reference_number"],
                    transaction_type=tx_data["transaction_type"],
                    payment_method=default_payment_method,
                    ledger_account=tx_data["ledger_account"],
                    amount=tx_data["amount"],
                    currency=default_currency,
                    exchange_rate=Decimal("1"),
                    base_amount=tx_data["amount"],
                    payer_payee=tx_data["payer_payee"],
                    description=tx_data["description"],
                    status=AccountingCashTransaction.TransactionStatus.PENDING,
                    source_reference=f"{tx_data['template_type'].upper()}-UPLOAD",
                )
                created_count += 1
            except Exception as e:
                errors.append({"row": 0, "errors": [f"Failed to create transaction: {str(e)}"]})

    return {
        "created": created_count,
        "errors": errors,
        "total_rows": len(df),
        "warnings": warnings,
    }


def _get_default_bank_account() -> AccountingBankAccount | None:
    """Get the first active bank account."""
    return AccountingBankAccount.objects.filter(status="active").first()
