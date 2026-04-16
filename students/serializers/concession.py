from datetime import date

from rest_framework import serializers

from accounting.models import AccountingConcession


class StudentConcessionSerializer(serializers.ModelSerializer):
    amount = serializers.SerializerMethodField()
    active = serializers.BooleanField(source="is_active")

    class Meta:
        model = AccountingConcession
        fields = [
            "id",
            "student",
            "academic_year",
            "concession_type",
            "target",
            "value",
            "start_date",
            "end_date",
            "amount",
            "notes",
            "active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "amount", "created_at", "updated_at", "student"]
        extra_kwargs = {
            "start_date": {"required": False, "allow_null": True},
            "end_date": {"required": False, "allow_null": True},
        }

    def validate(self, attrs):
        concession_type = attrs.get("concession_type", getattr(self.instance, "concession_type", None))
        value = attrs.get("value", getattr(self.instance, "value", None))

        if concession_type == AccountingConcession.ConcessionType.PERCENTAGE and value is not None:
            if value <= 0 or value > 100:
                raise serializers.ValidationError(
                    {"value": "Percentage concession value must be between 0 and 100."}
                )

        if concession_type == AccountingConcession.ConcessionType.FLAT and value is not None and value <= 0:
            raise serializers.ValidationError(
                {"value": "Flat concession value must be greater than 0."}
            )

        start_date = attrs.get("start_date", getattr(self.instance, "start_date", None))
        end_date = attrs.get("end_date", getattr(self.instance, "end_date", None))
        if start_date and end_date and end_date < start_date:
            raise serializers.ValidationError(
                {"end_date": "End date cannot be earlier than start date."}
            )

        return attrs

    def create(self, validated_data):
        if not validated_data.get("start_date"):
            academic_year = validated_data.get("academic_year")
            validated_data["start_date"] = (
                academic_year.start_date if academic_year and getattr(academic_year, "start_date", None) else date.today()
            )
        return super().create(validated_data)

    def get_amount(self, instance):
        return float(instance.computed_amount)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["student"] = {
            "id": str(instance.student.id),
            "id_number": instance.student.id_number,
            "full_name": instance.student.get_full_name(),
        }
        data["academic_year"] = {
            "id": str(instance.academic_year.id),
            "name": instance.academic_year.name,
            "current": instance.academic_year.current,
        }
        return data
