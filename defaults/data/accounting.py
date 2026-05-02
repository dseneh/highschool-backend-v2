"""Default seed data for the `accounting` module.

Seeded at tenant creation so every new tenant has a working chart of accounts,
currency, payment methods, transaction types and fee item catalog.
"""

# Base currency for the tenant. Mirrors `defaults/data/currency.py` but is
# specific to the accounting (double-entry) module.
accounting_currency = {
    "name": "Liberian Dollar",
    "code": "LRD",
    "symbol": "L$",
    "is_base_currency": True,
    "decimal_places": 2,
}


# Standard chart of accounts.
#
# Layout follows a parent/child numbering scheme so reports group naturally:
#   - Parents are 3-digit header codes (e.g. `100` Current Assets).
#   - Children prefix the parent code with one extra digit (e.g. `1001` Cash on Hand).
#
# `is_header=True` marks a non-postable parent. `is_system_managed=True` accounts
# are protected from edits/deletion in the UI — the platform creates and
# maintains them (e.g. transfer clearing, tuition income).
accounting_ledger_accounts = [
    # ---- Assets (1xx) ----
    {"code": "100", "name": "Current Assets", "account_type": "asset", "category": "Current Asset", "normal_balance": "debit", "is_header": True},
    {"code": "1001", "name": "Cash on Hand", "account_type": "asset", "category": "Current Asset", "normal_balance": "debit", "parent_code": "100"},
    {"code": "1002", "name": "Bank", "account_type": "asset", "category": "Current Asset", "normal_balance": "debit", "parent_code": "100"},
    {"code": "1003", "name": "Accounts Receivable", "account_type": "asset", "category": "Current Asset", "normal_balance": "debit", "parent_code": "100"},
    {"code": "1004", "name": "Student Receivables", "account_type": "asset", "category": "Current Asset", "normal_balance": "debit", "parent_code": "100"},

    {"code": "190", "name": "Clearing Accounts", "account_type": "asset", "category": "Clearing", "normal_balance": "debit", "is_header": True},
    {
        "code": "1901",
        "name": "Transfer Clearing",
        "account_type": "asset",
        "category": "Clearing",
        "normal_balance": "debit",
        "parent_code": "190",
        "is_system_managed": True,
        "description": "System-managed clearing account for inter-account transfers.",
    },

    # ---- Liabilities (2xx) ----
    {"code": "200", "name": "Current Liabilities", "account_type": "liability", "category": "Current Liability", "normal_balance": "credit", "is_header": True},
    {"code": "2001", "name": "Accounts Payable", "account_type": "liability", "category": "Current Liability", "normal_balance": "credit", "parent_code": "200"},
    {"code": "2002", "name": "Tax Payable", "account_type": "liability", "category": "Current Liability", "normal_balance": "credit", "parent_code": "200"},
    {"code": "2003", "name": "Salaries Payable", "account_type": "liability", "category": "Current Liability", "normal_balance": "credit", "parent_code": "200"},
    {"code": "2004", "name": "Unearned Tuition", "account_type": "liability", "category": "Current Liability", "normal_balance": "credit", "parent_code": "200"},

    # ---- Equity (3xx) ----
    {"code": "300", "name": "Equity", "account_type": "equity", "category": "Equity", "normal_balance": "credit", "is_header": True},
    {"code": "3001", "name": "Owner's Equity", "account_type": "equity", "category": "Equity", "normal_balance": "credit", "parent_code": "300"},
    {"code": "3002", "name": "Retained Earnings", "account_type": "equity", "category": "Equity", "normal_balance": "credit", "parent_code": "300"},

    # ---- Income (4xx) ----
    {"code": "400", "name": "Revenue", "account_type": "income", "category": "Revenue", "normal_balance": "credit", "is_header": True},
    {
        "code": "4001",
        "name": "Tuition Income",
        "account_type": "income",
        "category": "Revenue",
        "normal_balance": "credit",
        "parent_code": "400",
        "is_system_managed": True,
        "description": "System-managed account for tuition collections.",
    },
    {"code": "4002", "name": "Fee Income", "account_type": "income", "category": "Revenue", "normal_balance": "credit", "parent_code": "400"},
    {"code": "4003", "name": "Donations", "account_type": "income", "category": "Revenue", "normal_balance": "credit", "parent_code": "400"},
    {
        "code": "4099",
        "name": "Other Income",
        "account_type": "income",
        "category": "Revenue",
        "normal_balance": "credit",
        "parent_code": "400",
        "is_system_managed": True,
        "description": "System-managed catch-all income account.",
    },

    # ---- Expenses (5xx) ----
    {"code": "500", "name": "Operating Expenses", "account_type": "expense", "category": "Operating Expense", "normal_balance": "debit", "is_header": True},
    {"code": "5001", "name": "Salaries Expense", "account_type": "expense", "category": "Operating Expense", "normal_balance": "debit", "parent_code": "500"},
    {"code": "5002", "name": "Operating Expense", "account_type": "expense", "category": "Operating Expense", "normal_balance": "debit", "parent_code": "500"},
    {"code": "5003", "name": "Utilities Expense", "account_type": "expense", "category": "Operating Expense", "normal_balance": "debit", "parent_code": "500"},
    {"code": "5004", "name": "Supplies Expense", "account_type": "expense", "category": "Operating Expense", "normal_balance": "debit", "parent_code": "500"},
    {"code": "5005", "name": "Concession / Discount Expense", "account_type": "expense", "category": "Operating Expense", "normal_balance": "debit", "parent_code": "500"},
    {
        "code": "5006",
        "name": "Refunds",
        "account_type": "expense",
        "category": "Operating Expense",
        "normal_balance": "debit",
        "parent_code": "500",
        "is_system_managed": True,
        "description": "System-managed account for refunds issued to payers.",
    },
    {
        "code": "5099",
        "name": "Other Expense",
        "account_type": "expense",
        "category": "Operating Expense",
        "normal_balance": "debit",
        "parent_code": "500",
        "is_system_managed": True,
        "description": "System-managed catch-all expense account.",
    },
]


accounting_payment_methods = [
    {"name": "Cash", "code": "CASH", "description": "Cash payments"},
    {"name": "Check", "code": "CHECK", "description": "Check / cheque payments"},
    {"name": "Bank Transfer", "code": "BANK", "description": "Bank wire / transfer"},
    {"name": "Mobile Money", "code": "MOMO", "description": "Mobile money payments"},
    {"name": "Credit Card", "code": "CARD", "description": "Credit / debit card payments"},
    {"name": "Online Payment", "code": "ONLINE", "description": "Online gateway payments"},
    {"name": "Other", "code": "OTHER", "description": "Other payment methods"},
]


# `transaction_category` matches AccountingTransactionType.transaction_category choices.
# `default_ledger_account_code` is resolved at seed time to the matching
# AccountingLedgerAccount for auto-posting.
# `is_system_managed=True` types cannot be edited or deleted from the UI.
accounting_transaction_types = [
    {
        "name": "Tuition Payment",
        "code": "TUITION",
        "transaction_category": "income",
        "description": "Student tuition collection",
        "default_ledger_account_code": "4001",
        "is_system_managed": True,
    },
    {
        "name": "Fee Payment",
        "code": "FEE",
        "transaction_category": "income",
        "description": "Student general / activity fees",
        "default_ledger_account_code": "4002",
    },
    {
        "name": "Donation",
        "code": "DONATION",
        "transaction_category": "income",
        "description": "Donations received",
        "default_ledger_account_code": "4003",
    },
    {
        "name": "Other Income",
        "code": "OTHER_INCOME",
        "transaction_category": "income",
        "description": "Other income",
        "default_ledger_account_code": "4099",
        "is_system_managed": True,
    },
    {
        "name": "Payroll",
        "code": "PAYROLL",
        "transaction_category": "expense",
        "description": "Staff salary disbursement",
        "default_ledger_account_code": "5001",
    },
    {
        "name": "Operating Expense",
        "code": "OPEX",
        "transaction_category": "expense",
        "description": "Operating expenses",
        "default_ledger_account_code": "5002",
    },
    {
        "name": "Refund",
        "code": "REFUND",
        "transaction_category": "expense",
        "description": "Refunds to students / payers",
        "default_ledger_account_code": "5006",
        "is_system_managed": True,
    },
    {
        "name": "Concession",
        "code": "CONCESSION",
        "transaction_category": "expense",
        "description": "Discounts / concessions granted",
        "default_ledger_account_code": "5005",
    },
    {
        "name": "Other Expense",
        "code": "OTHER_EXPENSE",
        "transaction_category": "expense",
        "description": "Other expenses",
        "default_ledger_account_code": "5099",
        "is_system_managed": True,
    },
    {
        "name": "Transfer In",
        "code": "TRANSFER_IN",
        "transaction_category": "transfer",
        "description": "Funds received into a bank/cash account",
        "default_ledger_account_code": "1901",
        "is_system_managed": True,
    },
    {
        "name": "Transfer Out",
        "code": "TRANSFER_OUT",
        "transaction_category": "transfer",
        "description": "Funds sent out of a bank/cash account",
        "default_ledger_account_code": "1901",
        "is_system_managed": True,
    },
]


accounting_fee_items = [
    {"name": "Tuition", "code": "TUITION-01", "category": "tuition", "description": "Standard tuition fee"},
    {"name": "Registration Fee", "code": "REG-01", "category": "general", "description": "Annual registration fee"},
    {"name": "Activity Fee", "code": "ACT-01", "category": "activity", "description": "Student activity fee"},
    {"name": "Examination Fee", "code": "EXAM-01", "category": "general", "description": "Examination fee"},
    {"name": "Books & Supplies", "code": "BOOKS-01", "category": "general", "description": "Books and supplies"},
]


# Default bank/cash account seeded for every new tenant. The `ledger_account_code`
# is resolved at seed time to the matching AccountingLedgerAccount.
accounting_bank_accounts = [
    {
        "account_number": "INHOUSE-SAVINGS-01",
        "account_name": "In-House Savings",
        "bank_name": "",
        "account_type": "savings",
        "ledger_account_code": "1002",
        "opening_balance": 0,
        "status": "active",
        "description": "Default in-house savings account.",
    },
]
