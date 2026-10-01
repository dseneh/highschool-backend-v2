"""A real two-connection replay race (not wrapped in TestCase's outer atomic block)."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from django.db import connections, connection
from django.test import TransactionTestCase
from django.utils import timezone
from django_tenants.test.cases import TenantTestCase
from django_tenants.utils import schema_context
from rest_framework.exceptions import ValidationError
from users.models import User, ParentProfile, ParentStudentLink
from students.models import Student, StudentGuardian
from users.parent_portal import issue_invitation, accept_invitation


class ParentInvitationConcurrencyTests(TenantTestCase):
    @classmethod
    def _fixture_setup(cls):
        TransactionTestCase._fixture_setup.__func__(cls)

    def _fixture_teardown(self):
        # This class owns a disposable schema, dropped by TenantTestCase. Public
        # identities are explicitly deleted here rather than flushing shared data.
        with schema_context(self.tenant.schema_name):
            User.objects.filter(id_number="CONCURRENT-PARENT").delete()

    @classmethod
    def get_test_schema_name(cls):
        return "parent_concurrency_test"

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.name, tenant.id_number, tenant.status = "Concurrent parent school", "PPC001", "active"
        tenant.owner, _ = User.objects.get_or_create(email="concurrent-owner@example.com", defaults={"id_number": "CONCURRENT-OWNER"})

    def test_simultaneous_acceptance_consumes_invitation_exactly_once(self):
        user = User.objects.create(email="concurrent-parent@example.com", id_number="CONCURRENT-PARENT", account_type="staff")
        student = Student.objects.create(first_name="Test", last_name="Child", id_number="92001", entry_as="new", school_code=1, student_seq=92001)
        guardian = StudentGuardian.objects.create(student=student, first_name="Test", last_name="Parent", email=user.email)
        invitation, token = issue_invitation(tenant=self.tenant, guardian_id=guardian.pk, actor=self.tenant.owner)
        invitation.delivered_at = timezone.now()
        invitation.save()
        barrier = Barrier(2)
        schema = self.tenant.schema_name

        def accept():
            try:
                with schema_context(schema):
                    actor = User.objects.get(pk=user.pk)
                    barrier.wait(timeout=10)
                    try:
                        accept_invitation(token=token, user=actor)
                        return "accepted"
                    except ValidationError:
                        return "rejected"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: accept(), range(2)))
        self.assertCountEqual(results, ["accepted", "rejected"])
        connection.set_tenant(self.tenant)
        self.assertEqual(ParentProfile.objects.filter(user=user).count(), 1)
        self.assertEqual(ParentStudentLink.objects.filter(profile__user=user, tenant=self.tenant, active=True).count(), 1)
