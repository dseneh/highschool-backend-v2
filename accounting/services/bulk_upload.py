"""
Bulk upload services for accounting entities.

Supports:
- Ledger accounts (Chart of Accounts)
- Cash transactions
- Journal entries (grouped by reference)
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
    AccountingJournalEntry,
    AccountingJournalLine,
    AccountingLedgerAccount,
    AccountingPaymentMethod,
    AccountingTransactionType,
)

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
ALLOWED_EXTENSIONS = (".csv", ".xlsx", ".xls")


# ── Helpers ─────────────────────────────────────────────────────────


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


def _to_bool(val: str) -> bool:
    return val.lower() in {"true", "1", "yes", "on"} if val else False


def _generate_ref(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


# ── Ledger Accounts ────────────────────────────────────────────────

LEDGER_REQUIRED = {"code", "name", "account_type"}
LEDGER_OPTIONAL = {"category", "parent_code", "normal_balance", "is_header", "description"}
VALID_ACCOUNT_TYPES = {c[0] for c in AccountingLedgerAccount.AccountType.choices}
VALID_NORMAL_BALANCES = {"debit", "credit"}

# Maps account_type → default normal_balance
DEFAULT_NORMAL_BALANCE = {
    "asset": "debit",
    "expense": "debit",
    "liability": "credit",
    "equity": "credit",
    "income": "credit",
}


def bulk_upload_ledger_accounts(uploaded_file, *, replace_existing: bool = False) -> dict:
    """
    Parse and create ledger accounts from CSV/Excel.

    Expected columns: code, name, account_type, category (opt),
    parent_code (opt), normal_balance (opt), is_header (opt), description (opt)

    When replace_existing=True, rows whose `code` matches an existing account
    will update that account instead of erroring.

    Partial success: rows that fail validation are collected as errors;
    valid rows are still processed.
    """
    _validate_file(uploaded_file)
    df = _read_file_to_dataframe(uploaded_file)

    if df.empty:
        raise ValueError("File is empty.")

    missing_cols = LEDGER_REQUIRED - set(df.columns)
    if missing_cols:
        raise ValueError(f"Missing required columns: {', '.join(sorted(missing_cols))}")

    errors: list[dict] = []
    accounts_to_create: list[dict] = []
    accounts_to_update: list[dict] = []

    # Pre-fetch existing codes for uniqueness check and parent resolution
    existing_accounts = {
        a.code: a
        for a in AccountingLedgerAccount.objects.all()
    }
    existing_codes = set(existing_accounts.keys())
    seen_codes: set[str] = set()

    for idx, row in df.iterrows():
        row_num = idx + 2  # 1-indexed + header row
        code = _cell(row, "code")
        name = _cell(row, "name")
        account_type = _cell(row, "account_type").lower()
        category = _cell(row, "category")
        parent_code = _cell(row, "parent_code")
        normal_balance = _cell(row, "normal_balance").lower()
        is_header = _to_bool(_cell(row, "is_header"))
        description = _cell(row, "description")

        row_errors: list[str] = []

        if not code:
            row_errors.append("Code is required")
        elif code in seen_codes:
            row_errors.append(f"Duplicate code '{code}' in file")
        elif code in existing_codes and not replace_existing:
            row_errors.append(f"Code '{code}' already exists")

        if not name:
            row_errors.append("Name is required")

        if not account_type:
            row_errors.append("Account type is required")
        elif account_type not in VALID_ACCOUNT_TYPES:
            row_errors.append(f"Invalid account_type '{account_type}'. Must be one of: {', '.join(sorted(VALID_ACCOUNT_TYPES))}")

        if normal_balance and normal_balance not in VALID_NORMAL_BALANCES:
            row_errors.append(f"Invalid normal_balance '{normal_balance}'. Must be 'debit' or 'credit'")

        if row_errors:
            errors.append({"row": row_num, "errors": row_errors})
            continue

        seen_codes.add(code)
        parsed = {
            "code": code,
            "name": name,
            "account_type": account_type,
            "category": category,
            "parent_code": parent_code,
            "normal_balance": normal_balance or DEFAULT_NORMAL_BALANCE.get(account_type, "debit"),
            "is_header": is_header,
            "description": description or None,
        }

        if code in existing_codes and replace_existing:
            accounts_to_update.append(parsed)
        else:
            accounts_to_create.append(parsed)

    with transaction.atomic():
        code_to_instance: dict[str, AccountingLedgerAccount] = {}

        # Update existing accounts
        for acc_data in accounts_to_update:
            instance = existing_accounts[acc_data["code"]]
            instance.name = acc_data["name"]
            instance.account_type = acc_data["account_type"]
            instance.category = acc_data["category"]
            instance.normal_balance = acc_data["normal_balance"]
            instance.is_header = acc_data["is_header"]
            instance.description = acc_data["description"]
            instance.save()
            code_to_instance[acc_data["code"]] = instance

        # Create new accounts
        for acc_data in accounts_to_create:
            instance = AccountingLedgerAccount.objects.create(
                code=acc_data["code"],
                name=acc_data["name"],
                account_type=acc_data["account_type"],
                category=acc_data["category"],
                normal_balance=acc_data["normal_balance"],
                is_header=acc_data["is_header"],
                description=acc_data["description"],
            )
            code_to_instance[acc_data["code"]] = instance

        # Resolve parent_code references
        all_codes_map = {
            a.code: a
            for a in AccountingLedgerAccount.objects.all()
        }
        parent_updates = []
        for acc_data in accounts_to_create + accounts_to_update:
            parent_code = acc_data["parent_code"]
            if parent_code:
                parent = all_codes_map.get(parent_code)
                if parent:
                    instance = code_to_instance[acc_data["code"]]
                    instance.parent_account = parent
                    parent_updates.append(instance)
                else:
                    # Surface as a row-level warning rather than aborting the whole batch
                    errors.append({
                        "row": 0,
                        "errors": [f"Row with code '{acc_data['code']}': parent_code '{parent_code}' not found — account was created without a parent"],
                    })

        if parent_updates:
            AccountingLedgerAccount.objects.bulk_update(parent_updates, ["parent_account"])

    return {
        "created": len(accounts_to_create),
        "updated": len(accounts_to_update),
        "errors": errors,
        "total_rows": len(df),
    }


# ── Cash Transactions ──────────────────────────────────────────────

CASH_TX_REQUIRED = {"transaction_date", "description", "amount", "bank_account", "transaction_type", "payment_method"}
CASH_TX_OPTIONAL = {"reference_number", "payer_payee", "status", "ledger_account"}


def bulk_upload_cash_transactions(
    uploaded_file,
    *,
    replace_existing: bool = False,
    bank_account_id: str | None = None,
    override_status: str | None = None,
    override_transaction_type_id: str | None = None,
) -> dict:
    """
    Parse and create cash transactions from CSV/Excel.

    Expected columns: transaction_date, description, amount, bank_account (account number),
    transaction_type (name or code), payment_method (name or code),
    reference_number (opt), payer_payee (opt), status (opt, default: pending),
    ledger_account (opt, code)

    When replace_existing=True, rows whose `reference_number` matches an existing
    transaction will update that transaction instead of erroring.

    When bank_account_id is provided, it overrides the bank_account column for all rows.
    When override_status is provided, it overrides the status column for all rows.
    When override_transaction_type_id is provided, it overrides the transaction_type column for all rows.
    """
    _validate_file(uploaded_file)
    df = _read_file_to_dataframe(uploaded_file)

    if df.empty:
        raise ValueError("File is empty.")

    # Determine which required columns can be omitted due to global overrides
    skippable = set()
    if bank_account_id:
        skippable.add("bank_account")
    if override_transaction_type_id:
        skippable.add("transaction_type")
    required_cols = CASH_TX_REQUIRED - skippable
    missing_cols = required_cols - set(df.columns)
    if missing_cols:
        raise ValueError(f"Missing required columns: {', '.join(sorted(missing_cols))}")

    errors: list[dict] = []
    transactions_to_create: list[dict] = []

    # Pre-fetch lookups — bank accounts matched by account_number only
    bank_accounts = {
        a.account_number.lower(): a for a in AccountingBankAccount.objects.filter(status="active")
    }

    # Pre-resolve bank account override if provided
    override_bank_account = None
    if bank_account_id:
        try:
            override_bank_account = AccountingBankAccount.objects.get(id=bank_account_id, status="active")
        except AccountingBankAccount.DoesNotExist:
            raise ValueError(f"Bank account with id '{bank_account_id}' not found or is not active.")

    # Validate override_status if provided
    valid_statuses = {"pending", "approved", "rejected"}
    if override_status and override_status not in valid_statuses:
        raise ValueError(f"Invalid override status '{override_status}'. Must be: {', '.join(sorted(valid_statuses))}")

    # Pre-resolve transaction type override if provided
    override_transaction_type = None
    if override_transaction_type_id:
        try:
            override_transaction_type = AccountingTransactionType.objects.get(
                id=override_transaction_type_id, is_active=True
            )
        except AccountingTransactionType.DoesNotExist:
            raise ValueError(f"Transaction type with id '{override_transaction_type_id}' not found or is inactive.")

    tx_types = {
        **{t.name.lower(): t for t in AccountingTransactionType.objects.filter(is_active=True)},
        **{t.code.lower(): t for t in AccountingTransactionType.objects.filter(is_active=True)},
    }
    pay_methods = {
        **{m.name.lower(): m for m in AccountingPaymentMethod.objects.filter(is_active=True)},
        **{m.code.lower(): m for m in AccountingPaymentMethod.objects.filter(is_active=True)},
    }
    ledger_map = {
        a.code.lower(): a for a in AccountingLedgerAccount.objects.filter(is_active=True)
    }
    existing_tx_by_ref = {
        tx.reference_number: tx
        for tx in AccountingCashTransaction.objects.all()
        if tx.reference_number
    }
    existing_refs = set(existing_tx_by_ref.keys())
    seen_refs: set[str] = set()

    # Determine default currency (base currency)
    base_currency = AccountingCurrency.objects.filter(is_base_currency=True).first()
    if not base_currency:
        base_currency = AccountingCurrency.objects.first()
    if not base_currency:
        raise ValueError("No currencies configured. Please set up at least one currency first.")

    valid_statuses = {"pending", "approved", "rejected"}

    for idx, row in df.iterrows():
        row_num = idx + 2
        row_errors: list[str] = []

        date_str = _cell(row, "transaction_date")
        description = _cell(row, "description")
        amount_str = _cell(row, "amount")
        bank_acct_str = _cell(row, "bank_account").lower()
        tx_type_str = _cell(row, "transaction_type").lower()
        pay_method_str = _cell(row, "payment_method").lower()
        ref = _cell(row, "reference_number")
        payer_payee = _cell(row, "payer_payee")
        status_str = (override_status or _cell(row, "status")).lower() or "pending"
        ledger_code = _cell(row, "ledger_account").lower()

        # Validate date
        tx_date = None
        if not date_str:
            row_errors.append("Transaction date is required")
        else:
            for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d"):
                try:
                    tx_date = datetime.strptime(date_str, fmt).date()
                    break
                except ValueError:
                    continue
            if tx_date is None:
                row_errors.append(f"Invalid date format '{date_str}'. Use YYYY-MM-DD")

        if not description:
            row_errors.append("Description is required")

        # Validate amount
        amount = None
        if not amount_str:
            row_errors.append("Amount is required")
        else:
            try:
                amount = Decimal(amount_str.replace(",", ""))
                if amount <= 0:
                    row_errors.append("Amount must be greater than 0")
            except InvalidOperation:
                row_errors.append(f"Invalid amount '{amount_str}'")

        # Validate lookups
        bank_account = override_bank_account or bank_accounts.get(bank_acct_str)
        if not bank_account:
            row_errors.append(f"Bank account number '{_cell(row, 'bank_account')}' not found")

        tx_type = override_transaction_type or tx_types.get(tx_type_str)
        if not tx_type:
            row_errors.append(f"Transaction type '{_cell(row, 'transaction_type')}' not found")

        pay_method = pay_methods.get(pay_method_str)
        if not pay_method:
            row_errors.append(f"Payment method '{_cell(row, 'payment_method')}' not found")

        if status_str not in valid_statuses:
            row_errors.append(f"Invalid status '{status_str}'. Must be: {', '.join(sorted(valid_statuses))}")

        ledger_account = None
        if ledger_code:
            ledger_account = ledger_map.get(ledger_code)
            if not ledger_account:
                row_errors.append(f"Ledger account '{_cell(row, 'ledger_account')}' not found")

        # Generate or validate reference
        if not ref:
            ref = _generate_ref("BLK")
        if ref in seen_refs:
            row_errors.append(f"Duplicate reference number '{ref}' in file")
        elif ref in existing_refs and not replace_existing:
            row_errors.append(f"Reference number '{ref}' already exists")

        if row_errors:
            errors.append({"row": row_num, "errors": row_errors})
            continue

        seen_refs.add(ref)
        parsed = {
            "bank_account": bank_account,
            "transaction_date": tx_date,
            "reference_number": ref,
            "transaction_type": tx_type,
            "payment_method": pay_method,
            "ledger_account": ledger_account,
            "amount": amount,
            "currency": bank_account.currency if bank_account else base_currency,
            "exchange_rate": Decimal("1"),
            "base_amount": amount,
            "payer_payee": payer_payee,
            "description": description,
            "status": status_str,
            "_is_update": ref in existing_refs and replace_existing,
        }
        transactions_to_create.append(parsed)

    with transaction.atomic():
        created_count = 0
        updated_count = 0
        for tx_data in transactions_to_create:
            is_update = tx_data.pop("_is_update", False)
            if is_update:
                instance = existing_tx_by_ref[tx_data["reference_number"]]
                for field, value in tx_data.items():
                    setattr(instance, field, value)
                instance.save()
                updated_count += 1
            else:
                AccountingCashTransaction.objects.create(**tx_data)
                created_count += 1

    return {
        "created": created_count,
        "updated": updated_count,
        "errors": errors,
        "total_rows": len(df),
    }


# ── Journal Entries ────────────────────────────────────────────────

JE_REQUIRED = {"posting_date", "reference", "description", "account_code", "debit_amount", "credit_amount"}


def bulk_upload_journal_entries(uploaded_file, *, replace_existing: bool = False) -> dict:
    """
    Parse and create journal entries from CSV/Excel.

    Rows with the same `reference` are grouped into a single journal entry.
    Each row becomes one journal line.

    Expected columns: posting_date, reference, description, account_code,
    debit_amount, credit_amount

    When replace_existing=True, entries whose `reference` matches an existing
    draft journal entry will delete the old entry and re-create it.
    """
    _validate_file(uploaded_file)
    df = _read_file_to_dataframe(uploaded_file)

    if df.empty:
        raise ValueError("File is empty.")

    missing_cols = JE_REQUIRED - set(df.columns)
    if missing_cols:
        raise ValueError(f"Missing required columns: {', '.join(sorted(missing_cols))}")

    errors: list[dict] = []

    # Pre-fetch ledger accounts by code
    ledger_map = {
        a.code.lower(): a
        for a in AccountingLedgerAccount.objects.filter(is_active=True, is_header=False)
    }
    base_currency = AccountingCurrency.objects.filter(is_base_currency=True).first()
    if not base_currency:
        base_currency = AccountingCurrency.objects.first()
    if not base_currency:
        raise ValueError("No currencies configured.")

    # Group rows by reference
    from collections import OrderedDict
    groups: OrderedDict[str, list[dict]] = OrderedDict()

    for idx, row in df.iterrows():
        row_num = idx + 2
        row_errors: list[str] = []

        date_str = _cell(row, "posting_date")
        reference = _cell(row, "reference")
        description = _cell(row, "description")
        account_code = _cell(row, "account_code").lower()
        debit_str = _cell(row, "debit_amount")
        credit_str = _cell(row, "credit_amount")

        # Validate date
        posting_date = None
        if not date_str:
            row_errors.append("Posting date is required")
        else:
            for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d"):
                try:
                    posting_date = datetime.strptime(date_str, fmt).date()
                    break
                except ValueError:
                    continue
            if posting_date is None:
                row_errors.append(f"Invalid date '{date_str}'. Use YYYY-MM-DD")

        if not reference:
            row_errors.append("Reference is required")

        if not description:
            row_errors.append("Description is required")

        # Validate account
        ledger_account = ledger_map.get(account_code)
        if not account_code:
            row_errors.append("Account code is required")
        elif not ledger_account:
            row_errors.append(f"Account code '{_cell(row, 'account_code')}' not found or is a header account")

        # Validate amounts
        debit = Decimal("0")
        credit = Decimal("0")
        try:
            if debit_str:
                debit = Decimal(debit_str.replace(",", ""))
                if debit < 0:
                    row_errors.append("Debit amount cannot be negative")
        except InvalidOperation:
            row_errors.append(f"Invalid debit amount '{debit_str}'")

        try:
            if credit_str:
                credit = Decimal(credit_str.replace(",", ""))
                if credit < 0:
                    row_errors.append("Credit amount cannot be negative")
        except InvalidOperation:
            row_errors.append(f"Invalid credit amount '{credit_str}'")

        if debit == 0 and credit == 0:
            row_errors.append("Either debit or credit must be non-zero")

        if debit > 0 and credit > 0:
            row_errors.append("A line cannot have both debit and credit amounts")

        if row_errors:
            errors.append({"row": row_num, "errors": row_errors})
            continue

        if reference not in groups:
            groups[reference] = []

        groups[reference].append({
            "posting_date": posting_date,
            "description": description,
            "ledger_account": ledger_account,
            "debit_amount": debit,
            "credit_amount": credit,
        })

    # Per-group validation: existing refs, balance, draft status
    bad_refs: set[str] = set()

    if not replace_existing:
        existing_refs_found = set(
            AccountingJournalEntry.objects.filter(
                reference_number__in=list(groups.keys()),
            ).values_list("reference_number", flat=True)
        )
        for ref in sorted(existing_refs_found):
            errors.append({"row": 0, "errors": [f"Entry reference '{ref}' already exists"]})
            bad_refs.add(ref)

    # Balance check per group
    for ref, lines in groups.items():
        if ref in bad_refs:
            continue
        total_debit = sum(l["debit_amount"] for l in lines)
        total_credit = sum(l["credit_amount"] for l in lines)
        if total_debit != total_credit:
            errors.append({"row": 0, "errors": [f"Entry '{ref}': debits ({total_debit}) != credits ({total_credit})"]})
            bad_refs.add(ref)

    # Pre-fetch existing entries for upsert
    existing_entries_by_ref: dict[str, AccountingJournalEntry] = {}
    if replace_existing and groups:
        for entry in AccountingJournalEntry.objects.filter(
            reference_number__in=[r for r in groups.keys() if r not in bad_refs],
        ):
            existing_entries_by_ref[entry.reference_number] = entry

        # Only allow replacing draft entries
        for ref, entry in existing_entries_by_ref.items():
            if entry.status != AccountingJournalEntry.EntryStatus.DRAFT:
                errors.append({"row": 0, "errors": [
                    f"Entry '{ref}' is {entry.status} and cannot be replaced (only draft entries can be replaced)"
                ]})
                bad_refs.add(ref)

    # Remove groups with any errors before committing
    valid_groups = {ref: lines for ref, lines in groups.items() if ref not in bad_refs}

    # Create / replace valid journal entries atomically
    from accounting.services.posting import _resolve_academic_year

    with transaction.atomic():
        created_count = 0
        updated_count = 0

        for ref, lines in valid_groups.items():
            posting_date = lines[0]["posting_date"]
            description = lines[0]["description"]
            academic_year = _resolve_academic_year(posting_date)

            # If replacing, delete old entry (cascades to lines)
            if ref in existing_entries_by_ref:
                existing_entries_by_ref[ref].delete()
                updated_count += 1
            else:
                created_count += 1

            entry = AccountingJournalEntry.objects.create(
                posting_date=posting_date,
                description=description,
                source="manual",
                status="draft",
                academic_year=academic_year,
            )

            for line_data in lines:
                AccountingJournalLine.objects.create(
                    journal_entry=entry,
                    ledger_account=line_data["ledger_account"],
                    debit_amount=line_data["debit_amount"],
                    credit_amount=line_data["credit_amount"],
                    currency=base_currency,
                    exchange_rate=Decimal("1"),
                    description=line_data["description"],
                )

    return {
        "created": created_count,
        "updated": updated_count,
        "errors": errors,
        "total_rows": len(df),
    }
