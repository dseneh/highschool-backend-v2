from django.core.cache import cache
from django_tenants.test.cases import TenantTestCase
from rest_framework.test import APIRequestFactory, force_authenticate
from authorization.models import Role
from authorization.multiple_roles import add_role
from hr.models import Employee
from hr.views import EmployeeViewSet
from users.models import User


class EmployeeSelfServiceTests(TenantTestCase):
    @classmethod
    def get_test_schema_name(cls):
        return 'employee_self_service_test'

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.name = 'Employee self service'
        tenant.id_number = 'SELF001'
        tenant.owner, _ = User.objects.get_or_create(email='self-owner@example.com', defaults={'id_number': 'SELF-OWNER'})

    def setUp(self):
        cache.clear()
        self.user = User.objects.create(email='self-user@example.com', id_number='SELF-USER')
        add_role(user=self.user, role=Role.objects.create(name='Limited employee'))
        self.employee = Employee.objects.create(employee_number='SELF-001', id_number='EMP-SELF', first_name='Jane', last_name='Doe', user_account_id_number=self.user.id_number)
        self.other = Employee.objects.create(employee_number='OTHER-001', id_number='EMP-OTHER', first_name='Other', last_name='Employee', user_account_id_number='OTHER-USER')

    def call(self, action, pk=None, data=None):
        method = 'patch' if action == 'partial_update' else 'get'
        request = getattr(APIRequestFactory(), method)('/', data or {}, format='json')
        request.tenant = self.tenant
        force_authenticate(request, user=self.user)
        return EmployeeViewSet.as_view({method: action})(request, **({'pk': pk} if pk else {}))

    def test_me_uses_account_link_not_matching_employee_number(self):
        response = self.call('me')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['id_number'], 'EMP-SELF')

    def test_employee_can_read_and_edit_own_personal_fields(self):
        self.assertEqual(self.call('retrieve', str(self.employee.pk)).status_code, 200)
        response = self.call('partial_update', str(self.employee.pk), {'phone_number': '123456789'})
        self.assertEqual(response.status_code, 200)
        self.employee.refresh_from_db()
        self.assertEqual(self.employee.phone_number, '123456789')

    def test_self_service_cannot_read_other_employee_or_list_everyone(self):
        self.assertEqual(self.call('retrieve', str(self.other.pk)).status_code, 403)
        self.assertEqual(self.call('list').status_code, 403)

    def test_self_service_cannot_change_employment_or_account_link(self):
        for data in ({'is_teacher': True}, {'user_account_id_number': 'OTHER-USER'}, {'id_number': 'REPLACED'}):
            self.assertEqual(self.call('partial_update', str(self.employee.pk), data).status_code, 403)

    def test_no_link_returns_null_without_matching_someone_elses_employee_number(self):
        self.employee.user_account_id_number = 'OTHER-USER'
        self.employee.id_number = self.user.id_number
        self.employee.save()
        response = self.call('me')
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.data)

    def test_own_hr_and_pay_lists_do_not_grant_school_wide_access(self):
        from hr.views import EmployeeAttendanceViewSet, LeaveRequestViewSet
        from payroll_v2.views import EmployeeCompensationViewSet, PayrollEmployeeItemViewSet
        for view in [EmployeeAttendanceViewSet, LeaveRequestViewSet, EmployeeCompensationViewSet, PayrollEmployeeItemViewSet]:
            for params, expected in [({'employee': str(self.employee.pk)}, 200), ({'employee': str(self.other.pk)}, 403), ({}, 403)]:
                request = APIRequestFactory().get('/', params)
                request.tenant = self.tenant
                force_authenticate(request, user=self.user)
                self.assertEqual(view.as_view({'get': 'list'})(request).status_code, expected)


from django.test import SimpleTestCase
from types import SimpleNamespace
from unittest.mock import patch
from hr.access_policies import HRAccessPolicy


class SelfServiceFilterTests(SimpleTestCase):
    @patch('hr.self_service.own_employee_queryset')
    def test_specializations_require_the_filter_the_endpoint_actually_uses(self, employees):
        from hr.views import EmployeeSpecializationViewSet
        employees.return_value = [SimpleNamespace(pk='own-employee')]
        request = SimpleNamespace(user=object(), query_params={'employee_id': 'own-employee'})
        policy = HRAccessPolicy()
        self.assertFalse(policy.is_own_employee_records(request, EmployeeSpecializationViewSet(), 'list'))
        request.query_params = {'employee': 'own-employee'}
        self.assertTrue(policy.is_own_employee_records(request, EmployeeSpecializationViewSet(), 'list'))

    @patch('hr.self_service.own_employee_queryset')
    def test_leave_self_service_cannot_submit_for_others_or_set_approval(self, employees):
        from hr.views import LeaveRequestViewSet
        employees.return_value = [SimpleNamespace(pk='own-employee')]
        request = SimpleNamespace(user=object(), data={'employee': 'own-employee', 'reason': 'Personal leave'})
        policy = HRAccessPolicy()
        self.assertTrue(policy.is_own_employee_records(request, LeaveRequestViewSet(), 'create'))
        request.data['employee'] = 'other-employee'
        self.assertFalse(policy.is_own_employee_records(request, LeaveRequestViewSet(), 'create'))
        request.data = {'employee': 'own-employee', 'status': 'approved'}
        self.assertFalse(policy.is_own_employee_records(request, LeaveRequestViewSet(), 'create'))
