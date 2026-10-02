from django_tenants.test.cases import TenantTestCase
from rest_framework.test import APIRequestFactory, force_authenticate
from students.models import Student, StudentGuardian
from students.views.my_student import MyStudentView
from users.models import User


class MyStudentTests(TenantTestCase):
    @classmethod
    def get_test_schema_name(cls):
        return 'my_student_link_test'

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.name = 'My student link test'
        tenant.id_number = 'MSL001'
        tenant.owner, _ = User.objects.get_or_create(email='my-student-owner@example.com', defaults={'id_number': 'MY-STUDENT-OWNER'})

    def setUp(self):
        self.user = User.objects.create(email='my-student@example.com', id_number='MY-ACCOUNT', account_type='staff')
        self.student = Student.objects.create(first_name='Jane', last_name='Doe', id_number='99001', user_account_id_number=self.user.id_number, entry_as='new', school_code=1, student_seq=99001)

    def call(self):
        request = APIRequestFactory().get('/students/me/')
        request.tenant = self.tenant
        force_authenticate(request, user=self.user)
        return MyStudentView.as_view()(request)

    def test_link_is_resolved_independently_of_active_role_and_account_type(self):
        response = self.call()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {'id': str(self.student.pk), 'id_number': '99001'})

    def test_guardian_link_does_not_count_as_own_student_identity(self):
        self.student.user_account_id_number = 'ANOTHER-ACCOUNT'
        self.student.save()
        StudentGuardian.objects.create(student=self.student, first_name='Parent', last_name='Doe', user_account_id_number=self.user.id_number, active=True)
        self.assertIsNone(self.call().data)

    def test_matching_number_does_not_override_another_account_link(self):
        self.student.user_account_id_number = 'ANOTHER-ACCOUNT'
        self.student.id_number = self.user.id_number
        self.student.save()
        self.assertIsNone(self.call().data)
