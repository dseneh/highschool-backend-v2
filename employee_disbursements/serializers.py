from rest_framework import serializers

from employee_disbursements.models import EmployeeDisbursementRecord


class EmployeeDisbursementRecordListSerializer(serializers.ModelSerializer):
    employee_display = serializers.SerializerMethodField()
    currency_code = serializers.CharField(source="currency.code", read_only=True, default=None)
    source_type_label = serializers.CharField(source="get_source_type_display", read_only=True)

    class Meta:
        model = EmployeeDisbursementRecord
        fields = [
            "id",
            "source_type",
            "source_type_label",
            "source_id",
            "payroll_employee_item",
            "benefit_request_line",
            "employee",
            "employee_display",
            "status",
            "paid_at",
            "reverted_at",
            "payment_date",
            "period_start",
            "period_end",
            "title",
            "reference_number",
            "currency",
            "currency_code",
            "net_amount",
            "gross_amount",
            "benefit_type_name",
            "created_at",
        ]
        read_only_fields = fields

    def get_employee_display(self, obj):
        employee = obj.employee
        return {
            "id": str(employee.id),
            "name": employee.get_full_name().strip() or employee.id_number,
            "id_number": employee.id_number,
            "department_name": getattr(employee.department, "name", None),
            "position_title": getattr(employee.position, "title", None),
        }


class EmployeeDisbursementRecordDetailSerializer(EmployeeDisbursementRecordListSerializer):
    snapshot = serializers.JSONField(read_only=True)

    class Meta(EmployeeDisbursementRecordListSerializer.Meta):
        fields = EmployeeDisbursementRecordListSerializer.Meta.fields + ["snapshot", "journal_entry"]
