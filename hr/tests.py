from datetime import date

from django.test import SimpleTestCase

from hr.access_policies import HRAccessPolicy
from hr.serializers import EmployeeSerializer
from hr.models import (
    Employee,
    EmployeeAttendance,
    EmployeeCompensation,
    EmployeeDepartment,
    EmployeeDocument,
    EmployeePerformanceReview,
    EmployeePosition,
    EmployeeWorkflowTask,
    LeaveRequest,
    LeaveType,
    PayrollComponent,
    PayrollRun,
)
from hr.views import (
    EmployeeAttendanceViewSet,
    EmployeeCompensationViewSet,
    EmployeeDocumentViewSet,
    EmployeePerformanceReviewViewSet,
    EmployeeViewSet,
    EmployeeWorkflowTaskViewSet,
    LeaveRequestViewSet,
    PayrollComponentViewSet,
    PayrollRunViewSet,
)


class EmployeeHrModelSmokeTest(SimpleTestCase):
    def test_employee_model_wires_department_and_position(self):
        department = EmployeeDepartment(name="Administration", code="ADMIN")
        position = EmployeePosition(
            title="HR Officer",
            code="HR-OFFICER",
            department=department,
        )
        employee = Employee(
            first_name="Ada",
            last_name="Lovelace",
            id_number="EMP-0001",
            department=department,
            position=position,
            employment_status=Employee.EmploymentStatus.ACTIVE,
        )

        self.assertEqual(employee.department.name, "Administration")
        self.assertEqual(employee.position.title, "HR Officer")
        self.assertEqual(employee.get_full_name(), "Ada Lovelace")

    def test_employee_serializer_allows_missing_id_number(self):
        serializer = EmployeeSerializer(
            data={
                "first_name": "Ada",
                "last_name": "Lovelace",
                "email": "ada@example.com",
                "date_of_birth": "1990-05-12",
                "hire_date": "2026-04-16",
                "job_title": "Teacher",
                "employment_type": "full_time",
            }
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertNotIn("id_number", serializer.errors)

    def test_employee_viewset_uses_hr_access_policy(self):
        self.assertEqual(EmployeeViewSet.permission_classes, [HRAccessPolicy])

    def test_leave_request_tracks_days_and_approval(self):
        leave_type = LeaveType(name="Annual Leave", code="AL", default_days=21)
        employee = Employee(
            first_name="Ada",
            last_name="Lovelace",
            id_number="EMP-0001",
            employment_status=Employee.EmploymentStatus.ACTIVE,
        )
        leave_request = LeaveRequest(
            employee=employee,
            leave_type=leave_type,
            start_date=date(2026, 4, 20),
            end_date=date(2026, 4, 24),
            reason="Family travel",
        )

        self.assertEqual(leave_request.total_days, 5)

        leave_request.approve()

        self.assertEqual(leave_request.status, LeaveRequest.Status.APPROVED)
        self.assertEqual(employee.employment_status, Employee.EmploymentStatus.ON_LEAVE)

    def test_leave_request_viewset_uses_hr_access_policy(self):
        self.assertEqual(LeaveRequestViewSet.permission_classes, [HRAccessPolicy])

    def test_employee_leave_balance_summary_counts_approved_days(self):
        annual_leave = LeaveType(name="Annual Leave", code="AL", default_days=21)
        sick_leave = LeaveType(name="Sick Leave", code="SL", default_days=10)
        employee = Employee(
            first_name="Ada",
            last_name="Lovelace",
            id_number="EMP-0001",
            employment_status=Employee.EmploymentStatus.ACTIVE,
        )
        approved_request = LeaveRequest(
            employee=employee,
            leave_type=annual_leave,
            start_date=date(2026, 4, 1),
            end_date=date(2026, 4, 3),
            status=LeaveRequest.Status.APPROVED,
        )
        pending_request = LeaveRequest(
            employee=employee,
            leave_type=annual_leave,
            start_date=date(2026, 5, 10),
            end_date=date(2026, 5, 11),
            status=LeaveRequest.Status.PENDING,
        )
        sick_request = LeaveRequest(
            employee=employee,
            leave_type=sick_leave,
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 1),
            status=LeaveRequest.Status.APPROVED,
        )

        summary = employee.get_leave_balance_summary(
            [approved_request, pending_request, sick_request]
        )

        self.assertEqual(summary[0]["leave_type"], "Annual Leave")
        self.assertEqual(summary[0]["used_days"], 3)
        self.assertEqual(summary[0]["remaining_days"], 18)
        self.assertEqual(summary[1]["leave_type"], "Sick Leave")
        self.assertEqual(summary[1]["used_days"], 1)
        self.assertEqual(summary[1]["remaining_days"], 9)

    def test_leave_balance_summary_applies_monthly_accrual_and_rollover(self):
        annual_leave = LeaveType(
            name="Annual Leave",
            code="AL",
            default_days=24,
            accrual_frequency=LeaveType.AccrualFrequency.MONTHLY,
            allow_carryover=True,
            max_carryover_days=5,
        )
        employee = Employee(
            first_name="Ada",
            last_name="Lovelace",
            id_number="EMP-0001",
            employment_status=Employee.EmploymentStatus.ACTIVE,
            hire_date=date(2025, 1, 15),
        )
        previous_year_request = LeaveRequest(
            employee=employee,
            leave_type=annual_leave,
            start_date=date(2025, 12, 1),
            end_date=date(2025, 12, 20),
            status=LeaveRequest.Status.APPROVED,
        )
        current_year_request = LeaveRequest(
            employee=employee,
            leave_type=annual_leave,
            start_date=date(2026, 4, 10),
            end_date=date(2026, 4, 12),
            status=LeaveRequest.Status.APPROVED,
        )

        summary = employee.get_leave_balance_summary(
            [previous_year_request, current_year_request],
            as_of_date=date(2026, 4, 30),
        )

        self.assertEqual(summary[0]["carried_over_days"], 4)
        self.assertEqual(summary[0]["entitled_days"], 12)
        self.assertEqual(summary[0]["used_days"], 3)
        self.assertEqual(summary[0]["remaining_days"], 9)

    def test_employee_compensation_calculates_gross_and_net_pay(self):
        employee = Employee(
            first_name="Ada",
            last_name="Lovelace",
            id_number="EMP-0001",
            employment_status=Employee.EmploymentStatus.ACTIVE,
        )
        housing = PayrollComponent(
            name="Housing Allowance",
            code="HOUSE",
            component_type=PayrollComponent.ComponentType.EARNING,
            calculation_method=PayrollComponent.CalculationMethod.FIXED,
            default_value=500,
        )
        tax = PayrollComponent(
            name="PAYE",
            code="PAYE",
            component_type=PayrollComponent.ComponentType.DEDUCTION,
            calculation_method=PayrollComponent.CalculationMethod.PERCENTAGE,
            default_value=10,
        )
        compensation = EmployeeCompensation(
            employee=employee,
            base_salary=2000,
        )

        summary = compensation.get_compensation_summary(
            [{"component": housing, "amount": 500}, {"component": tax}]
        )

        self.assertEqual(summary["gross_pay"], 2500)
        self.assertEqual(summary["total_deductions"], 250)
        self.assertEqual(summary["net_pay"], 2250)

    def test_payroll_run_retains_name_and_date(self):
        payroll_run = PayrollRun(name="April 2026 Payroll", run_date=date(2026, 4, 30))

        self.assertEqual(str(payroll_run), "April 2026 Payroll - 2026-04-30")

    def test_payroll_viewsets_use_hr_access_policy(self):
        self.assertEqual(PayrollComponentViewSet.permission_classes, [HRAccessPolicy])
        self.assertEqual(EmployeeCompensationViewSet.permission_classes, [HRAccessPolicy])
        self.assertEqual(PayrollRunViewSet.permission_classes, [HRAccessPolicy])

    def test_employee_attendance_calculates_hours_worked(self):
        employee = Employee(
            first_name="Ada",
            last_name="Lovelace",
            id_number="EMP-0001",
            employment_status=Employee.EmploymentStatus.ACTIVE,
        )
        attendance = EmployeeAttendance(
            employee=employee,
            attendance_date=date(2026, 4, 16),
            status=EmployeeAttendance.Status.PRESENT,
            check_in_time="08:00:00",
            check_out_time="16:30:00",
        )

        self.assertEqual(attendance.hours_worked, 8.5)

    def test_attendance_viewset_uses_hr_access_policy(self):
        self.assertEqual(EmployeeAttendanceViewSet.permission_classes, [HRAccessPolicy])

    def test_employee_document_flags_expired_and_expiring_soon_status(self):
        employee = Employee(
            first_name="Ada",
            last_name="Lovelace",
            id_number="EMP-0001",
            employment_status=Employee.EmploymentStatus.ACTIVE,
        )
        expired_document = EmployeeDocument(
            employee=employee,
            title="Work Permit",
            document_type=EmployeeDocument.DocumentType.CERTIFICATION,
            expiry_date=date(2026, 4, 10),
        )
        expiring_document = EmployeeDocument(
            employee=employee,
            title="Teaching License",
            document_type=EmployeeDocument.DocumentType.CERTIFICATION,
            expiry_date=date(2026, 4, 25),
        )

        self.assertEqual(expired_document.get_compliance_status(as_of_date=date(2026, 4, 16)), "expired")
        self.assertEqual(expiring_document.get_compliance_status(as_of_date=date(2026, 4, 16)), "expiring_soon")

    def test_document_viewset_uses_hr_access_policy(self):
        self.assertEqual(EmployeeDocumentViewSet.permission_classes, [HRAccessPolicy])

    def test_employee_performance_review_flags_completion_and_score(self):
        employee = Employee(
            first_name="Ada",
            last_name="Lovelace",
            id_number="EMP-0001",
            employment_status=Employee.EmploymentStatus.ACTIVE,
        )
        review = EmployeePerformanceReview(
            employee=employee,
            review_title="Mid-Year Review",
            review_period="Q2 2026",
            rating=EmployeePerformanceReview.Rating.EXCEEDS_EXPECTATIONS,
            status=EmployeePerformanceReview.Status.COMPLETED,
        )

        self.assertEqual(review.rating_score, 5)
        self.assertTrue(review.is_completed)

    def test_performance_review_viewset_uses_hr_access_policy(self):
        self.assertEqual(EmployeePerformanceReviewViewSet.permission_classes, [HRAccessPolicy])

    def test_employee_workflow_task_tracks_overdue_and_completion(self):
        employee = Employee(
            first_name="Ada",
            last_name="Lovelace",
            id_number="EMP-0001",
            employment_status=Employee.EmploymentStatus.ACTIVE,
        )
        task = EmployeeWorkflowTask(
            employee=employee,
            workflow_type=EmployeeWorkflowTask.WorkflowType.ONBOARDING,
            category=EmployeeWorkflowTask.Category.ORIENTATION,
            title="Complete orientation",
            due_date=date(2026, 4, 10),
            status=EmployeeWorkflowTask.TaskStatus.PENDING,
        )

        self.assertTrue(task.is_overdue(as_of_date=date(2026, 4, 16)))
        task.mark_completed()
        self.assertEqual(task.status, EmployeeWorkflowTask.TaskStatus.COMPLETED)
        self.assertIsNotNone(task.completed_at)

    def test_workflow_task_viewset_uses_hr_access_policy(self):
        self.assertEqual(EmployeeWorkflowTaskViewSet.permission_classes, [HRAccessPolicy])
