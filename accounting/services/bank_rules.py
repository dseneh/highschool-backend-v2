"""Centralized calculators and validators for bank-account rules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
import re
import logging

from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.db.models import DecimalField, F, Q, QuerySet, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from accounting.models import (
    AccountingBankAccount,
    AccountingBankBalanceRule,
    AccountingNotificationChannel,
    AccountingCashTransaction,
    AccountingJournalLine,
    AccountingNotificationTriggerStatus,
    AccountingRuleThresholdState,
    AccountingSpendableAllocationRule,
)
from common.email_validation import is_valid_email
from common.email_service import ResendEmailService

logger = logging.getLogger(__name__)

PLACEHOLDER_PATTERN = re.compile(r"{{\s*([a-z_]+)\s*}}")

ALLOWED_EMAIL_PLACEHOLDERS = {
    "tenant_name",
    "rule_name",
    "rule_explanation",
    "account_name",
    "current_balance",
    "maximum_balance",
    "remaining_amount",
    "recommended_transfer_amount",
    "threshold_percentage",
    "transaction_amount",
    "transaction_reference",
    "date",
}

DEFAULT_EMAIL_SUBJECT = "[{{tenant_name}}] Bank limit alert: {{rule_name}}"
LEGACY_TRANSFER_SENTENCE = (
    "Please transfer the remaining funds to the appropriate bank account to avoid exceeding the limit."
)
DEFAULT_EMAIL_BODY = (
    "Hello,\n\n"
    "A bank account rule threshold was reached.\n\n"
    "School: {{tenant_name}}\n"
    "Rule: {{rule_name}}\n"
    "Account: {{account_name}}\n"
    "Current Balance: {{current_balance}}\n"
    "Maximum Balance: {{maximum_balance}}\n"
    "Remaining Amount: {{remaining_amount}}\n"
    "Recommended Transfer Amount: {{recommended_transfer_amount}}\n"
    "Threshold: {{threshold_percentage}}%\n"
    "Transaction Amount: {{transaction_amount}}\n"
    "Transaction Reference: {{transaction_reference}}\n"
    "Date: {{date}}\n\n"
    "{{rule_explanation}}\n\n"
    "This is an automated message from EzySchool."
)

ACTUAL_STATUSES = [AccountingCashTransaction.TransactionStatus.COMPLETED]
PROJECTED_STATUSES = [
    AccountingCashTransaction.TransactionStatus.PENDING,
    AccountingCashTransaction.TransactionStatus.APPROVED,
    AccountingCashTransaction.TransactionStatus.COMPLETED,
]
APPROVED_AND_COMPLETED_STATUSES = [
    AccountingCashTransaction.TransactionStatus.APPROVED,
    AccountingCashTransaction.TransactionStatus.COMPLETED,
]


@dataclass
class LimitEvaluation:
    should_block: bool
    requires_warning_confirmation: bool
    warning_messages: list[str]
    blocking_messages: list[str]
    details: list[dict]


def validate_template_placeholders(*templates: str) -> None:
    unknown: set[str] = set()
    for template in templates:
        if not template:
            continue
        for placeholder in PLACEHOLDER_PATTERN.findall(template):
            if placeholder not in ALLOWED_EMAIL_PLACEHOLDERS:
                unknown.add(placeholder)

    if unknown:
        formatted = ", ".join(sorted(unknown))
        raise ValidationError(
            f"Unknown placeholders: {formatted}. Allowed placeholders: "
            f"{', '.join(sorted(ALLOWED_EMAIL_PLACEHOLDERS))}."
        )


def render_email_template(template: str, context: dict[str, str | int | Decimal]) -> str:
    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        value = context.get(key, "")
        return str(value)

    return PLACEHOLDER_PATTERN.sub(_replace, template or "")


def default_email_template() -> dict[str, str]:
    return {
        "subject": DEFAULT_EMAIL_SUBJECT,
        "body": DEFAULT_EMAIL_BODY,
    }


def period_bounds(period: str, *, as_of: date | None = None) -> tuple[date | None, date | None]:
    dt = as_of or timezone.now().date()

    if period == "all_time":
        return None, dt
    if period == "yearly":
        return date(dt.year, 1, 1), dt
    if period == "quarterly":
        quarter_start_month = ((dt.month - 1) // 3) * 3 + 1
        return date(dt.year, quarter_start_month, 1), dt
    if period == "monthly":
        return date(dt.year, dt.month, 1), dt

    return date(dt.year, dt.month, 1), dt


def total_revenue_from_posted_ledger(*, period: str, as_of: date | None = None) -> Decimal:
    start_date, end_date = period_bounds(period, as_of=as_of)

    queryset = AccountingJournalLine.objects.filter(
        journal_entry__status="posted",
        ledger_account__account_type="income",
    )
    if start_date:
        queryset = queryset.filter(journal_entry__posting_date__gte=start_date)
    if end_date:
        queryset = queryset.filter(journal_entry__posting_date__lte=end_date)

    totals = queryset.aggregate(
        credit_total=Coalesce(Sum("credit_amount"), Decimal("0.00"), output_field=DecimalField()),
        debit_total=Coalesce(Sum("debit_amount"), Decimal("0.00"), output_field=DecimalField()),
    )
    return (totals["credit_total"] or Decimal("0.00")) - (totals["debit_total"] or Decimal("0.00"))


def total_revenue_from_recorded_income(*, period: str, as_of: date | None = None) -> Decimal:
    """Revenue fallback from recorded income transactions.

    This keeps percent-of-revenue limits usable even when journal posting is not
    fully enabled yet for a tenant.
    """

    start_date, end_date = period_bounds(period, as_of=as_of)

    queryset = AccountingCashTransaction.objects.filter(
        status__in=PROJECTED_STATUSES,
        transaction_type__transaction_category="income",
    )
    if start_date:
        queryset = queryset.filter(transaction_date__gte=start_date)
    if end_date:
        queryset = queryset.filter(transaction_date__lte=end_date)

    return queryset.aggregate(
        total=Coalesce(Sum("base_amount"), Decimal("0.00"), output_field=DecimalField())
    )["total"] or Decimal("0.00")


def resolve_revenue_basis(*, period: str, as_of: date | None = None) -> Decimal:
    """Resolve revenue basis for percent-based limits.

    Priority:
    1) Posted ledger revenue
    2) Recorded income transaction fallback
    Always returns a non-negative value.
    """

    posted_revenue = total_revenue_from_posted_ledger(period=period, as_of=as_of)
    if posted_revenue > 0:
        return posted_revenue

    recorded_revenue = total_revenue_from_recorded_income(period=period, as_of=as_of)
    return max(recorded_revenue, Decimal("0.00"))


def normalize_limit_mode(limit_mode: str | None) -> str:
    normalized = str(limit_mode or "").strip().lower()
    if normalized in {"fixed_amount", "flat"}:
        return "fixed_amount"
    if normalized in {"percent_revenue", "percentage"}:
        return "percent_revenue"
    return normalized


def resolve_limit_amount(limit_mode: str, fixed_value: Decimal | None, percent_value: Decimal | None, revenue_period: str) -> Decimal:
    normalized_mode = normalize_limit_mode(limit_mode)
    if normalized_mode == "fixed_amount":
        return fixed_value or Decimal("0.00")

    if normalized_mode != "percent_revenue":
        return Decimal("0.00")

    revenue = resolve_revenue_basis(period=revenue_period)
    percentage = percent_value or Decimal("0.00")
    return (revenue * percentage) / Decimal("100")


def _inflow_filter() -> Q:
    return Q(transaction_type__transaction_category="income") | Q(transaction_type__code__iexact="TRANSFER_IN")


def _outflow_filter() -> Q:
    return Q(transaction_type__transaction_category="expense") | Q(transaction_type__code__iexact="TRANSFER_OUT")


def _signed_sum(queryset: QuerySet) -> Decimal:
    inflow = queryset.filter(_inflow_filter()).aggregate(
        total=Coalesce(Sum("base_amount"), Decimal("0.00"), output_field=DecimalField())
    )["total"] or Decimal("0.00")
    outflow = queryset.filter(_outflow_filter()).aggregate(
        total=Coalesce(Sum("base_amount"), Decimal("0.00"), output_field=DecimalField())
    )["total"] or Decimal("0.00")
    return inflow - outflow


def account_balance_for_statuses(
    bank_account: AccountingBankAccount,
    *,
    statuses: list[str],
    exclude_transaction_id: str | None = None,
) -> Decimal:
    queryset = AccountingCashTransaction.objects.filter(
        bank_account=bank_account,
        status__in=statuses,
    )
    if exclude_transaction_id:
        queryset = queryset.exclude(id=exclude_transaction_id)
    return _signed_sum(queryset)


def signed_effect_for_transaction(*, transaction_category: str, transaction_code: str, amount: Decimal) -> Decimal:
    code_upper = (transaction_code or "").upper()
    if transaction_category == "income" or code_upper == "TRANSFER_IN":
        return amount
    return -amount


def _should_fire_threshold(rule: AccountingBankBalanceRule, ratio_percent: Decimal, max_amount: Decimal) -> tuple[bool, Decimal]:
    threshold = rule.alert_threshold_percentage or Decimal("0.00")
    at_max = max_amount > 0 and ratio_percent >= Decimal("100.00")
    before_max = max_amount > 0 and ratio_percent >= threshold

    if rule.alert_trigger == "at_maximum":
        return at_max, Decimal("100.00")
    if rule.alert_trigger == "before":
        return before_max, threshold
    return at_max or before_max, max(threshold, Decimal("100.00") if at_max else threshold)


def mark_threshold_crossing(
    *,
    rule: AccountingBankBalanceRule,
    bank_account: AccountingBankAccount,
    ratio_percent: Decimal,
    projected_balance: Decimal,
    max_amount: Decimal,
) -> tuple[bool, Decimal]:
    crossed, threshold_value = _should_fire_threshold(rule, ratio_percent, max_amount)

    state, _ = AccountingRuleThresholdState.objects.get_or_create(
        balance_rule=rule,
        bank_account=bank_account,
        threshold_percentage=threshold_value,
        defaults={"is_above_threshold": False},
    )

    if not crossed:
        if state.is_above_threshold:
            state.is_above_threshold = False
            state.save(update_fields=["is_above_threshold", "updated_at"])
        return False, threshold_value

    if state.is_above_threshold:
        return False, threshold_value

    state.is_above_threshold = True
    state.last_triggered_balance = projected_balance
    state.last_triggered_at = timezone.now()
    state.save(
        update_fields=[
            "is_above_threshold",
            "last_triggered_balance",
            "last_triggered_at",
            "updated_at",
        ]
    )
    return True, threshold_value


def evaluate_transaction_limits(
    *,
    bank_account: AccountingBankAccount,
    transaction_type,
    base_amount: Decimal,
    exclude_transaction_id: str | None = None,
    persist_threshold_state: bool = True,
) -> LimitEvaluation:
    transaction_category = str(getattr(transaction_type, "transaction_category", "") or "").lower()
    signed_effect = signed_effect_for_transaction(
        transaction_category=transaction_type.transaction_category,
        transaction_code=transaction_type.code,
        amount=base_amount,
    )

    current_actual_balance = account_balance_for_statuses(
        bank_account,
        statuses=ACTUAL_STATUSES,
        exclude_transaction_id=exclude_transaction_id,
    )
    current_projected_balance = account_balance_for_statuses(
        bank_account,
        statuses=PROJECTED_STATUSES,
        exclude_transaction_id=exclude_transaction_id,
    )
    projected_balance = current_projected_balance + signed_effect

    blocking_messages: list[str] = []
    warning_messages: list[str] = []
    details: list[dict] = []

    if transaction_category == "income":
        active_rules = AccountingBankBalanceRule.objects.filter(
            is_active=True,
            bank_accounts=bank_account,
        ).prefetch_related("alert_recipients")

        for rule in active_rules:
            revenue_basis = None
            percentage_value = None
            if rule.limit_mode == "percent_revenue":
                raw_revenue = total_revenue_from_posted_ledger(period=rule.revenue_period)
                revenue_basis = max(raw_revenue, Decimal("0.00"))
                percentage_value = rule.revenue_percentage or Decimal("0.00")

            maximum = resolve_limit_amount(
                rule.limit_mode,
                rule.fixed_maximum_balance,
                rule.revenue_percentage,
                rule.revenue_period,
            )
            remaining = maximum - projected_balance
            exceeded = maximum > 0 and projected_balance >= maximum

            detail = {
                "rule_name": rule.name,
                "current_balance": str(current_actual_balance),
                "projected_balance": str(projected_balance),
                "maximum_balance": str(maximum),
                "remaining_capacity": str(remaining),
                "is_exceeded": exceeded,
                "behavior": rule.behavior,
                "limit_mode": rule.limit_mode,
                "revenue_period": rule.revenue_period,
            }

            if maximum > 0:
                ratio_percent = (projected_balance / maximum) * Decimal("100")
            else:
                ratio_percent = Decimal("0")

            detail["threshold_percentage"] = str(rule.alert_threshold_percentage)
            detail["projected_ratio_percentage"] = str(ratio_percent.quantize(Decimal("0.01")))

            if rule.enable_email_alerts:
                if persist_threshold_state:
                    should_send, threshold = mark_threshold_crossing(
                        rule=rule,
                        bank_account=bank_account,
                        ratio_percent=ratio_percent,
                        projected_balance=projected_balance,
                        max_amount=maximum,
                    )
                else:
                    should_send, threshold = _should_fire_threshold(
                        rule,
                        ratio_percent,
                        maximum,
                    )
                detail["alert_crossed"] = should_send
                detail["crossed_threshold_percentage"] = str(threshold)
                detail["email_alert_applicable"] = bool(should_send and rule.alert_recipients.exists())
            else:
                detail["alert_crossed"] = False
                detail["crossed_threshold_percentage"] = None
                detail["email_alert_applicable"] = False

            details.append(detail)

            if exceeded:
                message = (
                    f"Rule '{rule.name}' reached its maximum balance for account "
                    f"'{bank_account.account_name}'."
                )
                if rule.behavior == "block":
                    blocking_messages.append(message)
                else:
                    warning_messages.append(message)

    if transaction_category == "expense":
        spend_rule = (
            AccountingSpendableAllocationRule.objects.filter(is_active=True)
            .order_by("-updated_at")
            .first()
        )
    else:
        spend_rule = None

    if spend_rule:
        additional_expense = abs(signed_effect) if signed_effect < 0 else Decimal("0.00")
        revenue_basis = resolve_revenue_basis(period=spend_rule.revenue_period)
        percentage_value = None
        if normalize_limit_mode(spend_rule.limit_mode) == "percent_revenue":
            percentage_value = spend_rule.revenue_percentage or Decimal("0.00")
        allocation = resolve_limit_amount(
            spend_rule.limit_mode,
            spend_rule.fixed_allocation,
            spend_rule.revenue_percentage,
            spend_rule.revenue_period,
        )
        used_amount = AccountingCashTransaction.objects.filter(
            status__in=PROJECTED_STATUSES,
            transaction_type__transaction_category="expense",
        ).aggregate(
            total=Coalesce(Sum("base_amount"), Decimal("0.00"), output_field=DecimalField())
        )["total"] or Decimal("0.00")
        projected_used = used_amount + additional_expense
        remaining_allocation = allocation - projected_used
        exceeded_allocation = allocation > 0 and projected_used >= allocation

        details.append(
            {
                "rule_name": spend_rule.name,
                "kind": "spendable_allocation",
                "current_balance": str(used_amount),
                "projected_balance": str(projected_used),
                "maximum_balance": str(allocation),
                "remaining_capacity": str(remaining_allocation),
                "is_exceeded": exceeded_allocation,
                "behavior": spend_rule.behavior,
                "limit_mode": spend_rule.limit_mode,
                "revenue_period": spend_rule.revenue_period,
                "revenue_basis": str(revenue_basis) if revenue_basis is not None else None,
                "revenue_percentage": str(percentage_value) if percentage_value is not None else None,
            }
        )

        if exceeded_allocation:
            message = f"Spendable allocation rule '{spend_rule.name}' has been reached."
            if spend_rule.behavior == "block":
                blocking_messages.append(message)
            else:
                warning_messages.append(message)

    return LimitEvaluation(
        should_block=bool(blocking_messages),
        requires_warning_confirmation=bool(warning_messages) and not blocking_messages,
        warning_messages=warning_messages,
        blocking_messages=blocking_messages,
        details=details,
    )


def compute_bank_account_rule_status(bank_account: AccountingBankAccount) -> dict[str, object]:
    """Return a computed status snapshot describing active balance-rule impact."""

    prefetched_rules = getattr(bank_account, "_prefetched_objects_cache", {}).get("balance_rules")
    if prefetched_rules is not None:
        active_rules = [rule for rule in prefetched_rules if rule.is_active]
    else:
        active_rules = list(
            AccountingBankBalanceRule.objects.filter(
                is_active=True,
                bank_accounts=bank_account,
            )
        )

    if not active_rules:
        return {
            "has_active_rules": False,
            "positive": False,
            "should_alert": False,
            "severity": "none",
            "message": "No active bank balance rules apply to this account.",
            "triggered_rule_count": 0,
            "total_rule_count": 0,
            "rules": [],
        }

    current_balance = account_balance_for_statuses(bank_account, statuses=ACTUAL_STATUSES)
    rules_payload: list[dict[str, object]] = []
    triggered_rule_count = 0
    has_critical = False

    for rule in active_rules:
        revenue_basis: Decimal | None = None
        percentage_value: Decimal | None = None
        if rule.limit_mode == "percent_revenue":
            revenue_basis = resolve_revenue_basis(period=rule.revenue_period)
            percentage_value = rule.revenue_percentage or Decimal("0.00")

        maximum = resolve_limit_amount(
            rule.limit_mode,
            rule.fixed_maximum_balance,
            rule.revenue_percentage,
            rule.revenue_period,
        )
        threshold = rule.alert_threshold_percentage or Decimal("0.00")

        if maximum > 0:
            ratio_percent = (current_balance / maximum) * Decimal("100")
        else:
            ratio_percent = Decimal("0.00")

        at_maximum = maximum > 0 and ratio_percent >= Decimal("100.00")
        before_maximum = maximum > 0 and ratio_percent >= threshold
        if rule.alert_trigger == "at_maximum":
            threshold_positive = at_maximum
        elif rule.alert_trigger == "before":
            threshold_positive = before_maximum
        else:
            threshold_positive = at_maximum or before_maximum

        positive = threshold_positive or at_maximum
        if positive:
            triggered_rule_count += 1
        if at_maximum and rule.behavior == "block":
            has_critical = True

        rules_payload.append(
            {
                "id": str(rule.id),
                "name": rule.name,
                "positive": positive,
                "at_maximum": at_maximum,
                "threshold_positive": threshold_positive,
                "behavior": rule.behavior,
                "alert_trigger": rule.alert_trigger,
                "notification_channel": _normalize_notification_channel(
                    getattr(rule, "notification_channel", None)
                ),
                "email_alerts_enabled": bool(rule.enable_email_alerts),
                "has_email_recipients": bool(rule.alert_recipients.exists()),
                "limit_mode": rule.limit_mode,
                "revenue_period": rule.revenue_period,
                "revenue_basis": str(revenue_basis) if revenue_basis is not None else None,
                "revenue_percentage": str(percentage_value) if percentage_value is not None else None,
                "current_balance": str(current_balance),
                "maximum_balance": str(maximum),
                "ratio_percentage": str(ratio_percent.quantize(Decimal("0.01"))),
                "threshold_percentage": str(threshold),
            }
        )

    has_positive = triggered_rule_count > 0
    if has_positive and has_critical:
        severity = "critical"
        message = (
            f"{triggered_rule_count} active bank rule"
            f"{'s' if triggered_rule_count != 1 else ''} reached a blocking maximum threshold."
        )
    elif has_positive:
        severity = "warning"
        message = (
            f"{triggered_rule_count} active bank rule"
            f"{'s' if triggered_rule_count != 1 else ''} currently meets an alert threshold."
        )
    else:
        severity = "ok"
        message = "Active bank balance rules apply, and all are currently within threshold."

    return {
        "has_active_rules": True,
        "positive": has_positive,
        "should_alert": has_positive,
        "severity": severity,
        "message": message,
        "triggered_rule_count": triggered_rule_count,
        "total_rule_count": len(active_rules),
        "rules": rules_payload,
    }


def _recipient_emails_for_rule(rule: AccountingBankBalanceRule) -> list[str]:
    emails: list[str] = []
    seen: set[str] = set()
    for employee in rule.alert_recipients.all():
        raw_email = (getattr(employee, "email", None) or "").strip().lower()
        if not is_valid_email(raw_email):
            continue
        if raw_email in seen:
            continue
        seen.add(raw_email)
        emails.append(raw_email)
    return emails


def _tenant_name_for_alerts() -> str:
    tenant = getattr(connection, "tenant", None)
    if tenant is not None:
        candidate = str(getattr(tenant, "name", "") or "").strip()
        if candidate:
            return candidate
    schema_name = str(getattr(connection, "schema_name", "") or "").strip()
    if schema_name:
        return schema_name
    return "Your School"


def _format_amount_text(value: Decimal) -> str:
    return f"{value:,.2f}"


def notification_balance_statuses(trigger_status: str) -> list[str]:
    status_value = str(trigger_status or AccountingNotificationTriggerStatus.COMPLETED).strip().lower()
    if status_value == AccountingNotificationTriggerStatus.PENDING:
        return PROJECTED_STATUSES
    if status_value == AccountingNotificationTriggerStatus.APPROVED:
        return APPROVED_AND_COMPLETED_STATUSES
    return ACTUAL_STATUSES


def _build_rule_explanation_text(
    *,
    account_name: str,
    behavior: str,
    at_maximum: bool,
    ratio_percent: Decimal,
    threshold_percent: Decimal,
    current_balance: Decimal,
    maximum_balance: Decimal,
) -> str:
    remaining = maximum_balance - current_balance
    transfer_needed = max(current_balance - maximum_balance, Decimal("0.00"))

    warning = (
        "has reached its maximum and blocks additional balance increases."
        if at_maximum and behavior == "block"
        else "has reached its maximum and allows transactions only with warning acknowledgment."
        if at_maximum
        else f"has reached the configured warning threshold ({_format_amount_text(threshold_percent)}% used)."
    )

    action = (
        f"Transfer out at least {_format_amount_text(transfer_needed)} from this account to return below the configured cap."
        if at_maximum and transfer_needed > 0
        else "Move funds out of this account before posting more incoming transactions."
        if at_maximum
        else f"Remaining headroom is {_format_amount_text(remaining)} before reaching the maximum cap."
        if remaining > 0
        else "Review account movements and consider transferring funds out to avoid exceeding the cap."
    )

    return (
        f"{account_name} {warning} "
        f"Current usage is {_format_amount_text(ratio_percent)}% "
        f"({_format_amount_text(current_balance)} of {_format_amount_text(maximum_balance)}). "
        f"{action}"
    )


def _normalize_legacy_email_body_template(template: str) -> str:
    body = template or ""
    if LEGACY_TRANSFER_SENTENCE not in body:
        return body

    if "{{recommended_transfer_amount}}" not in body:
        body = body.replace(
            "Remaining Amount: {{remaining_amount}}\n",
            "Remaining Amount: {{remaining_amount}}\nRecommended Transfer Amount: {{recommended_transfer_amount}}\n",
        )

    body = body.replace("Rule: {{rule_name}}\n{{rule_explanation}}\n", "Rule: {{rule_name}}\n")
    body = body.replace(
        "Date: {{date}}\n\n",
        "Date: {{date}}\n\n{{rule_explanation}}\n\n",
    ) if "{{rule_explanation}}" not in body or "Date: {{date}}\n\n{{rule_explanation}}" not in body else body

    body = body.replace(f"{LEGACY_TRANSFER_SENTENCE}\n\n\n", "")
    body = body.replace(LEGACY_TRANSFER_SENTENCE, "")
    return body


def _recipient_user_ids_for_rule(rule: AccountingBankBalanceRule) -> list[str]:
    from notifications.services.audience import get_tenant_user_queryset

    candidate_id_numbers = {
        str(getattr(employee, "user_account_id_number", "") or getattr(employee, "id_number", "")).strip()
        for employee in rule.alert_recipients.all()
    }
    candidate_id_numbers.discard("")
    if not candidate_id_numbers:
        return []

    return [
        str(user_id)
        for user_id in get_tenant_user_queryset()
        .filter(id_number__in=candidate_id_numbers)
        .values_list("id", flat=True)
        .distinct()
    ]


def _normalize_notification_channel(channel: str | None) -> str:
    channel_value = str(channel or AccountingNotificationChannel.IN_APP).strip().lower()
    if channel_value in {
        AccountingNotificationChannel.IN_APP,
        AccountingNotificationChannel.EMAIL,
        AccountingNotificationChannel.BOTH,
    }:
        return channel_value
    return AccountingNotificationChannel.IN_APP


def validate_bulk_balance_rule_batch(
    *,
    account_effects: dict[AccountingBankAccount, Decimal],
) -> None:
    messages: list[str] = []

    for bank_account, signed_effect in account_effects.items():
        if signed_effect == 0:
            continue

        current_projected_balance = account_balance_for_statuses(
            bank_account,
            statuses=PROJECTED_STATUSES,
        )
        projected_balance = current_projected_balance + signed_effect

        active_rules = AccountingBankBalanceRule.objects.filter(
            is_active=True,
            behavior="block",
            bank_accounts=bank_account,
        )

        for rule in active_rules:
            maximum = resolve_limit_amount(
                rule.limit_mode,
                rule.fixed_maximum_balance,
                rule.revenue_percentage,
                rule.revenue_period,
            )
            if maximum > 0 and projected_balance >= maximum:
                messages.append(
                    f"Bulk operation would violate blocking rule '{rule.name}' for account '{bank_account.account_name}'. "
                    f"Projected balance {projected_balance:,.2f} would reach or exceed the maximum {maximum:,.2f}."
                )

    if messages:
        raise ValidationError(messages)


def dispatch_bank_rule_alerts_for_status_event(
    *,
    bank_account: AccountingBankAccount,
    transaction_status: str,
    event_key: str,
    actor=None,
    transaction_amount: Decimal | None = None,
    transaction_reference: str = "",
    transaction_date: date | None = None,
) -> dict[str, int]:
    from notifications.models import NotificationCampaign
    from notifications.services.campaign_send import create_and_send_campaign

    status_value = str(transaction_status or "").strip().lower()
    if status_value not in {
        AccountingNotificationTriggerStatus.PENDING,
        AccountingNotificationTriggerStatus.APPROVED,
        AccountingNotificationTriggerStatus.COMPLETED,
    }:
        return {"attempted": 0, "sent": 0, "in_app": 0}

    balance_statuses = notification_balance_statuses(status_value)
    current_balance = account_balance_for_statuses(
        bank_account,
        statuses=balance_statuses,
    )
    tenant_name = _tenant_name_for_alerts()
    effective_date = transaction_date or timezone.now().date()
    amount_value = transaction_amount if transaction_amount is not None else Decimal("0.00")
    defaults = default_email_template()
    service = ResendEmailService()

    sent_count = 0
    attempted_count = 0
    in_app_count = 0

    active_rules = AccountingBankBalanceRule.objects.filter(
        is_active=True,
        enable_email_alerts=True,
        notification_trigger_status=status_value,
        bank_accounts=bank_account,
    ).prefetch_related("alert_recipients")

    for rule in active_rules:
        maximum = resolve_limit_amount(
            rule.limit_mode,
            rule.fixed_maximum_balance,
            rule.revenue_percentage,
            rule.revenue_period,
        )

        if maximum > 0:
            ratio_percent = (current_balance / maximum) * Decimal("100")
        else:
            ratio_percent = Decimal("0.00")

        at_maximum = maximum > 0 and ratio_percent >= Decimal("100.00")
        threshold_percent = rule.alert_threshold_percentage or Decimal("0.00")
        crossed, threshold = _should_fire_threshold(rule, ratio_percent, maximum)

        with transaction.atomic():
            state, _ = AccountingRuleThresholdState.objects.get_or_create(
                balance_rule=rule,
                bank_account=bank_account,
                threshold_percentage=threshold,
                defaults={"is_above_threshold": False},
            )
            state = AccountingRuleThresholdState.objects.select_for_update().get(pk=state.pk)

            if not crossed:
                if state.is_above_threshold:
                    state.is_above_threshold = False
                    state.save(update_fields=["is_above_threshold", "updated_at"])
                continue

            if state.last_notified_event_key == event_key:
                continue

            notification_channel = _normalize_notification_channel(
                getattr(rule, "notification_channel", None)
            )
            send_in_app = notification_channel in {
                AccountingNotificationChannel.IN_APP,
                AccountingNotificationChannel.BOTH,
            }
            send_email = notification_channel in {
                AccountingNotificationChannel.EMAIL,
                AccountingNotificationChannel.BOTH,
            }

            recipient_user_ids = _recipient_user_ids_for_rule(rule) if send_in_app else []
            recipient_emails = _recipient_emails_for_rule(rule) if send_email else []
            if send_in_app and not recipient_user_ids and send_email and not recipient_emails:
                logger.info(
                    "Skipping bank rule alert for rule=%s account=%s: no valid recipients for configured channels.",
                    rule.id,
                    bank_account.id,
                )
                continue
            if send_in_app and not recipient_user_ids and not send_email:
                logger.info(
                    "Skipping bank rule in-app alert for rule=%s account=%s: no valid in-app recipients.",
                    rule.id,
                    bank_account.id,
                )
                continue
            if send_email and not recipient_emails and not send_in_app:
                logger.info(
                    "Skipping bank rule email alert for rule=%s account=%s: no valid email recipients.",
                    rule.id,
                    bank_account.id,
                )
                continue

            state.is_above_threshold = True
            state.last_triggered_balance = current_balance
            state.last_triggered_at = timezone.now()
            state.last_notified_event_key = event_key
            state.save(
                update_fields=[
                    "is_above_threshold",
                    "last_triggered_balance",
                    "last_triggered_at",
                    "last_notified_event_key",
                    "updated_at",
                ]
            )

        remaining = maximum - current_balance
        recommended_transfer_amount = max(current_balance - maximum, Decimal("0.00"))
        subject_template = defaults["subject"]
        body_template = defaults["body"]
        if not rule.use_default_email_template:
            subject_template = (rule.email_subject_template or "").strip() or subject_template
            body_template = _normalize_legacy_email_body_template(
                (rule.email_body_template or "").strip()
            ) or body_template

        rule_explanation = _build_rule_explanation_text(
            account_name=bank_account.account_name,
            behavior=rule.behavior,
            at_maximum=at_maximum,
            ratio_percent=ratio_percent.quantize(Decimal("0.01")),
            threshold_percent=threshold_percent,
            current_balance=current_balance,
            maximum_balance=maximum,
        )
        context = {
            "tenant_name": tenant_name,
            "rule_name": rule.name,
            "rule_explanation": rule_explanation,
            "account_name": bank_account.account_name,
            "current_balance": f"{current_balance:,.2f}",
            "maximum_balance": f"{maximum:,.2f}",
            "remaining_amount": f"{remaining:,.2f}",
            "recommended_transfer_amount": f"{recommended_transfer_amount:,.2f}",
            "threshold_percentage": f"{threshold.quantize(Decimal('0.01'))}",
            "transaction_amount": f"{amount_value:,.2f}",
            "transaction_reference": transaction_reference or "N/A",
            "date": effective_date.strftime("%Y-%m-%d"),
        }

        if recipient_user_ids and actor is not None:
            create_and_send_campaign(
                title=f"Bank rule alert: {bank_account.account_name}",
                body=rule_explanation,
                category=NotificationCampaign.Category.ALERT,
                channels=["in_app"],
                audience={"scope": "user_ids", "user_ids": recipient_user_ids},
                source=NotificationCampaign.Source.RULE,
                created_by=actor,
                action_url=f"/accounting/bank-accounts/{bank_account.id}",
                banner_variant=(
                    NotificationCampaign.BannerVariant.ERROR
                    if rule.behavior == "block" and at_maximum
                    else NotificationCampaign.BannerVariant.WARNING
                ),
            )
            in_app_count += 1

        subject = render_email_template(subject_template, context)
        body = render_email_template(body_template, context)

        if recipient_emails:
            attempted_count += 1
            if service.send(to=recipient_emails, subject=subject, text_body=body):
                sent_count += 1
            else:
                logger.error(
                    "Failed to send bank rule alert for rule=%s account=%s to %s",
                    rule.id,
                    bank_account.id,
                    recipient_emails,
                )

    return {
        "attempted": attempted_count,
        "sent": sent_count,
        "in_app": in_app_count,
    }


def dispatch_bank_rule_alerts_for_account(
    *,
    bank_account: AccountingBankAccount,
    transaction_amount: Decimal | None = None,
    transaction_reference: str = "",
    transaction_date: date | None = None,
) -> dict[str, int]:
    legacy_date = transaction_date or timezone.now().date()
    return dispatch_bank_rule_alerts_for_status_event(
        bank_account=bank_account,
        transaction_status=AccountingNotificationTriggerStatus.COMPLETED,
        event_key=f"legacy:{bank_account.id}:{legacy_date.isoformat()}",
        actor=None,
        transaction_amount=transaction_amount,
        transaction_reference=transaction_reference,
        transaction_date=transaction_date,
    )
