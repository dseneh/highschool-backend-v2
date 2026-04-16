from decimal import Decimal
from typing import Any
from datetime import datetime

from django.db.models import Q, Sum, Max
from django.db.models.functions import TruncMonth

from rest_framework import serializers

from accounting.models import (
    AccountingARSnapshot,
    AccountingAccountTransfer,
    AccountingBankAccount,
    AccountingConcession,
    AccountingCashTransaction,
    AccountingCurrency,
    AccountingExchangeRate,
    AccountingExpenseRecord,
    AccountingFeeItem,
    AccountingFeeRate,
    AccountingInstallmentLine,
    AccountingInstallmentPlan,
    AccountingJournalEntry,
    AccountingJournalLine,
    AccountingLedgerAccount,
    AccountingPaymentMethod,
    AccountingPayrollPostingBatch,
    AccountingPayrollPostingLine,
    AccountingStudentBill,
    AccountingStudentBillLine,
    AccountingStudentPaymentAllocation,
    AccountingTaxCode,
    AccountingTaxRemittance,
    AccountingTransactionType,
)
from accounting.services.posting import _resolve_academic_year


class AccountingCurrencySerializer(serializers.ModelSerializer):
    class Meta:
        model = AccountingCurrency
        fields = [
            "id",
            "name",
            "code",
            "symbol",
            "is_base_currency",
            "is_active",
            "decimal_places",
            "created_at",
            "updated_at",
        ]


class AccountingExchangeRateSerializer(serializers.ModelSerializer):
    class Meta:
        model = AccountingExchangeRate
        fields = "__all__"


class AccountingLedgerAccountSerializer(serializers.ModelSerializer):
    template_key = serializers.ChoiceField(
        choices=[
            "manual",
            "bank_account",
            "petty_cash",
            "accounts_receivable",
            "accounts_payable",
            "general_income",
            "other_income",
            "tuition_revenue",
            "general_expense",
            "utilities_expense",
            "salary_expense",
        ],
        write_only=True,
        required=False,
        allow_null=True,
    )
    code = serializers.CharField(required=False, allow_blank=True)

    TEMPLATE_DEFAULTS = {
        "bank_account": {
            "account_type": AccountingLedgerAccount.AccountType.ASSET,
            "normal_balance": "debit",
            "category": "current_assets",
            "header_code": "1000",
            "header_name": "Cash and Cash Equivalents",
        },
        "petty_cash": {
            "account_type": AccountingLedgerAccount.AccountType.ASSET,
            "normal_balance": "debit",
            "category": "current_assets",
            "header_code": "1000",
            "header_name": "Cash and Cash Equivalents",
            "default_name": "Petty Cash",
        },
        "accounts_receivable": {
            "account_type": AccountingLedgerAccount.AccountType.ASSET,
            "normal_balance": "debit",
            "category": "current_assets",
            "header_code": "1100",
            "header_name": "Receivables",
            "default_name": "Accounts Receivable",
        },
        "accounts_payable": {
            "account_type": AccountingLedgerAccount.AccountType.LIABILITY,
            "normal_balance": "credit",
            "category": "current_liabilities",
            "header_code": "2000",
            "header_name": "Payables",
            "default_name": "Accounts Payable",
        },
        "general_income": {
            "account_type": AccountingLedgerAccount.AccountType.INCOME,
            "normal_balance": "credit",
            "category": "operating_income",
            "header_code": "4000",
            "header_name": "Revenue",
            "default_name": "General Income",
        },
        "other_income": {
            "account_type": AccountingLedgerAccount.AccountType.INCOME,
            "normal_balance": "credit",
            "category": "other_income",
            "header_code": "4100",
            "header_name": "Other Income",
            "default_name": "Other Income",
        },
        "tuition_revenue": {
            "account_type": AccountingLedgerAccount.AccountType.INCOME,
            "normal_balance": "credit",
            "category": "operating_income",
            "header_code": "4000",
            "header_name": "Revenue",
            "default_name": "Tuition Revenue",
        },
        "general_expense": {
            "account_type": AccountingLedgerAccount.AccountType.EXPENSE,
            "normal_balance": "debit",
            "category": "operating_expenses",
            "header_code": "5000",
            "header_name": "Operating Expenses",
            "default_name": "General Expense",
        },
        "utilities_expense": {
            "account_type": AccountingLedgerAccount.AccountType.EXPENSE,
            "normal_balance": "debit",
            "category": "operating_expenses",
            "header_code": "5000",
            "header_name": "Operating Expenses",
            "default_name": "Utilities Expense",
        },
        "salary_expense": {
            "account_type": AccountingLedgerAccount.AccountType.EXPENSE,
            "normal_balance": "debit",
            "category": "operating_expenses",
            "header_code": "5000",
            "header_name": "Operating Expenses",
            "default_name": "Salary Expense",
        },
    }

    def validate(self, attrs):
        account_type = attrs.get("account_type", getattr(self.instance, "account_type", None))
        parent_account = attrs.get("parent_account", getattr(self.instance, "parent_account", None))

        if parent_account is not None:
            if not parent_account.is_header:
                raise serializers.ValidationError(
                    {"parent_account": "Parent account must be a header account."}
                )

            if account_type and parent_account.account_type != account_type:
                raise serializers.ValidationError(
                    {
                        "parent_account": (
                            f"Parent header account type ({parent_account.account_type}) must match child account type ({account_type})."
                        )
                    }
                )

        return attrs

    def _ensure_header_account(self, template_defaults):
        header_code = template_defaults["header_code"]
        header_name = template_defaults["header_name"]
        header_account = AccountingLedgerAccount.objects.filter(code=header_code).first()
        if header_account:
            return header_account

        return AccountingLedgerAccount.objects.create(
            code=header_code,
            name=header_name,
            account_type=template_defaults["account_type"],
            category=template_defaults.get("category", ""),
            normal_balance=template_defaults["normal_balance"],
            is_active=True,
            is_header=True,
            description=f"Auto-created header for {header_name}",
        )

    def _generate_code(self, validated_data):
        parent_account = validated_data.get("parent_account")
        if parent_account and str(parent_account.code).isdigit():
            base_code = int(parent_account.code)
            existing_codes = {
                int(account.code)
                for account in AccountingLedgerAccount.objects.filter(parent_account=parent_account)
                if str(account.code).isdigit()
            }
            next_code = base_code + 10
            while next_code in existing_codes:
                next_code += 10
            return str(next_code)

        type_prefix = {
            AccountingLedgerAccount.AccountType.ASSET: 1000,
            AccountingLedgerAccount.AccountType.LIABILITY: 2000,
            AccountingLedgerAccount.AccountType.EQUITY: 3000,
            AccountingLedgerAccount.AccountType.INCOME: 4000,
            AccountingLedgerAccount.AccountType.EXPENSE: 5000,
        }.get(validated_data.get("account_type"), 9000)

        existing_codes = {
            int(account.code)
            for account in AccountingLedgerAccount.objects.filter(account_type=validated_data.get("account_type"))
            if str(account.code).isdigit()
        }
        next_code = type_prefix + 10
        while next_code in existing_codes:
            next_code += 10
        return str(next_code)

    def create(self, validated_data):
        template_key = validated_data.pop("template_key", None)
        code = (validated_data.get("code") or "").strip()

        if template_key and template_key != "manual":
            template_defaults = self.TEMPLATE_DEFAULTS[template_key]
            validated_data.setdefault("account_type", template_defaults["account_type"])
            validated_data.setdefault("normal_balance", template_defaults["normal_balance"])
            validated_data.setdefault("category", template_defaults.get("category", ""))
            if not validated_data.get("name") and template_defaults.get("default_name"):
                validated_data["name"] = template_defaults["default_name"]
            if not validated_data.get("parent_account"):
                validated_data["parent_account"] = self._ensure_header_account(template_defaults)

        if not code:
            validated_data["code"] = self._generate_code(validated_data)
        else:
            validated_data["code"] = code

        return super().create(validated_data)

    def update(self, instance, validated_data):
        validated_data.pop("template_key", None)
        if "code" in validated_data and not str(validated_data.get("code") or "").strip():
            validated_data.pop("code")
        return super().update(instance, validated_data)

    class Meta:
        model = AccountingLedgerAccount
        fields = "__all__"


class AccountingJournalEntrySerializer(serializers.ModelSerializer):
    # Allow blank reference_number so it can be auto-generated in create()
    reference_number = serializers.CharField(max_length=100, required=False, allow_blank=True)

    def _generate_reference_number(self, posting_date):
        """Generate a unique reference number for journal entry."""
        # Format: JE-YYYYMMDD-XXXXX
        date_str = posting_date.strftime("%Y%m%d")
        prefix = f"JE-{date_str}-"
        
        # Find the last reference number for this date
        last_entry = AccountingJournalEntry.objects.filter(
            reference_number__startswith=prefix
        ).order_by("-reference_number").first()
        
        if last_entry:
            # Extract the counter from the last reference number
            last_counter = int(last_entry.reference_number.split("-")[-1])
            next_counter = last_counter + 1
        else:
            next_counter = 1
        
        return f"{prefix}{next_counter:05d}"

    def create(self, validated_data):
        posting_date = validated_data.get("posting_date")
        if posting_date is None:
            raise serializers.ValidationError({"posting_date": "Posting date is required"})

        # Auto-generate reference_number if empty or not provided
        reference_number = (validated_data.get("reference_number") or "").strip()
        if not reference_number:
            validated_data["reference_number"] = self._generate_reference_number(posting_date)

        validated_data["academic_year"] = _resolve_academic_year(posting_date)
        return super().create(validated_data)

    def update(self, instance, validated_data):
        posting_date = validated_data.get("posting_date")
        if posting_date is not None:
            validated_data["academic_year"] = _resolve_academic_year(posting_date)
        return super().update(instance, validated_data)

    class Meta:
        model = AccountingJournalEntry
        fields = "__all__"
        read_only_fields = ["academic_year"]


class AccountingJournalLineSerializer(serializers.ModelSerializer):
    ledger_account_name = serializers.CharField(source="ledger_account.name", read_only=True)
    ledger_account_code = serializers.CharField(source="ledger_account.code", read_only=True)
    currency_code = serializers.CharField(source="currency.code", read_only=True)

    class Meta:
        model = AccountingJournalLine
        fields = [
            "id",
            "journal_entry",
            "ledger_account",
            "ledger_account_name",
            "ledger_account_code",
            "currency",
            "currency_code",
            "amount",
            "debit_amount",
            "credit_amount",
            "exchange_rate",
            "base_amount",
            "description",
            "line_sequence",
            "created_at",
            "updated_at",
        ]


class AccountingJournalEntryListSerializer(serializers.ModelSerializer):
    total_debit = serializers.SerializerMethodField()
    total_credit = serializers.SerializerMethodField()

    def _resolve_total(self, obj, annotated_field: str, line_field: str) -> str:
        annotated_value = getattr(obj, annotated_field, None)
        if annotated_value is not None:
            return str(annotated_value)

        aggregated = obj.lines.aggregate(total=Sum(line_field))
        return str(aggregated.get("total") or Decimal("0.00"))

    def get_total_debit(self, obj):
        return self._resolve_total(obj, "total_debit_amount", "debit_amount")

    def get_total_credit(self, obj):
        return self._resolve_total(obj, "total_credit_amount", "credit_amount")

    class Meta:
        model = AccountingJournalEntry
        fields = [
            "id",
            "posting_date",
            "reference_number",
            "source",
            "description",
            "status",
            "academic_year",
            "posted_by",
            "posted_at",
            "reversal_of",
            "source_reference",
            "total_debit",
            "total_credit",
            "created_at",
            "updated_at",
        ]


class AccountingJournalEntryDetailSerializer(AccountingJournalEntryListSerializer):
    lines = AccountingJournalLineSerializer(many=True, read_only=True)

    class Meta(AccountingJournalEntryListSerializer.Meta):
        fields = AccountingJournalEntryListSerializer.Meta.fields + ["lines"]


class AccountingTransactionTypeSerializer(serializers.ModelSerializer):
    default_ledger_account_name = serializers.CharField(
        source="default_ledger_account.name", read_only=True
    )

    def validate(self, attrs):
        category = attrs.get(
            "transaction_category",
            getattr(self.instance, "transaction_category", None),
        )
        code = (
            attrs.get("code", getattr(self.instance, "code", "")) or ""
        ).strip().upper()
        default_ledger_account = attrs.get(
            "default_ledger_account",
            getattr(self.instance, "default_ledger_account", None),
        )

        is_transfer_code = code in {"TRANSFER_IN", "TRANSFER_OUT"}

        # Transfer in/out should map to an asset-side clearing account regardless of category label.
        if is_transfer_code:
            if default_ledger_account is None:
                raise serializers.ValidationError(
                    {
                        "default_ledger_account": (
                            "Default ledger account is required for TRANSFER_IN and TRANSFER_OUT transaction types."
                        )
                    }
                )

            if default_ledger_account.account_type != "asset":
                raise serializers.ValidationError(
                    {
                        "default_ledger_account": (
                            "TRANSFER_IN and TRANSFER_OUT transaction types must use an asset clearing ledger account."
                        )
                    }
                )

            return attrs

        if category in {"income", "expense"}:
            if default_ledger_account is None:
                raise serializers.ValidationError(
                    {
                        "default_ledger_account": (
                            "Default ledger account is required for income and expense transaction categories."
                        )
                    }
                )

            if default_ledger_account.account_type != category:
                raise serializers.ValidationError(
                    {
                        "default_ledger_account": (
                            f"Selected ledger account type ({default_ledger_account.account_type}) does not match transaction category ({category})."
                        )
                    }
                )

        return attrs

    class Meta:
        model = AccountingTransactionType
        fields = [
            "id",
            "name",
            "code",
            "transaction_category",
            "description",
            "default_ledger_account",
            "default_ledger_account_name",
            "is_active",
        ]


class AccountingPaymentMethodSerializer(serializers.ModelSerializer):
    class Meta:
        model = AccountingPaymentMethod
        fields = ["id", "name", "code", "description", "is_active"]


class AccountingBankAccountSerializer(serializers.ModelSerializer):
    currency = serializers.PrimaryKeyRelatedField(queryset=AccountingCurrency.objects.all())

    class Meta:
        model = AccountingBankAccount
        fields = [
            "id",
            "account_number",
            "account_name",
            "bank_name",
            "account_type",
            "currency",
            "ledger_account",
            "opening_balance",
            "opening_balance_date",
            "current_balance",
            "status",
            "description",
            "created_at",
            "updated_at",
        ]

    def to_internal_value(self, data):
        payload = data.copy() if hasattr(data, "copy") else dict(data)
        currency_value = payload.get("currency")
        if isinstance(currency_value, dict):
            payload["currency"] = currency_value.get("id")
        return super().to_internal_value(payload)

    def validate(self, attrs):
        ledger_account = attrs.get("ledger_account")
        currency = attrs.get("currency")

        if self.instance is not None:
            ledger_account = ledger_account if "ledger_account" in attrs else self.instance.ledger_account
            currency = currency if "currency" in attrs else self.instance.currency

        if ledger_account is None or currency is None:
            return attrs

        if ledger_account.account_type != AccountingLedgerAccount.AccountType.ASSET:
            raise serializers.ValidationError(
                {
                    "ledger_account": (
                        "Bank accounts can only be linked to asset ledger accounts."
                    )
                }
            )

        conflicting_accounts = AccountingBankAccount.objects.filter(
            ledger_account=ledger_account,
        ).exclude(currency=currency)

        if self.instance is not None:
            conflicting_accounts = conflicting_accounts.exclude(pk=self.instance.pk)

        if conflicting_accounts.exists():
            conflict = conflicting_accounts.select_related("currency").first()
            raise serializers.ValidationError(
                {
                    "ledger_account": (
                        f"Ledger account '{ledger_account.code} - {ledger_account.name}' is already linked "
                        f"to bank account '{conflict.account_name}' in currency '{conflict.currency.code}'. "
                        "Use a separate ledger account per currency (e.g. BANK-USD, BANK-XOF)."
                    )
                }
            )

        return attrs
    
    def to_representation(self, instance):
        response = super().to_representation(instance)
        response["currency"] = AccountingCurrencySerializer(instance.currency).data
        return response


class AccountingBankAccountRecentActivitySerializer(serializers.ModelSerializer):
    transaction_type = serializers.SerializerMethodField()
    payment_method = serializers.SerializerMethodField()
    posted = serializers.SerializerMethodField()

    class Meta:
        model = AccountingCashTransaction
        fields = [
            "id",
            "transaction_date",
            "reference_number",
            "transaction_type",
            "payment_method",
            "amount",
            "base_amount",
            "status",
            "payer_payee",
            "description",
            "journal_entry",
            "posted",
            "created_at",
        ]

    def get_transaction_type(self, obj):
        if obj.transaction_type_id is None:
            return None
        return AccountingTransactionTypeNestedSerializer(obj.transaction_type).data

    def get_payment_method(self, obj):
        if obj.payment_method_id is None:
            return None
        return AccountingPaymentMethodNestedSerializer(obj.payment_method).data

    def get_posted(self, obj):
        return bool(obj.journal_entry_id)


class AccountingBankAccountDetailSerializer(AccountingBankAccountSerializer):
    recent_activities = serializers.SerializerMethodField()
    opening_amount = serializers.DecimalField(max_digits=18, decimal_places=2, source="opening_balance", read_only=True)
    total_income = serializers.SerializerMethodField()
    total_expense = serializers.SerializerMethodField()
    net_balance = serializers.SerializerMethodField()
    activity_breakdown = serializers.SerializerMethodField()
    monthly_activity = serializers.SerializerMethodField()
    ledger_account_detail = serializers.SerializerMethodField()

    class Meta(AccountingBankAccountSerializer.Meta):
        fields = AccountingBankAccountSerializer.Meta.fields + [
            "opening_amount",
            "total_income",
            "total_expense",
            "net_balance",
            "activity_breakdown",
            "monthly_activity",
            "recent_activities",
            "ledger_account_detail",
        ]

    def _build_metrics(self, instance) -> dict[str, Any]:
        cached = getattr(instance, "_bank_account_detail_metrics", None)
        if cached is not None:
            return cached

        approved_tx = instance.transactions.filter(status=AccountingCashTransaction.TransactionStatus.APPROVED)

        total_income = (
            approved_tx.filter(transaction_type__transaction_category="income").aggregate(
                total=Sum("base_amount")
            )["total"]
            or Decimal("0")
        )
        total_expense = (
            approved_tx.filter(transaction_type__transaction_category="expense").aggregate(
                total=Sum("base_amount")
            )["total"]
            or Decimal("0")
        )

        opening_amount = instance.opening_balance or Decimal("0")
        net_balance = opening_amount + total_income - total_expense

        monthly_rows = (
            approved_tx.annotate(month=TruncMonth("transaction_date"))
            .values("month")
            .annotate(
                income=Sum("base_amount", filter=Q(transaction_type__transaction_category="income")),
                expense=Sum("base_amount", filter=Q(transaction_type__transaction_category="expense")),
            )
            .order_by("month")
        )
        monthly_activity = [
            {
                "month": row["month"].strftime("%b %Y") if row.get("month") else "",
                "income": str(row.get("income") or Decimal("0")),
                "expense": str(row.get("expense") or Decimal("0")),
            }
            for row in monthly_rows
        ]

        activity_breakdown = {
            "approved": instance.transactions.filter(
                status=AccountingCashTransaction.TransactionStatus.APPROVED
            ).count(),
            "pending": instance.transactions.filter(
                status=AccountingCashTransaction.TransactionStatus.PENDING
            ).count(),
            "rejected": instance.transactions.filter(
                status=AccountingCashTransaction.TransactionStatus.REJECTED
            ).count(),
        }

        recent_qs = (
            instance.transactions.select_related("transaction_type", "payment_method")
            .order_by("-transaction_date", "-created_at")[:5]
        )
        recent_activities = AccountingBankAccountRecentActivitySerializer(recent_qs, many=True).data

        metrics = {
            "opening_amount": opening_amount,
            "total_income": total_income,
            "total_expense": total_expense,
            "net_balance": net_balance,
            "activity_breakdown": activity_breakdown,
            "monthly_activity": monthly_activity,
            "recent_activities": recent_activities,
        }
        setattr(instance, "_bank_account_detail_metrics", metrics)
        return metrics

    def get_opening_amount(self, obj):
        return self._build_metrics(obj)["opening_amount"]

    def get_total_income(self, obj):
        return self._build_metrics(obj)["total_income"]

    def get_total_expense(self, obj):
        return self._build_metrics(obj)["total_expense"]

    def get_net_balance(self, obj):
        return self._build_metrics(obj)["net_balance"]

    def get_activity_breakdown(self, obj):
        return self._build_metrics(obj)["activity_breakdown"]

    def get_monthly_activity(self, obj):
        return self._build_metrics(obj)["monthly_activity"]

    def get_recent_activities(self, obj):
        return self._build_metrics(obj)["recent_activities"]

    def get_ledger_account_detail(self, obj):
        if obj.ledger_account_id is None:
            return None
        ledger = obj.ledger_account
        return {
            "id": str(ledger.id),
            "code": ledger.code,
            "name": ledger.name,
            "account_type": ledger.account_type,
            "normal_balance": ledger.normal_balance,
        }



class AccountingCashTransactionSerializer(serializers.ModelSerializer):
    def _generate_reference_number(self, transaction_date):
        """Generate a unique reference number for cash transaction."""
        # Format: TXN-YYYYMMDD-XXXXX
        date_str = transaction_date.strftime("%Y%m%d")
        prefix = f"TXN-{date_str}-"
        
        # Find the last reference number for this date
        last_entry = AccountingCashTransaction.objects.filter(
            reference_number__startswith=prefix
        ).order_by("-reference_number").first()
        
        if last_entry:
            # Extract the counter from the last reference number
            last_counter = int(last_entry.reference_number.split("-")[-1])
            next_counter = last_counter + 1
        else:
            next_counter = 1
        
        return f"{prefix}{next_counter:05d}"

    # Allow blank reference_number so it can be auto-generated in create()
    reference_number = serializers.CharField(max_length=100, required=False, allow_blank=True)
    # Optional: when omitted, validate() derives from amount * exchange_rate (or amount when rate missing).
    base_amount = serializers.DecimalField(max_digits=18, decimal_places=2, required=False)

    # Write-only FK inputs (accept UUIDs from clients).
    bank_account_id = serializers.PrimaryKeyRelatedField(
        source="bank_account",
        queryset=AccountingBankAccount.objects.all(),
        write_only=True,
    )
    transaction_type_id = serializers.PrimaryKeyRelatedField(
        source="transaction_type",
        queryset=AccountingTransactionType.objects.all(),
        write_only=True,
    )
    payment_method_id = serializers.PrimaryKeyRelatedField(
        source="payment_method",
        queryset=AccountingPaymentMethod.objects.all(),
        write_only=True,
    )
    currency_id = serializers.PrimaryKeyRelatedField(
        source="currency",
        queryset=AccountingCurrency.objects.all(),
        write_only=True,
    )
    ledger_account_id = serializers.PrimaryKeyRelatedField(
        source="ledger_account",
        queryset=AccountingLedgerAccount.objects.all(),
        required=False,
        allow_null=True,
        write_only=True,
    )

    # Nested serializers for FK fields (output only, resolved objects)
    bank_account = serializers.SerializerMethodField()
    transaction_type = serializers.SerializerMethodField()
    payment_method = serializers.SerializerMethodField()
    currency = serializers.SerializerMethodField()
    ledger_account = serializers.SerializerMethodField()
    journal_entry = serializers.SerializerMethodField()

    class Meta:
        model = AccountingCashTransaction
        fields = [
            "id",
            "bank_account_id",
            "bank_account",
            "transaction_date",
            "reference_number",
            "transaction_type_id",
            "transaction_type",
            "payment_method_id",
            "payment_method",
            "ledger_account_id",
            "ledger_account",
            "amount",
            "currency_id",
            "currency",
            "exchange_rate",
            "base_amount",
            "payer_payee",
            "description",
            "status",
            "approved_by",
            "approved_at",
            "rejection_reason",
            "source_reference",
            "journal_entry",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["journal_entry", "created_at", "updated_at"]

    def create(self, validated_data):
        transaction_date = validated_data.get("transaction_date")
        
        # Auto-generate reference_number if empty or not provided
        reference_number = (validated_data.get("reference_number") or "").strip()
        if not reference_number:
            validated_data["reference_number"] = self._generate_reference_number(transaction_date)
        
        return super().create(validated_data)

    def get_bank_account(self, obj):
        if obj.bank_account_id is None:
            return None
        return AccountingBankAccountNestedSerializer(obj.bank_account).data

    def get_transaction_type(self, obj):
        if obj.transaction_type_id is None:
            return None
        return AccountingTransactionTypeNestedSerializer(obj.transaction_type).data

    def get_payment_method(self, obj):
        if obj.payment_method_id is None:
            return None
        return AccountingPaymentMethodNestedSerializer(obj.payment_method).data

    def get_currency(self, obj):
        if obj.currency_id is None:
            return None
        return AccountingCurrencySerializer(obj.currency).data

    def get_ledger_account(self, obj):
        if obj.ledger_account_id is None:
            return None
        return AccountingLedgerAccountNestedSerializer(obj.ledger_account).data

    def get_journal_entry(self, obj):
        if obj.journal_entry_id is None:
            return None
        return {
            "id": str(obj.journal_entry_id),
            "reference_number": obj.journal_entry.reference_number,
            "posting_date": obj.journal_entry.posting_date,
            "status": obj.journal_entry.status,
        }

    def to_internal_value(self, data):
        """Accept FK IDs in input, convert them to use the standard FK field names."""
        payload = data.copy() if hasattr(data, "copy") else dict(data)

        # Handle bank_account
        bank_account_value = payload.get("bank_account")
        if isinstance(bank_account_value, dict):
            payload["bank_account"] = bank_account_value.get("id")
        if payload.get("bank_account") is not None and payload.get("bank_account_id") is None:
            payload["bank_account_id"] = payload.get("bank_account")

        # Handle transaction_type
        transaction_type_value = payload.get("transaction_type")
        if isinstance(transaction_type_value, dict):
            payload["transaction_type"] = transaction_type_value.get("id")
        if payload.get("transaction_type") is not None and payload.get("transaction_type_id") is None:
            payload["transaction_type_id"] = payload.get("transaction_type")

        # Handle payment_method
        payment_method_value = payload.get("payment_method")
        if isinstance(payment_method_value, dict):
            payload["payment_method"] = payment_method_value.get("id")
        if payload.get("payment_method") is not None and payload.get("payment_method_id") is None:
            payload["payment_method_id"] = payload.get("payment_method")

        # Handle currency
        currency_value = payload.get("currency")
        if isinstance(currency_value, dict):
            payload["currency"] = currency_value.get("id")
        if payload.get("currency") is not None and payload.get("currency_id") is None:
            payload["currency_id"] = payload.get("currency")

        # Handle ledger_account
        ledger_account_value = payload.get("ledger_account")
        if isinstance(ledger_account_value, dict):
            payload["ledger_account"] = ledger_account_value.get("id")
        if payload.get("ledger_account") is not None and payload.get("ledger_account_id") is None:
            payload["ledger_account_id"] = payload.get("ledger_account")

        return super().to_internal_value(payload)

    def validate(self, attrs):
        exchange_rate = attrs.get("exchange_rate")
        amount = attrs.get("amount")
        base_amount = attrs.get("base_amount")

        if exchange_rate is not None and exchange_rate <= 0:
            raise serializers.ValidationError({"exchange_rate": "Exchange rate must be greater than zero"})

        if amount is not None and amount <= 0:
            raise serializers.ValidationError({"amount": "Amount must be greater than zero"})

        # If base_amount is omitted, derive from amount and exchange_rate.
        if base_amount is None and amount is not None:
            rate = exchange_rate if exchange_rate is not None else Decimal("1")
            attrs["base_amount"] = amount * rate

        return attrs


class AccountingBankAccountNestedSerializer(serializers.ModelSerializer):
    """Lightweight nested serializer for bank account in responses."""
    class Meta:
        model = AccountingBankAccount
        fields = ["id", "account_number", "account_name", "bank_name", "account_type", "status"]


class AccountingTransactionTypeNestedSerializer(serializers.ModelSerializer):
    """Lightweight nested serializer for transaction type in responses."""
    class Meta:
        model = AccountingTransactionType
        fields = ["id", "name", "code", "transaction_category", "description"]


class AccountingPaymentMethodNestedSerializer(serializers.ModelSerializer):
    """Lightweight nested serializer for payment method in responses."""
    class Meta:
        model = AccountingPaymentMethod
        fields = ["id", "name", "code", "description"]


class AccountingLedgerAccountNestedSerializer(serializers.ModelSerializer):
    """Lightweight nested serializer for ledger account in responses."""
    class Meta:
        model = AccountingLedgerAccount
        fields = ["id", "code", "name", "account_type"]

class AccountingAccountTransferSerializer(serializers.ModelSerializer):
    def _generate_reference_number(self, transfer_date):
        """Generate a unique reference number for account transfer."""
        # Format: TRF-YYYYMMDD-XXXXX
        date_str = transfer_date.strftime("%Y%m%d")
        prefix = f"TRF-{date_str}-"

        last_entry = AccountingAccountTransfer.objects.filter(
            reference_number__startswith=prefix
        ).order_by("-reference_number").first()

        if last_entry:
            last_counter = int(last_entry.reference_number.split("-")[-1])
            next_counter = last_counter + 1
        else:
            next_counter = 1

        return f"{prefix}{next_counter:05d}"

    # Allow blank reference_number so it can be auto-generated in create()
    reference_number = serializers.CharField(max_length=100, required=False, allow_blank=True)
    # Optional on input; derived from amount * exchange_rate when omitted.
    to_amount = serializers.DecimalField(max_digits=18, decimal_places=2, required=False)

    # Write-only FK inputs (accept UUIDs from clients)
    from_account_id = serializers.PrimaryKeyRelatedField(
        source="from_account",
        queryset=AccountingBankAccount.objects.all(),
        write_only=True,
    )
    to_account_id = serializers.PrimaryKeyRelatedField(
        source="to_account",
        queryset=AccountingBankAccount.objects.all(),
        write_only=True,
    )
    from_currency_id = serializers.PrimaryKeyRelatedField(
        source="from_currency",
        queryset=AccountingCurrency.objects.all(),
        write_only=True,
    )
    to_currency_id = serializers.PrimaryKeyRelatedField(
        source="to_currency",
        queryset=AccountingCurrency.objects.all(),
        write_only=True,
    )

    from_account = serializers.SerializerMethodField()
    to_account = serializers.SerializerMethodField()
    from_currency = serializers.SerializerMethodField()
    to_currency = serializers.SerializerMethodField()

    class Meta:
        model = AccountingAccountTransfer
        fields = [
            "id",
            "transfer_date",
            "reference_number",
            "from_account_id",
            "from_account",
            "to_account_id",
            "to_account",
            "amount",
            "from_currency_id",
            "from_currency",
            "to_currency_id",
            "to_currency",
            "exchange_rate",
            "to_amount",
            "status",
            "description",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def get_from_account(self, obj):
        if obj.from_account_id is None:
            return None
        return AccountingBankAccountNestedSerializer(obj.from_account).data

    def get_to_account(self, obj):
        if obj.to_account_id is None:
            return None
        return AccountingBankAccountNestedSerializer(obj.to_account).data

    def get_from_currency(self, obj):
        if obj.from_currency_id is None:
            return None
        return AccountingCurrencySerializer(obj.from_currency).data

    def get_to_currency(self, obj):
        if obj.to_currency_id is None:
            return None
        return AccountingCurrencySerializer(obj.to_currency).data

    def to_internal_value(self, data):
        """Accept FK IDs in input, convert them for standard FK field names."""
        payload = data.copy() if hasattr(data, "copy") else dict(data)

        # Handle from_account
        from_account_value = payload.get("from_account")
        if isinstance(from_account_value, dict):
            payload["from_account"] = from_account_value.get("id")
        if payload.get("from_account") is not None and payload.get("from_account_id") is None:
            payload["from_account_id"] = payload.get("from_account")

        # Handle to_account
        to_account_value = payload.get("to_account")
        if isinstance(to_account_value, dict):
            payload["to_account"] = to_account_value.get("id")
        if payload.get("to_account") is not None and payload.get("to_account_id") is None:
            payload["to_account_id"] = payload.get("to_account")

        # Handle from_currency
        from_currency_value = payload.get("from_currency")
        if isinstance(from_currency_value, dict):
            payload["from_currency"] = from_currency_value.get("id")
        if payload.get("from_currency") is not None and payload.get("from_currency_id") is None:
            payload["from_currency_id"] = payload.get("from_currency")

        # Handle to_currency
        to_currency_value = payload.get("to_currency")
        if isinstance(to_currency_value, dict):
            payload["to_currency"] = to_currency_value.get("id")
        if payload.get("to_currency") is not None and payload.get("to_currency_id") is None:
            payload["to_currency_id"] = payload.get("to_currency")

        return super().to_internal_value(payload)

    def validate(self, attrs):
        amount = attrs.get("amount")
        exchange_rate = attrs.get("exchange_rate")
        to_amount = attrs.get("to_amount")

        if amount is not None and amount <= 0:
            raise serializers.ValidationError({"amount": "Amount must be greater than zero"})

        if exchange_rate is not None and exchange_rate <= 0:
            raise serializers.ValidationError({"exchange_rate": "Exchange rate must be greater than zero"})

        if to_amount is None and amount is not None:
            rate = exchange_rate if exchange_rate is not None else Decimal("1")
            attrs["to_amount"] = amount * rate

        return attrs

    def create(self, validated_data):
        transfer_date = validated_data.get("transfer_date")

        reference_number = (validated_data.get("reference_number") or "").strip()
        if not reference_number:
            validated_data["reference_number"] = self._generate_reference_number(transfer_date)

        return super().create(validated_data)


class AccountingFeeItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = AccountingFeeItem
        fields = "__all__"


class AccountingFeeRateSerializer(serializers.ModelSerializer):
    class Meta:
        model = AccountingFeeRate
        fields = "__all__"


class AccountingStudentBillSerializer(serializers.ModelSerializer):
    class Meta:
        model = AccountingStudentBill
        fields = "__all__"


class AccountingStudentBillLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = AccountingStudentBillLine
        fields = "__all__"


class AccountingConcessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = AccountingConcession
        fields = "__all__"


class AccountingInstallmentPlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = AccountingInstallmentPlan
        fields = "__all__"


class AccountingInstallmentLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = AccountingInstallmentLine
        fields = "__all__"


class AccountingStudentPaymentAllocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = AccountingStudentPaymentAllocation
        fields = "__all__"


class AccountingARSnapshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = AccountingARSnapshot
        fields = "__all__"


class AccountingTaxCodeSerializer(serializers.ModelSerializer):
    class Meta:
        model = AccountingTaxCode
        fields = "__all__"


class AccountingTaxRemittanceSerializer(serializers.ModelSerializer):
    class Meta:
        model = AccountingTaxRemittance
        fields = "__all__"


class AccountingExpenseRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = AccountingExpenseRecord
        fields = "__all__"


class AccountingPayrollPostingBatchSerializer(serializers.ModelSerializer):
    class Meta:
        model = AccountingPayrollPostingBatch
        fields = "__all__"


class AccountingPayrollPostingLineSerializer(serializers.ModelSerializer):
    class Meta:
        model = AccountingPayrollPostingLine
        fields = "__all__"
