from django_tenants.test.cases import TenantTestCase

from authorization.models import Role, TenantMembership
from students.models import Student
from students.serializers import StudentDetailSerializer
from users.models import User


class StudentDetailRBACAccountTests(TenantTestCase):
    @classmethod
    def get_test_schema_name(cls):
        return "student_detail_rbac"

    @classmethod
    def get_test_tenant_domain(cls):
        return "student-detail-rbac.tenant.test.com"

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.name = "Student Detail RBAC Test School"
        tenant.id_number = "SDR001"
        tenant.owner, _ = User.objects.get_or_create(
            email="student-detail-owner@example.com",
            defaults={
                "username": "student-detail-owner",
                "id_number": "STUDENT-DETAIL-OWNER-001",
            },
        )

    def test_user_account_uses_rbac_role_without_legacy_role_fields(self):
        user, _ = User.objects.get_or_create(
            email="student-detail-user@example.com",
            defaults={
                "username": "student-detail-user",
                "id_number": "STUDENT-DETAIL-USER-001",
            },
        )
        role = Role.objects.get(system_key="viewer")
        TenantMembership.objects.get_or_create(
            user=user,
            defaults={"role": role, "is_active": True},
        )
        student = Student.objects.create(
            first_name="Detail",
            last_name="Student",
            id_number="99001",
            user_account_id_number=user.id_number,
            entry_as="new",
            school_code=1,
            student_seq=99001,
        )

        payload = StudentDetailSerializer(student).data["user_account"]

        self.assertEqual(payload["rbac_role"]["system_key"], "viewer")
        self.assertNotIn("role", payload)
        self.assertNotIn("is_staff", payload)
