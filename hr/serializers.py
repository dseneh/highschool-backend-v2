from django.utils import timezone
from rest_framework import serializers
from academics.models import Subject

from .models import (
    Employee,
    EmployeeContact,
    EmployeeDepartment,
    EmployeeDependent,
    EmployeePosition,
    EmployeeSpecialization,
    EmployeeAttendance,
    EmployeePerformanceReview,
    LeaveRequest,
    LeaveType,
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
            "id_number",
            "national_id",
            "relationship",
            "photo",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

class EmployeeSpecializationSerializer(serializers.ModelSerializer):
    subject = serializers.PrimaryKeyRelatedField(
        queryset=Subject.objects.all(),
        required=False,
        allow_null=True,
    )

    class Meta:
        model = EmployeeSpecialization
        fields = [
            "id",
            "employee",
            "subject",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if instance.subject:
            data["subject"] = {
                "id": str(instance.subject.id),
                "name": instance.subject.name,
                "code": instance.subject.code,
            }
        else:
            data["subject"] = None
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
    specializations = EmployeeSpecializationSerializer(many=True, read_only=True)

    class Meta:
        model = Employee
        fields = [
            "id",
            "employee_number",
            "id_number",
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
            "highest_qualification",
            "salary_type",
            "basic_salary",
            "hourly_rate",
            "pay_schedule",
            "tax_rules",
            "tax_id",
            "bank_name",
            "bank_account_number",
            "contacts",
            "dependents",
            "specializations",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at", "contacts", "dependents", "specializations"]

    def validate_manager(self, value):
        if self.instance and value and self.instance.pk == value.pk:
            raise serializers.ValidationError("An employee cannot manage themselves.")
        return value

    _SALARY_FIELDS = ("salary_type", "basic_salary", "hourly_rate", "pay_schedule")

    def _is_admin_user(self):
        request = self.context.get("request") if hasattr(self, "context") else None
        user = getattr(request, "user", None)
        if not user or not getattr(user, "is_authenticated", False):
            return False
        if getattr(user, "is_superuser", False):
            return True
        role = str(getattr(user, "role", "") or "").lower()
        return role in {"admin", "superadmin"}

    def _strip_salary_fields_if_unauthorized(self, validated_data):
        if self._is_admin_user():
            return
        for field in self._SALARY_FIELDS:
            validated_data.pop(field, None)

    def create(self, validated_data):
        self._strip_salary_fields_if_unauthorized(validated_data)
        if not validated_data.get("employee_number"):
            validated_data["employee_number"] = self._generate_employee_number()

        position = validated_data.get("position")
        if position and not validated_data.get("job_title"):
            validated_data["job_title"] = position.title
        if position and not validated_data.get("employment_type"):
            validated_data["employment_type"] = position.employment_type

        return super().create(validated_data)

    def update(self, instance, validated_data):
        self._strip_salary_fields_if_unauthorized(validated_data)
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

        data["specializations"] = [
            {
                "id": str(spec.subject_id) if spec.subject_id else None,
                "subject_name": spec.subject.name if spec.subject else "Any",
            }
            for spec in instance.specializations.all()
        ]

        view = self.context.get("view")
        include_leave_details = getattr(view, "action", None) == "retrieve"

        if include_leave_details:
            leave_requests = instance.get_leave_requests_for_display()
            data["leave_requests"] = LeaveRequestSerializer(leave_requests, many=True).data
            data["leave_balances"] = instance.get_leave_balance_summary(leave_requests)
        else:
            data["leave_requests"] = []
            data["leave_balances"] = []

        readiness = instance.payroll_readiness()
        data["payroll_ready"] = readiness["ready"]
        data["missing_payroll_fields"] = readiness["missing"]
        if instance.pay_schedule_id:
            data["pay_schedule"] = {
                "id": str(instance.pay_schedule.id),
                "name": instance.pay_schedule.name,
                "frequency": instance.pay_schedule.frequency,
                "currency_code": instance.pay_schedule.currency.code,
            }

        if instance.pk:
            override_map = {
                ov.rule_id: ov
                for ov in instance.tax_rule_overrides.all()
            }
            data["tax_rules_detail"] = [
                {
                    "id": str(rule.id),
                    "name": rule.name,
                    "code": rule.code,
                    "calculation_type": rule.calculation_type,
                    "value": str(rule.value) if rule.value is not None else None,
                    "applies_to": rule.applies_to,
                    "formula": rule.formula,
                    "is_active": rule.is_active,
                    "override": (
                        {
                            "id": str(override_map[rule.id].id),
                            "calculation_type": override_map[rule.id].calculation_type,
                            "value": (
                                str(override_map[rule.id].value)
                                if override_map[rule.id].value is not None
                                else None
                            ),
                            "applies_to": override_map[rule.id].applies_to,
                            "formula": override_map[rule.id].formula,
                            "is_active": override_map[rule.id].is_active,
                        }
                        if rule.id in override_map
                        else None
                    ),
                }
                for rule in instance.tax_rules.all()
            ]
        else:
            data["tax_rules_detail"] = []

        return data
