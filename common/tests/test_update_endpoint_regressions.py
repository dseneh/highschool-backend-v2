from datetime import date, time
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

from django.test import SimpleTestCase
from rest_framework.exceptions import ValidationError

from academics.models import AcademicYear, GradeLevel, Subject
from academics.serializers import SubjectSerializer
from authorization.serializers import RoleUpdateSerializer
from common.update_utils import validate_partial_update
from common.utils import update_model_fields
from core.branding_views import LoginExperienceUpdateSerializer
from core.models import Tenant
from core.serializers import TenantLogoUpdateSerializer
from core.onboarding_views import OnboardingStepUpdateSerializer
from employee_benefits.models import BenefitSettings
from employee_benefits.serializers import BenefitSettingsSerializer
from finance.models import Currency
from finance.serializers import CurrencySerializer
from hr.models import Employee, EmployeeAttendance, EmployeeDepartment, LeaveType
from hr.serializers import EmployeeAttendanceSerializer, EmployeeDepartmentSerializer, LeaveTypeSerializer
from notifications.models import UserNotificationPreference
from notifications.serializers import UserNotificationPreferenceSerializer
from payroll_v2.models import EmployeeCompensation
from payroll_v2.serializers import EmployeeCompensationSerializer
from staff.models import Department, Position
from staff.serializers import DepartmentSerializer, PositionSerializer, TeacherSubjectSerializer
from staff.views.position import PositionViewSet
from students.models import HistoricalGradeRecord
from students.serializers.historical_grade import HistoricalGradeRecordWriteSerializer


class ResourcePartialUpdateRegressionTests(SimpleTestCase):
    def test_single_field_updates_across_resource_serializers(self):
        cases = [
            (SubjectSerializer, Subject(name="Math", code="MATH"), {"description": "Updated"}),
            (CurrencySerializer, Currency(name="Dollar", code="USD", symbol="$"), {"symbol": "US$"}),
            (DepartmentSerializer, Department(name="Science", code="SCI"), {"description": "Updated"}),
            (EmployeeDepartmentSerializer, EmployeeDepartment(name="Science", code="SCI"), {"description": "Updated"}),
            (EmployeeCompensationSerializer, EmployeeCompensation(base_amount=Decimal("100")), {"notes": "Updated"}),
            (UserNotificationPreferenceSerializer, UserNotificationPreference(), {"email_enabled": False}),
            (BenefitSettingsSerializer, BenefitSettings(max_period_days=30, default_period_days=30), {"default_period_days": 20}),
        ]
        for serializer_class, instance, payload in cases:
            with self.subTest(serializer=serializer_class.__name__):
                instance.save = Mock()
                serializer = validate_partial_update(serializer_class, instance, payload)
                self.assertEqual(set(serializer.validated_data), set(payload))
                serializer.save()
                self.assertTrue(instance.save.called)
                self.assertLessEqual(
                    set(instance.save.call_args.kwargs["update_fields"]),
                    set(payload) | {"updated_at"},
                )

    def test_legacy_helper_validates_before_model_is_modified(self):
        currency = Currency(name="Dollar", code="USD", symbol="$")
        currency.save = Mock()
        request = SimpleNamespace(data={"symbol": None}, user=None)
        with self.assertRaises(ValidationError):
            update_model_fields(request, currency, ["symbol"], CurrencySerializer)
        currency.save.assert_not_called()
        self.assertEqual(currency.symbol, "$")

    def test_legacy_helper_updates_only_allowed_fields(self):
        currency = Currency(name="Dollar", code="USD", symbol="$")
        currency.save = Mock()
        request = SimpleNamespace(data={"symbol": "US$", "name": "Forbidden"}, user=None)
        response = update_model_fields(request, currency, ["symbol"], CurrencySerializer)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(currency.name, "Dollar")
        self.assertEqual(currency.symbol, "US$")
        self.assertEqual(set(currency.save.call_args.kwargs["update_fields"]), {"symbol", "updated_at"})

    def test_teacher_assignment_can_use_existing_subject(self):
        existing = SimpleNamespace(section_subject=None, subject=Subject(name="Math"))
        serializer = TeacherSubjectSerializer(instance=existing)
        self.assertEqual(serializer.validate({}), {})

    def test_leave_type_description_does_not_inject_carryover_defaults(self):
        instance = LeaveType(name="Leave", code="LEAVE", allow_carryover=False, max_carryover_days=5)
        serializer = validate_partial_update(LeaveTypeSerializer, instance, {"description": "Edited"})
        self.assertEqual(serializer.validated_data, {"description": "Edited"})

    def test_nullable_attendance_time_is_cleared_without_falling_back(self):
        instance = EmployeeAttendance(
            employee=Employee(first_name="Test"), attendance_date=date(2026, 9, 1),
            check_in_time=time(17), check_out_time=time(9),
        )
        serializer = validate_partial_update(EmployeeAttendanceSerializer, instance, {"check_out_time": None})
        self.assertEqual(serializer.validated_data, {"check_out_time": None})

    def test_historical_note_edit_preserves_label(self):
        instance = HistoricalGradeRecord(
            grade_level=GradeLevel(name="Grade 1", level=1),
            subject=Subject(name="Math"),
            academic_year=AcademicYear(name="Canonical year"),
            academic_year_label="Original transcript label",
            period_end_date=date(2025, 5, 30),
        )
        serializer = validate_partial_update(HistoricalGradeRecordWriteSerializer, instance, {"notes": "Edited"})
        self.assertEqual(serializer.validated_data, {"notes": "Edited"})

    def test_partial_role_update_still_requires_complete_submitted_grants(self):
        with self.assertRaises(ValidationError) as error:
            validate_partial_update(
                RoleUpdateSerializer, SimpleNamespace(name="Role"),
                {"permissions": [{"code": "students.view"}]},
            )
        self.assertIn("permissions", error.exception.detail)
        serializer = validate_partial_update(RoleUpdateSerializer, {}, {"description": "Edited"})
        self.assertEqual(serializer.validated_data, {"description": "Edited"})

    def test_login_experience_only_validates_submitted_fields(self):
        current = {"heading": "Original", "layout": "classic", "show_logo": True}
        serializer = validate_partial_update(LoginExperienceUpdateSerializer, current, {"show_logo": False})
        self.assertEqual(serializer.validated_data, {"show_logo": False})
        self.assertEqual(current["heading"], "Original")

    def test_salary_only_update_uses_stored_title_and_salary_bound(self):
        position = Position(title="Teacher", code="TEACH", salary_min=Decimal("100"), salary_max=Decimal("200"))
        position.save = Mock()
        view = PositionViewSet()
        view.get_object = lambda: position
        view.get_serializer = lambda *args, **kwargs: PositionSerializer(*args, **kwargs)
        request = SimpleNamespace(data={"salary_min": "150.00"}, user=None)
        response = view.update(request)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(position.salary_min, Decimal("150"))
        self.assertEqual(position.title, "Teacher")
        self.assertEqual(set(position.save.call_args.kwargs["update_fields"]), {"salary_min", "updated_at"})
        position.save.reset_mock()
        request.data = {"salary_min": "250"}
        self.assertEqual(view.update(request).status_code, 400)
        position.save.assert_not_called()

    def test_logo_shape_update_does_not_require_upload(self):
        tenant = Tenant(id_number="TEST", logo_shape="square")
        serializer = validate_partial_update(TenantLogoUpdateSerializer, tenant, {"logo_shape": "landscape"})
        self.assertEqual(serializer.validated_data, {"logo_shape": "landscape"})

    def test_onboarding_status_update_does_not_require_payload(self):
        serializer = validate_partial_update(
            OnboardingStepUpdateSerializer, {"payload": {"name": "Original"}},
            {"mark_completed": False},
        )
        self.assertEqual(serializer.validated_data, {"mark_completed": False})

    def test_rule_note_edit_preserves_name_and_override_flag(self):
        from payroll_v2.models import PayrollCatalogItemRule, EmployeePayrollItem
        from payroll_v2.serializers import PayrollItemRuleSerializer, EmployeePayrollItemSerializer
        from employee_benefits.models import BenefitTypeRule, EmployeeBenefit
        from employee_benefits.serializers import BenefitTypeRuleSerializer, EmployeeBenefitSerializer

        cases = [
            (PayrollItemRuleSerializer, PayrollCatalogItemRule(name="Original rule")),
            (BenefitTypeRuleSerializer, BenefitTypeRule(name="Original rule")),
            (EmployeePayrollItemSerializer, EmployeePayrollItem(value=Decimal("25"), calculation_overridden=False)),
            (EmployeeBenefitSerializer, EmployeeBenefit(value=Decimal("25"), calculation_overridden=False)),
        ]
        for serializer_class, instance in cases:
            with self.subTest(serializer=serializer_class.__name__):
                instance.save = Mock()
                serializer = validate_partial_update(serializer_class, instance, {"notes": "Edited"})
                serializer.save()
                self.assertEqual(set(instance.save.call_args.kwargs["update_fields"]), {"notes", "updated_at"})
