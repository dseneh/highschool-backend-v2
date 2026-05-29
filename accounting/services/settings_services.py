"""Resolve tenant accounting settings and default ledger accounts."""

from __future__ import annotations

from django.core.exceptions import ValidationError

from accounting.models import (
    AccountingBankAccount,
    AccountingLedgerAccount,
    AccountingPaymentMethod,
    AccountingSettings,
    AccountingTransactionType,
)

GL_MAPPINGS_PATH = "Accounting → Cash Flow Settings → GL Mappings"
BANK_ACCOUNTS_PATH = "Accounting → Bank Accounts"
CHART_OF_ACCOUNTS_PATH = "Accounting → Chart of Accounts"

DEFAULT_LEDGER_CODES = {
    "transfer_in": "1901",
    "transfer_out": "1901",
    "salary_expense": "5001",
    "payroll_tax_payable": "2002",
    "payroll_deductions_payable": "2003",
}

GL_ACCOUNT_META = {
    "transfer_in": {
        "label": "Transfer in",
        "code": "1901",
        "name": "Transfer Clearing",
        "type": "asset",
        "setting_field": "transfer in",
    },
    "transfer_out": {
        "label": "Transfer out",
        "code": "1901",
        "name": "Transfer Clearing",
        "type": "asset",
        "setting_field": "transfer out",
    },
    "salary_expense": {
        "label": "Salary expense",
        "code": "5001",
        "name": "Salary Expense",
        "type": "expense",
        "setting_field": "salary expense",
    },
    "payroll_tax_payable": {
        "label": "Payroll tax payable",
        "code": "2002",
        "name": "Tax Payable",
        "type": "liability",
        "setting_field": "payroll tax payable",
    },
    "payroll_deductions_payable": {
        "label": "Payroll deductions payable",
        "code": "2003",
        "name": "Salaries Payable",
        "type": "liability",
        "setting_field": "payroll deductions payable",
    },
}


def validation_error_detail(exc: ValidationError) -> str:
    """Return a single user-facing message from a Django ValidationError."""
    if hasattr(exc, "message_dict") and exc.message_dict:
        first_key = next(iter(exc.message_dict))
        value = exc.message_dict[first_key]
        if isinstance(value, list) and value:
            return str(value[0])
        return str(value)
    if hasattr(exc, "messages") and exc.messages:
        return str(exc.messages[0])
    return str(exc)


def missing_gl_account_message(key: str) -> str:
    meta = GL_ACCOUNT_META[key]
    return (
        f"{meta['label']} GL account is not configured. "
        f"Open {GL_MAPPINGS_PATH} and set {meta['setting_field']}, "
        f"or create chart account {meta['code']} ({meta['name']}, {meta['type']}) "
        f"via {CHART_OF_ACCOUNTS_PATH} or Load Default Chart."
    )


def inactive_gl_account_message(key: str, *, code: str, name: str) -> str:
    meta = GL_ACCOUNT_META[key]
    return (
        f"The configured {meta['label'].lower()} account ({code} — {name}) is inactive. "
        f"Reactivate it in {CHART_OF_ACCOUNTS_PATH}, or choose another {meta['type']} account "
        f"under {GL_MAPPINGS_PATH}."
    )


def invalid_gl_account_type_message(key: str, *, expected_type: str) -> str:
    meta = GL_ACCOUNT_META[key]
    return (
        f"The configured {meta['label'].lower()} account must be a {expected_type} account. "
        f"Choose a valid {expected_type} account under {GL_MAPPINGS_PATH}."
    )


def header_gl_account_message(key: str) -> str:
    meta = GL_ACCOUNT_META[key]
    return (
        f"The configured {meta['label'].lower()} account cannot be a header account. "
        f"Choose a posting account (not a group/header) under {GL_MAPPINGS_PATH}."
    )


def bank_accounts_missing_ledger_message(
    bank_accounts: list[AccountingBankAccount],
) -> str:
    names = ", ".join(account.account_name for account in bank_accounts)
    if len(bank_accounts) == 1:
        return (
            f'Bank account "{names}" is not linked to a ledger account. '
            f"Open {BANK_ACCOUNTS_PATH}, edit the account, and link it to a chart of accounts entry."
        )
    return (
        f'Bank accounts "{names}" are not linked to ledger accounts. '
        f"Open {BANK_ACCOUNTS_PATH}, edit each account, and link it to a chart of accounts entry."
    )


def get_tenant_accounting_settings(*, user=None) -> AccountingSettings:
    settings = (
        AccountingSettings.objects.select_related(
            "transfer_in_account",
            "transfer_out_account",
            "salary_expense_account",
            "payroll_tax_payable_account",
            "payroll_deductions_payable_account",
        )
        .order_by("created_at")
        .first()
    )
    if settings is not None:
        return settings

    return AccountingSettings.objects.create(
        created_by=user,
        updated_by=user,
    )


def _ledger_by_code(code: str) -> AccountingLedgerAccount | None:
    return AccountingLedgerAccount.objects.filter(code=code, is_active=True).first()


def _resolve_configured_gl_account(
    *,
    key: str,
    configured_account: AccountingLedgerAccount | None,
) -> AccountingLedgerAccount:
    meta = GL_ACCOUNT_META[key]
    expected_type = meta["type"]
    account = configured_account

    if account is not None and not account.is_active:
        raise ValidationError(
            inactive_gl_account_message(
                key,
                code=account.code,
                name=account.name,
            )
        )

    if account is None:
        account = _ledger_by_code(DEFAULT_LEDGER_CODES[key])

    if account is None:
        raise ValidationError(missing_gl_account_message(key))

    if account.account_type != expected_type:
        raise ValidationError(invalid_gl_account_type_message(key, expected_type=expected_type))

    if account.is_header:
        raise ValidationError(header_gl_account_message(key))

    return account


def resolve_transfer_in_account() -> AccountingLedgerAccount:
    settings = get_tenant_accounting_settings()
    return _resolve_configured_gl_account(
        key="transfer_in",
        configured_account=settings.transfer_in_account,
    )


def resolve_transfer_out_account() -> AccountingLedgerAccount:
    settings = get_tenant_accounting_settings()
    return _resolve_configured_gl_account(
        key="transfer_out",
        configured_account=settings.transfer_out_account,
    )


def resolve_transfer_clearing_account() -> AccountingLedgerAccount:
    """Backward-compatible alias; prefer resolve_transfer_in/out_account."""
    return resolve_transfer_in_account()


def ensure_system_payment_method() -> AccountingPaymentMethod:
    payment_method = (
        AccountingPaymentMethod.objects.filter(code__iexact="system", is_active=True).first()
        or AccountingPaymentMethod.objects.filter(name__iexact="system", is_active=True).first()
    )
    if payment_method is None:
        inactive = (
            AccountingPaymentMethod.objects.filter(code__iexact="system").first()
            or AccountingPaymentMethod.objects.filter(name__iexact="system").first()
        )
        if inactive is not None:
            inactive.is_active = True
            inactive.save(update_fields=["is_active", "updated_at"])
            return inactive

        return AccountingPaymentMethod.objects.create(
            code="SYSTEM",
            name="System",
            description="Internal system-generated transactions such as account transfers.",
            is_active=True,
        )
    return payment_method


def ensure_transfer_transaction_types() -> tuple[AccountingTransactionType, AccountingTransactionType]:
    """Ensure transfer cash transaction types exist and point at the configured GL accounts."""
    transfer_out_ledger = resolve_transfer_out_account()
    transfer_in_ledger = resolve_transfer_in_account()

    def ensure(
        code: str,
        name: str,
        description: str,
        ledger_account: AccountingLedgerAccount,
    ) -> AccountingTransactionType:
        tx_type = AccountingTransactionType.objects.filter(code__iexact=code).first()
        if tx_type is None:
            return AccountingTransactionType.objects.create(
                code=code,
                name=name,
                transaction_category="transfer",
                description=description,
                default_ledger_account=ledger_account,
                is_system_managed=True,
                is_active=True,
            )

        updates: list[str] = []
        if tx_type.transaction_category != "transfer":
            tx_type.transaction_category = "transfer"
            updates.append("transaction_category")
        if tx_type.default_ledger_account_id != ledger_account.id:
            tx_type.default_ledger_account = ledger_account
            updates.append("default_ledger_account")
        if not tx_type.is_active:
            tx_type.is_active = True
            updates.append("is_active")
        if updates:
            updates.append("updated_at")
            tx_type.save(update_fields=updates)
        return tx_type

    transfer_out = ensure(
        "TRANSFER_OUT",
        "Transfer Out",
        "Funds sent out of a bank/cash account",
        transfer_out_ledger,
    )
    transfer_in = ensure(
        "TRANSFER_IN",
        "Transfer In",
        "Funds received into a bank/cash account",
        transfer_in_ledger,
    )
    return transfer_out, transfer_in


def resolve_payroll_ledger_accounts() -> dict[str, AccountingLedgerAccount]:
    settings = get_tenant_accounting_settings()

    return {
        "salary_expense": _resolve_configured_gl_account(
            key="salary_expense",
            configured_account=settings.salary_expense_account,
        ),
        "tax_payable": _resolve_configured_gl_account(
            key="payroll_tax_payable",
            configured_account=settings.payroll_tax_payable_account,
        ),
        "deductions_payable": _resolve_configured_gl_account(
            key="payroll_deductions_payable",
            configured_account=settings.payroll_deductions_payable_account,
        ),
    }
