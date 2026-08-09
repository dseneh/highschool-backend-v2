# Bank Rules Implementation Notes

## Scope
This document describes the first implementation slice for configurable bank account rules in accounting-v2.

## Canonical Revenue Calculation
Percentage-based limits and allocations use posted ledger income only.

Formula:
- `total_revenue = sum(credit_amount) - sum(debit_amount)`
- source rows: `AccountingJournalLine`
- filters:
  - `journal_entry.status = posted`
  - `ledger_account.account_type = income`

Supported revenue periods:
- `monthly`
- `quarterly`
- `yearly`
- `all_time`

## Balance Calculation Logic
Rule calculations are centralized in `accounting/services/bank_rules.py`.

Signed movement conventions:
- Inflow: income transactions or `TRANSFER_IN` => `+base_amount`
- Outflow: expense transactions or `TRANSFER_OUT` => `-base_amount`

## Transaction Status Inclusion
For rule evaluation:
- Actual balance: `completed`
- Projected balance: `pending`, `approved`, `completed`

These status sets are defined in one place (`ACTUAL_STATUSES`, `PROJECTED_STATUSES`) in the rule service.

## Limit Behaviors
- `block`: backend rejects transaction with validation error.
- `warn`: backend requires explicit override flag (`override_warning_limits=true`) and only accepts override from `admin` or `superadmin`.

Frontend warnings are informational. Backend is authoritative.

## Alert Placeholders
Allowed placeholders:
- `{{tenant_name}}`
- `{{rule_name}}`
- `{{account_name}}`
- `{{current_balance}}`
- `{{maximum_balance}}`
- `{{remaining_amount}}`
- `{{recommended_transfer_amount}}`
- `{{threshold_percentage}}`
- `{{transaction_amount}}`
- `{{transaction_reference}}`
- `{{date}}`

Template validation rejects unknown placeholders.

## Duplicate Alert Prevention
Threshold dedupe uses `AccountingRuleThresholdState` with keys:
- balance rule
- bank account
- threshold percentage

Behavior:
- Alert dispatch is event-based: each qualifying create/update(amount-change) action can send an alert while the rule condition is true.
- Threshold state still tracks above/below transitions and last triggered balance/time.
- Threshold state is marked as sent only after successful email dispatch; failed sends remain retryable on the next create/update action.

## Concurrency Safeguards
Transaction create/update limit checks run inside database transactions and lock relevant bank account rows (`select_for_update`) before evaluating and saving.

## Default Bank Accounts
`AccountingSettings` now stores:
- `default_payroll_bank_account`
- `default_expense_bank_account`

Validation rules:
- only active bank accounts are accepted.
- if account is later deleted, settings references become null due to `SET_NULL`.

## API Endpoints Added
- `accounting/balance-rules`
- `accounting/spendable-allocation-rules`
- `accounting/balance-rules/default-template/`
- `accounting/balance-rules/preview-template/`
- `accounting/balance-rules/{id}/restore-default-template/`
- `accounting/cash-transactions/limit-precheck/`

## Business Assumptions Requiring Confirmation
- Spendable allocation applies to expense-category outflows globally.
- Single numeric threshold (`alert_threshold_percentage`) is used per rule in this slice.
- Multi-threshold alert tiers (e.g. 80/90/100 simultaneously) are not yet implemented in this slice.
- Alert delivery is currently stateful and template-ready; full outbound campaign dispatch integration can be expanded in a follow-up.
