from urllib import response

from django.db import models
from rest_framework import serializers

from students.serializers.student import StudentSerializer

from .models import (
    BankAccount,
    Currency,
    GeneralFeeList,
    PaymentInstallment,
    PaymentMethod,
    SectionFee,
    Transaction,
    TransactionType,
)


class BankAccountSerializer(serializers.ModelSerializer):
    """Basic serializer for bank account list views"""

    class Meta:
        model = BankAccount
        fields = [
            "id",
            "number",
            "name",
            "description",
            "active",
        ]

    def __init__(self, *args, **kwargs):
        # Extract context to check if analysis should be included
        self.include_analysis = kwargs.pop("include_analysis", False)
        self.include_basic_analysis = kwargs.pop("include_basic_analysis", False)
        super().__init__(*args, **kwargs)

    def to_representation(self, instance):
        response = super().to_representation(instance)
        currency = Currency.objects.first()
        response["currency"] = {
            "id": currency.id,
            "name": currency.name,
            "symbol": currency.symbol,
            "code": currency.code,
        }
        response["status"] = "active" if instance.active else "disabled"

        # Always include basic balance
        response["balance"] = float(f"{instance.balance:.2f}")

        # Include analysis based on request parameters
        if self.include_analysis:
            # Full detailed analysis for dashboard views
            response["analysis"] = instance.get_analysis()
        elif self.include_basic_analysis:
            # Basic analysis with just totals for list views
            response["basic_analysis"] = instance.get_basic_analysis()

        return response


class BankAccountDetailSerializer(BankAccountSerializer):
    """Detailed serializer for bank account detail views"""

    class Meta(BankAccountSerializer.Meta):
        fields = BankAccountSerializer.Meta.fields + [
            # "meta",
        ]

    def to_representation(self, instance):
        response = super().to_representation(instance)

        # Get last 10 transactions ordered by date (most recent first) - database level limit
        recent_transactions = instance.transactions.select_related(
            "type", "payment_method", "student", "academic_year"
        ).order_by("-date", "-created_at")[:10]
        transactions = TransactionSerializer(recent_transactions, many=True).data
        response["transactions"] = transactions

        return response


class GeneralFeeSerializer(serializers.ModelSerializer):
    """Basic serializer for general fee list views"""

    class Meta:
        model = GeneralFeeList
        fields = [
            "id",
            "name",
            "description",
            "amount",
            "student_target",
            "active",
        ]

    def to_representation(self, instance):
        response = super().to_representation(instance)
        response["amount"] = float(f"{instance.amount:.2f}")
        response["status"] = "active" if instance.active else "disabled"

        return response


class SectionFeeSerializer(serializers.ModelSerializer):
    """Basic serializer for section fee list views"""

    class Meta:
        model = SectionFee
        fields = [
            "id",
            "section",
            "general_fee",
            "amount",
            "active",
        ]

    def to_representation(self, instance):
        response = super().to_representation(instance)

        response["section"] = {
            "id": instance.section.id,
            "name": instance.section.name,
        }
        response["general_fee"] = {
            "id": instance.general_fee.id,
            "name": instance.general_fee.name,
            "student_target": instance.general_fee.student_target,
        }
        response["status"] = "active" if instance.active else "disabled"
        response["amount"] = float(f"{instance.amount:.2f}")

        return response


class SectionFeeDetailSerializer(serializers.ModelSerializer):
    """Detailed serializer for section fee detail views"""

    class Meta:
        model = SectionFee
        fields = [
            "id",
            "section",
            "general_fee",
            "amount",
        ]

    def to_representation(self, instance):
        response = super().to_representation(instance)

        response["section"] = {
            "id": instance.section.id,
            "name": instance.section.name,
            "grade_level": (
                getattr(instance.section.grade_level, "name", "")
                if instance.section.grade_level
                else ""
            ),
        }
        response["general_fee"] = {
            "id": instance.general_fee.id,
            "name": instance.general_fee.name,
            "description": instance.general_fee.description,
        }
        response["amount"] = f"{float(instance.amount):.2f}"

        return response


class TransactionTypeSerializer(serializers.ModelSerializer):
    """Basic serializer for transaction type list views"""

    class Meta:
        model = TransactionType
        fields = [
            "id",
            "name",
            "type",
            "type_code",
            "is_hidden",
            "is_editable",
            "description",
            "active",
        ]

    def to_representation(self, instance):
        response = super().to_representation(instance)
        response["status"] = "active" if instance.active else "disabled"
        return response


class TransactionTypeDetailSerializer(TransactionTypeSerializer):
    class Meta(TransactionTypeSerializer.Meta):
        fields = TransactionTypeSerializer.Meta.fields + [
            "meta",
        ]


class PaymentMethodSerializer(serializers.ModelSerializer):
    """Basic serializer for payment method list views"""

    class Meta:
        model = PaymentMethod
        fields = ["id", "name", "description", "is_editable", "active"]

    def to_representation(self, instance):
        response = super().to_representation(instance)
        response["status"] = "active" if instance.active else "disabled"
        return response


class PaymentMethodDetailSerializer(PaymentMethodSerializer):
    class Meta(PaymentMethodSerializer.Meta):
        fields = PaymentMethodSerializer.Meta.fields + [
            "meta",
        ]


class CurrencySerializer(serializers.ModelSerializer):
    """Basic serializer for payment method list views"""

    class Meta:
        model = Currency
        fields = [
            "id",
            "name",
            "symbol",
            "code",
            "meta",
        ]

    def to_representation(self, instance):
        response = super().to_representation(instance)
        return response


class TransactionSerializer(serializers.ModelSerializer):
    """Basic serializer for transaction list views"""

    class Meta:
        model = Transaction
        fields = [
            "id",
            "type",
            "student",
            "transaction_id",
            "reference",
            "amount",
            "payment_method",
            "status",
            "description",
            "date",
            "meta",
        ]

    def to_representation(self, instance):
        response = super().to_representation(instance)
        if instance.student:
            response["student"] = {
                "id": instance.student.id,
                "id_number": instance.student.id_number,
                "full_name": instance.student.get_full_name(),
            }
        response["transaction_type"] = {
            "id": instance.type.id,
            "name": instance.type.name,
            "type_code": instance.type.type_code,
            "type": instance.type.type,
        }
        response["payment_method"] = {
            "id": instance.payment_method.id,
            "name": instance.payment_method.name,
        }
        response["account"] = {
            "id": instance.account.id,
            "number": instance.account.number,
            "name": instance.account.name,
        }
        response["academic_year"] = {
            "id": instance.academic_year.id,
            "name": instance.academic_year.name,
        }
        currency = Currency.objects.first()
        response["currency"] = {
            "id": currency.id,
            "name": currency.name,
            "symbol": currency.symbol,
            "code": currency.code,
        }
        response["amount"] = float(f"{instance.amount:.2f}")

        return response


class TransactionStudentSerializer(TransactionSerializer):
    """Basic serializer for transaction list views"""

    class Meta(TransactionSerializer.Meta):
        fields = TransactionSerializer.Meta.fields + []

    def to_representation(self, instance):
        response = super().to_representation(instance)
        if instance.student:
            enrollment = (
                instance.student.enrollments.select_related(
                    "grade_level",
                    "section",
                    "academic_year",
                )
                .only(
                    "grade_level__id",
                    "grade_level__name",
                    "section__id",
                    "section__name",
                    "academic_year__id",
                    "academic_year__name",
                    "academic_year__start_date",
                    "academic_year__end_date",
                )
                .order_by("-academic_year__start_date")
                .first()
            )

            if enrollment:
                grade_level = (
                    {
                        "id": enrollment.grade_level.id,
                        "name": enrollment.grade_level.name,
                    }
                    if enrollment.grade_level
                    else None
                )
                section = (
                    {
                        "id": enrollment.section.id,
                        "name": enrollment.section.name,
                    }
                    if enrollment.section
                    else None
                )

            # Get payment plan and payment status for the enrollment
            payment_plan = []
            payment_status = {
                "is_on_time": True,
                "overdue_count": 0,
                "overdue_amount": 0.0,
                "next_due_date": None,
            }
            if enrollment:
                from finance.models import (
                    get_student_payment_plan,
                    get_student_payment_status,
                )

                payment_plan = get_student_payment_plan(enrollment)
                payment_status = get_student_payment_status(enrollment)

            response["student"] = {
                "id": instance.student.id,
                "id_number": instance.student.id_number,
                "full_name": instance.student.get_full_name(),
                "grade_level": grade_level if enrollment else None,
                "section": section if enrollment else None,
                "academic_year": (
                    {
                        "id": enrollment.academic_year.id,
                        "name": enrollment.academic_year.name,
                    }
                    if enrollment.academic_year
                    else None
                ),
                "enrolled_as": enrollment.enrolled_as if enrollment else None,
                "balance": instance.student.balance_due,
                "payment_plan": payment_plan,
                "payment_status": payment_status,
            }

        return response


class TransactionDetailSerializer(TransactionSerializer):
    """Detailed serializer for transaction detail views"""

    class Meta(TransactionSerializer.Meta):
        fields = TransactionSerializer.Meta.fields + [
            "meta",
        ]


class PaymentInstallmentSerializer(serializers.ModelSerializer):
    """Basic serializer for payment installment list views"""

    class Meta:
        model = PaymentInstallment
        fields = [
            "id",
            "academic_year",
            "name",
            "description",
            "value",
            "due_date",
            "sequence",
            "active",
        ]

    def to_representation(self, instance):
        response = super().to_representation(instance)
        response["academic_year"] = {
            "id": instance.academic_year.id,
            "name": instance.academic_year.name,
            "start_date": instance.academic_year.start_date.isoformat(),
            "end_date": instance.academic_year.end_date.isoformat(),
        }

        # value is individual percentage
        individual_percentage = float(f"{instance.value:.2f}")
        response["percentage"] = individual_percentage
        response["value"] = individual_percentage  # Keep for backward compatibility

        # Calculate cumulative percentage up to this installment
        # OPTIMIZATION: Use pre-calculated cumulative from context if available
        # This eliminates N queries (one per installment)
        cumulative_map = self.context.get("cumulative_percentages", {})

        if instance.id in cumulative_map:
            # Use pre-calculated value from view (fastest - O(1) lookup)
            cumulative_percentage = cumulative_map[instance.id]
        elif instance.sequence is not None:
            # Fallback: calculate on-demand (for single installment views)
            # Cache cumulative percentage calculation (expensive query)
            from django.core.cache import cache

            cache_key = f"payment_installment:cumulative:{instance.academic_year.id}:{instance.sequence}"
            cumulative_percentage = cache.get(cache_key)

            if cumulative_percentage is None:
                cumulative_percentage = (
                    PaymentInstallment.objects.filter(
                        academic_year=instance.academic_year,
                        active=True,
                        sequence__lte=instance.sequence,
                    ).aggregate(total=models.Sum("value"))["total"]
                    or 0.0
                )
                # Cache for 24 hours (installments rarely change)
                cache.set(cache_key, cumulative_percentage, 86400)
        else:
            # If sequence is None, just use this installment's value
            cumulative_percentage = float(instance.value)

        response["cumulative_percentage"] = float(f"{cumulative_percentage:.2f}")
        response["due_date"] = instance.due_date.isoformat()
        response["status"] = "active" if instance.active else "disabled"

        return response


class PaymentInstallmentDetailSerializer(PaymentInstallmentSerializer):
    """Detailed serializer for payment installment detail views"""

    class Meta(PaymentInstallmentSerializer.Meta):
        fields = PaymentInstallmentSerializer.Meta.fields + [
            "meta",
        ]
