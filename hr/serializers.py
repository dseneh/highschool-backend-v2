from django.utils import timezone
from rest_framework import serializers

from .models import (
    Employee,
    EmployeeContact,
    EmployeeDepartment,
    EmployeeDependent,
    EmployeePosition,
    EmployeeDocument,
    EmployeeAttendance,
    EmployeePerformanceReview,
    EmployeeWorkflowTask,
    LeaveRequest,
    LeaveType,
    PayrollComponent,
    EmployeeCompensation,
    EmployeeCompensationItem,
    PayrollRun,
)


class EmployeeDepartmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmployeeDepartment
        fields = [
            "id",
            "name",
            "code",
            "description",
            "active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class EmployeePositionSerializer(serializers.ModelSerializer):
    department = serializers.PrimaryKeyRelatedField(
        queryset=EmployeeDepartment.objects.all(),
        required=False,
        allow_null=True,
    )

    class Meta:
        model = EmployeePosition
        fields = [
            "id",
            "title",
            "code",
            "description",
            "department",
            "employment_type",
            "can_teach",
            "active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if instance.department:
            data["department"] = {
                "id": str(instance.department.id),
                "name": instance.department.name,
                "code": instance.department.code,
            }
        return data


class EmployeeContactSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmployeeContact
        fields = [
            "id",
            "contact_type",
            "first_name",
            "last_name",
            "phone_number",
            "email",
            "relationship",
            "street",
            "city",
            "state",
            "postal_code",
            "country",
            "is_primary",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class EmployeeDependentSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmployeeDependent
        fields = [
            "id",
            "first_name",
            "middle_name",
            "last_name",
            "date_of_birth",
            "gender",
            "national_id",
            "relationship",
            "photo",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class EmployeeDocumentSerializer(serializers.ModelSerializer):
    employee = serializers.PrimaryKeyRelatedField(queryset=Employee.objects.all())
    compliance_status = serializers.SerializerMethodField()
    days_until_expiry = serializers.IntegerField(read_only=True)

    def get_compliance_status(self, obj):
        return obj.get_compliance_status()

    class Meta:
        model = EmployeeDocument
        fields = [
            "id",
            "employee",
            "title",
            "document_type",
            "document_number",
            "issue_date",
            "expiry_date",
            "issuing_authority",
            "document_url",
            "notes",
            "compliance_status",
            "days_until_expiry",
            "active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "compliance_status",
            "days_until_expiry",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):
        issue_date = attrs.get("issue_date") or getattr(self.instance, "issue_date", None)
        expiry_date = attrs.get("expiry_date") or getattr(self.instance, "expiry_date", None)
        if issue_date and expiry_date and expiry_date < issue_date:
            raise serializers.ValidationError("Expiry date cannot be earlier than issue date.")
        return attrs

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["employee"] = {
            "id": str(instance.employee.id),
            "employee_number": instance.employee.employee_number,
            "full_name": instance.employee.get_full_name(),
        }
        data["compliance_status"] = instance.get_compliance_status()
        data["days_until_expiry"] = instance.days_until_expiry
        return data


class EmployeePerformanceReviewSerializer(serializers.ModelSerializer):
    employee = serializers.PrimaryKeyRelatedField(queryset=Employee.objects.all())
    reviewer = serializers.PrimaryKeyRelatedField(
        queryset=Employee.objects.all(),
        required=False,
        allow_null=True,
    )
    rating_score = serializers.IntegerField(read_only=True)
    is_completed = serializers.BooleanField(read_only=True)

    class Meta:
        model = EmployeePerformanceReview
        fields = [
            "id",
            "employee",
            "reviewer",
            "review_title",
            "review_period",
            "review_date",
            "next_review_date",
            "status",
            "rating",
            "goals_summary",
            "strengths",
            "improvement_areas",
            "manager_comments",
            "employee_comments",
            "overall_score",
            "rating_score",
            "is_completed",
            "active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "rating_score", "is_completed", "created_at", "updated_at"]

    def validate(self, attrs):
        review_date = attrs.get("review_date") or getattr(self.instance, "review_date", None)
        next_review_date = attrs.get("next_review_date") or getattr(self.instance, "next_review_date", None)
        if review_date and next_review_date and next_review_date < review_date:
            raise serializers.ValidationError("Next review date cannot be earlier than review date.")
        return attrs

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["employee"] = {
            "id": str(instance.employee.id),
            "employee_number": instance.employee.employee_number,
            "full_name": instance.employee.get_full_name(),
        }
        if instance.reviewer:
            data["reviewer"] = {
                "id": str(instance.reviewer.id),
                "employee_number": instance.reviewer.employee_number,
                "full_name": instance.reviewer.get_full_name(),
            }
        return data


class EmployeeWorkflowTaskSerializer(serializers.ModelSerializer):
    employee = serializers.PrimaryKeyRelatedField(queryset=Employee.objects.all())
    assigned_to = serializers.PrimaryKeyRelatedField(
        queryset=Employee.objects.all(),
        required=False,
        allow_null=True,
    )
    is_overdue = serializers.SerializerMethodField()

    class Meta:
        model = EmployeeWorkflowTask
        fields = [
            "id",
            "employee",
            "assigned_to",
            "workflow_type",
            "category",
            "title",
            "description",
            "due_date",
            "status",
            "completed_at",
            "notes",
            "is_overdue",
            "active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "completed_at", "is_overdue", "created_at", "updated_at"]

    def get_is_overdue(self, obj):
        return obj.is_overdue()

    def validate(self, attrs):
        status_value = attrs.get("status") or getattr(self.instance, "status", None)
        due_date = attrs.get("due_date") or getattr(self.instance, "due_date", None)
        completed_at = attrs.get("completed_at") or getattr(self.instance, "completed_at", None)
        if status_value == EmployeeWorkflowTask.TaskStatus.COMPLETED and not completed_at:
            attrs["completed_at"] = timezone.now()
        if completed_at and due_date and completed_at.date() < due_date and status_value == EmployeeWorkflowTask.TaskStatus.COMPLETED:
            return attrs
        return attrs

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["employee"] = {
            "id": str(instance.employee.id),
            "employee_number": instance.employee.employee_number,
            "full_name": instance.employee.get_full_name(),
        }
        if instance.assigned_to:
            data["assigned_to"] = {
                "id": str(instance.assigned_to.id),
                "employee_number": instance.assigned_to.employee_number,
                "full_name": instance.assigned_to.get_full_name(),
            }
        return data


class LeaveTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = LeaveType
        fields = [
            "id",
            "name",
            "code",
            "description",
            "default_days",
            "requires_approval",
            "accrual_frequency",
            "allow_carryover",
            "max_carryover_days",
            "active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate(self, attrs):
        allow_carryover = attrs.get(
            "allow_carryover",
            getattr(self.instance, "allow_carryover", False),
        )
        max_carryover_days = attrs.get(
            "max_carryover_days",
            getattr(self.instance, "max_carryover_days", 0),
        )

        if not allow_carryover:
            attrs["max_carryover_days"] = 0
        elif max_carryover_days < 0:
            raise serializers.ValidationError(
                {"max_carryover_days": "Carryover cap cannot be negative."}
            )

        return attrs


class LeaveRequestSerializer(serializers.ModelSerializer):
    employee = serializers.PrimaryKeyRelatedField(queryset=Employee.objects.all())
    leave_type = serializers.PrimaryKeyRelatedField(queryset=LeaveType.objects.all())
    total_days = serializers.IntegerField(read_only=True)

    class Meta:
        model = LeaveRequest
        fields = [
            "id",
            "employee",
            "leave_type",
            "start_date",
            "end_date",
            "reason",
            "status",
            "reviewed_at",
            "review_note",
            "total_days",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "status",
            "reviewed_at",
            "review_note",
            "total_days",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):
        start_date = attrs.get("start_date") or getattr(self.instance, "start_date", None)
        end_date = attrs.get("end_date") or getattr(self.instance, "end_date", None)
        if start_date and end_date and end_date < start_date:
            raise serializers.ValidationError("End date cannot be earlier than start date.")
        return attrs

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["employee"] = {
            "id": str(instance.employee.id),
            "employee_number": instance.employee.employee_number,
            "full_name": instance.employee.get_full_name(),
        }
        data["leave_type"] = {
            "id": str(instance.leave_type.id),
            "name": instance.leave_type.name,
            "code": instance.leave_type.code,
        }
        return data


class EmployeeAttendanceSerializer(serializers.ModelSerializer):
    employee = serializers.PrimaryKeyRelatedField(queryset=Employee.objects.all())
    hours_worked = serializers.FloatField(read_only=True)

    class Meta:
        model = EmployeeAttendance
        fields = [
            "id",
            "employee",
            "attendance_date",
            "status",
            "check_in_time",
            "check_out_time",
            "notes",
            "hours_worked",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "hours_worked", "created_at", "updated_at"]

    def validate(self, attrs):
        check_in_time = attrs.get("check_in_time") or getattr(self.instance, "check_in_time", None)
        check_out_time = attrs.get("check_out_time") or getattr(self.instance, "check_out_time", None)
        if check_in_time and check_out_time and check_out_time < check_in_time:
            raise serializers.ValidationError("Check-out time cannot be earlier than check-in time.")
        return attrs

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["employee"] = {
            "id": str(instance.employee.id),
            "employee_number": instance.employee.employee_number,
            "full_name": instance.employee.get_full_name(),
        }
        return data


class PayrollComponentSerializer(serializers.ModelSerializer):
    class Meta:
        model = PayrollComponent
        fields = [
            "id",
            "name",
            "code",
            "description",
            "component_type",
            "calculation_method",
            "default_value",
            "taxable",
            "active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class EmployeeCompensationItemSerializer(serializers.ModelSerializer):
    component = serializers.PrimaryKeyRelatedField(queryset=PayrollComponent.objects.all())
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = EmployeeCompensationItem
        fields = ["id", "component", "override_value", "amount", "created_at", "updated_at"]
        read_only_fields = ["id", "amount", "created_at", "updated_at"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["component"] = {
            "id": str(instance.component.id),
            "name": instance.component.name,
            "code": instance.component.code,
            "component_type": instance.component.component_type,
            "calculation_method": instance.component.calculation_method,
        }
        data["amount"] = instance.get_amount()
        return data


class EmployeeCompensationSerializer(serializers.ModelSerializer):
    employee = serializers.PrimaryKeyRelatedField(queryset=Employee.objects.all())
    items = EmployeeCompensationItemSerializer(many=True, required=False)
    gross_pay = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    total_deductions = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    net_pay = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = EmployeeCompensation
        fields = [
            "id",
            "employee",
            "base_salary",
            "currency",
            "payment_frequency",
            "effective_date",
            "notes",
            "items",
            "gross_pay",
            "total_deductions",
            "net_pay",
            "active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "gross_pay", "total_deductions", "net_pay", "created_at", "updated_at"]

    def create(self, validated_data):
        items_data = validated_data.pop("items", [])
        compensation = super().create(validated_data)
        self._sync_items(compensation, items_data)
        return compensation

    def update(self, instance, validated_data):
        items_data = validated_data.pop("items", None)
        compensation = super().update(instance, validated_data)
        if items_data is not None:
            self._sync_items(compensation, items_data)
        return compensation

    def _sync_items(self, compensation, items_data):
        compensation.items.all().delete()
        for item_data in items_data:
            EmployeeCompensationItem.objects.create(
                compensation=compensation,
                component=item_data["component"],
                override_value=item_data.get("override_value"),
                created_by=self.context["request"].user,
                updated_by=self.context["request"].user,
            )

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["employee"] = {
            "id": str(instance.employee.id),
            "employee_number": instance.employee.employee_number,
            "full_name": instance.employee.get_full_name(),
        }
        summary = instance.get_compensation_summary()
        data["gross_pay"] = summary["gross_pay"]
        data["total_deductions"] = summary["total_deductions"]
        data["net_pay"] = summary["net_pay"]
        return data


class PayrollRunSerializer(serializers.ModelSerializer):
    employee_count = serializers.IntegerField(read_only=True)
    gross_pay = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    total_deductions = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    net_pay = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = PayrollRun
        fields = [
            "id",
            "name",
            "run_date",
            "period_start",
            "period_end",
            "payment_date",
            "status",
            "currency",
            "notes",
            "employee_count",
            "gross_pay",
            "total_deductions",
            "net_pay",
            "active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "employee_count",
            "gross_pay",
            "total_deductions",
            "net_pay",
            "created_at",
            "updated_at",
        ]

    def validate(self, attrs):
        period_start = attrs.get("period_start") or getattr(self.instance, "period_start", None)
        period_end = attrs.get("period_end") or getattr(self.instance, "period_end", None)
        payment_date = attrs.get("payment_date") or getattr(self.instance, "payment_date", None)

        if period_start and period_end and period_end < period_start:
            raise serializers.ValidationError({"period_end": "Period end cannot be earlier than period start."})

        if payment_date and period_end and payment_date < period_end:
            raise serializers.ValidationError({"payment_date": "Payment date cannot be earlier than period end."})

        return attrs

    def to_representation(self, instance):
        data = super().to_representation(instance)
        summary = instance.get_summary()
        data["employee_count"] = summary["employee_count"]
        data["gross_pay"] = summary["gross_pay"]
        data["total_deductions"] = summary["total_deductions"]
        data["net_pay"] = summary["net_pay"]
        return data


class EmployeeSerializer(serializers.ModelSerializer):
    employee_number = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    department = serializers.PrimaryKeyRelatedField(
        queryset=EmployeeDepartment.objects.all(),
        required=False,
        allow_null=True,
    )
    position = serializers.PrimaryKeyRelatedField(
        queryset=EmployeePosition.objects.all(),
        required=False,
        allow_null=True,
    )
    manager = serializers.PrimaryKeyRelatedField(
        queryset=Employee.objects.all(),
        required=False,
        allow_null=True,
    )
    contacts = EmployeeContactSerializer(many=True, read_only=True)
    dependents = EmployeeDependentSerializer(many=True, read_only=True)

    class Meta:
        model = Employee
        fields = [
            "id",
            "employee_number",
            "first_name",
            "middle_name",
            "last_name",
            "date_of_birth",
            "gender",
            "email",
            "phone_number",
            "address",
            "city",
            "state",
            "postal_code",
            "country",
            "place_of_birth",
            "photo",
            "hire_date",
            "termination_date",
            "termination_reason",
            "employment_status",
            "department",
            "position",
            "manager",
            "job_title",
            "employment_type",
            "national_id",
            "passport_number",
            "user_account_id_number",
            "is_teacher",
            "contacts",
            "dependents",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "contacts", "dependents"]

    def validate_manager(self, value):
        if self.instance and value and self.instance.pk == value.pk:
            raise serializers.ValidationError("An employee cannot manage themselves.")
        return value

    def create(self, validated_data):
        if not validated_data.get("employee_number"):
            validated_data["employee_number"] = self._generate_employee_number()

        position = validated_data.get("position")
        if position and not validated_data.get("job_title"):
            validated_data["job_title"] = position.title
        if position and not validated_data.get("employment_type"):
            validated_data["employment_type"] = position.employment_type

        return super().create(validated_data)

    def update(self, instance, validated_data):
        position = validated_data.get("position")
        if position and not validated_data.get("job_title"):
            validated_data["job_title"] = position.title
        if position and not validated_data.get("employment_type"):
            validated_data["employment_type"] = position.employment_type
        return super().update(instance, validated_data)

    def _generate_employee_number(self):
        last_employee = Employee.objects.order_by("created_at").last()
        next_number = 1

        if last_employee and last_employee.employee_number:
            suffix = "".join(ch for ch in last_employee.employee_number if ch.isdigit())
            if suffix.isdigit():
                next_number = int(suffix) + 1

        return f"EMP-{next_number:04d}"

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["full_name"] = instance.get_full_name()
        data["photo_url"] = instance.photo.url if getattr(instance, "photo", None) else None
        data["has_photo"] = bool(getattr(instance, "photo", None))

        if instance.department:
            data["department"] = {
                "id": str(instance.department.id),
                "name": instance.department.name,
                "code": instance.department.code,
            }

        if instance.position:
            data["position"] = {
                "id": str(instance.position.id),
                "title": instance.position.title,
                "code": instance.position.code,
            }

        if instance.manager:
            data["manager"] = {
                "id": str(instance.manager.id),
                "employee_number": instance.manager.employee_number,
                "full_name": instance.manager.get_full_name(),
            }

        view = self.context.get("view")
        include_leave_details = getattr(view, "action", None) == "retrieve"

        if include_leave_details:
            leave_requests = instance.get_leave_requests_for_display()
            data["leave_requests"] = LeaveRequestSerializer(leave_requests, many=True).data
            data["leave_balances"] = instance.get_leave_balance_summary(leave_requests)
        else:
            data["leave_requests"] = []
            data["leave_balances"] = []

        return data
