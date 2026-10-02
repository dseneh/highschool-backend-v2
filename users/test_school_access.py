import re
from unittest.mock import patch
from datetime import timedelta
from django.test import override_settings
from django.utils import timezone
from django_tenants.utils import schema_context
from rest_framework.exceptions import ValidationError, PermissionDenied
from authorization.models import Role, TenantRoleAssignment
from authorization.multiple_roles import add_role
from users.models import User, SchoolUserAccess
from users.test_parent_portal import ParentPortalTests
from users.school_access import approve_access, eligible_access
from users.account_setup import begin_setup, verify_setup, complete_setup


@override_settings(ACCOUNT_SETUP_EMAIL_ENABLED=True)
class SchoolAccessTests(ParentPortalTests):
    def setUp(self):
        super().setUp()
        self.actor = self.tenant.owner
        add_role(user=self.actor, role=Role.objects.get(system_key="admin"))

    def approve(self, email="external@example.com", role="viewer"):
        return approve_access(self.tenant, self.actor, {"email": email, "first_name": "External", "last_name": "User", "role": role})

    def proof(self, email):
        with patch("common.email_service.send_notification_email", return_value=True) as mail:
            challenge = begin_setup(self.tenant, "other", email)
        code = re.search(r"code is (\d{6})", mail.call_args.args[2]).group(1)
        result = verify_setup(self.tenant, challenge.pk, code)
        result["details"]["terms_accepted"] = True
        return challenge, result

    def test_new_user_has_only_approved_role_and_no_employee(self):
        from hr.models import Employee
        count = Employee.objects.count()
        approval = self.approve()
        self.assertFalse(User.objects.filter(email=approval.email).exists())
        challenge, data = self.proof(approval.email)
        user, created = complete_setup(self.tenant, challenge.pk, data["proof"], {**data["details"], "first_name": "Tampered"}, "Unique-Strong!846218")
        self.assertTrue(created)
        self.assertEqual(user.account_type, "other")
        self.assertEqual(user.first_name, "External")
        self.assertFalse(user.is_platform_superuser)
        self.assertEqual(Employee.objects.count(), count)
        self.assertEqual(list(TenantRoleAssignment.objects.filter(membership__user=user, is_active=True).values_list("role_key", flat=True)), ["system:viewer"])
        self.assertTrue(user.tenants.filter(pk=self.tenant.pk).exists())
        with schema_context(self.other_tenant.schema_name):
            self.assertFalse(TenantRoleAssignment.objects.filter(membership__user=user).exists())
        with self.assertRaises(ValidationError):
            complete_setup(self.tenant, challenge.pk, data["proof"], data["details"], "Unique-Strong!846218")

    def test_existing_identity_and_password_preserved(self):
        self.user.set_password("Original-Strong!87621")
        self.user.save()
        approval = self.approve(self.user.email)
        challenge, data = self.proof(approval.email)
        with self.assertRaises(ValidationError):
            complete_setup(self.tenant, challenge.pk, data["proof"], data["details"], "Wrong-Strong!98723")
        user, created = complete_setup(self.tenant, challenge.pk, data["proof"], data["details"], "Original-Strong!87621")
        self.assertFalse(created)
        self.assertEqual(user.pk, self.user.pk)
        self.assertEqual(user.account_type, "staff")
        self.assertTrue(user.check_password("Original-Strong!87621"))
        self.assertEqual(TenantRoleAssignment.objects.filter(membership__user=user, is_active=True).count(), 2)

    def test_restricted_actor_and_specialized_roles_denied(self):
        with self.assertRaises(PermissionDenied):
            approve_access(self.tenant, self.user, {"email": "x@example.com", "first_name": "X", "last_name": "User", "role": "viewer"})
        for key in ["parent", "student", "staff", "teacher", "superadmin"]:
            with self.assertRaises(ValidationError):
                self.approve(role=key)

    def test_unknown_email_never_sends_code(self):
        with patch("common.email_service.send_notification_email") as mail, self.assertRaises(ValidationError):
            begin_setup(self.tenant, "other", "unknown@example.com")
        mail.assert_not_called()

    def test_revocation_expiry_and_school_isolation(self):
        approval = self.approve()
        with self.assertRaises(ValidationError):
            eligible_access(self.other_tenant, approval.email)
        challenge, data = self.proof(approval.email)
        with self.assertRaises(ValidationError):
            complete_setup(self.other_tenant, challenge.pk, data["proof"], data["details"], "Unique-Strong!846218")
        approval.status = "revoked"
        approval.save()
        with self.assertRaises(ValidationError):
            complete_setup(self.tenant, challenge.pk, data["proof"], data["details"], "Unique-Strong!846218")
        challenge.expires_at = timezone.now() - timedelta(seconds=1)
        challenge.save()
        with self.assertRaises(ValidationError):
            complete_setup(self.tenant, challenge.pk, data["proof"], data["details"], "Unique-Strong!846218")

    def test_changed_permissions_require_fresh_approval(self):
        approval = self.approve()
        approval.permission_version += 1
        approval.save()
        with patch("common.email_service.send_notification_email") as mail, self.assertRaises(ValidationError):
            begin_setup(self.tenant, "other", approval.email)
        mail.assert_not_called()

    def test_pending_api_is_scoped_and_revocation_invalidates_setup(self):
        from users.school_access_views import SchoolUserAccessView
        from rest_framework.test import APIRequestFactory, force_authenticate
        approval = self.approve()
        request = APIRequestFactory().get("/auth/school-user-access/")
        request.tenant = self.tenant
        force_authenticate(request, user=self.actor)
        response = SchoolUserAccessView.as_view()(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 1)
        with schema_context(self.other_tenant.schema_name):
            add_role(user=self.actor, role=Role.objects.get(system_key="admin"))
            # Clear the active-context cache when testing another school.
            request = APIRequestFactory().delete("/auth/school-user-access/")
            request.tenant = self.other_tenant
            force_authenticate(request, user=User.objects.get(pk=self.actor.pk))
            self.assertEqual(SchoolUserAccessView.as_view()(request, access_id=approval.pk).status_code, 404)
        request = APIRequestFactory().delete("/auth/school-user-access/")
        request.tenant = self.tenant
        force_authenticate(request, user=self.actor)
        self.assertEqual(SchoolUserAccessView.as_view()(request, access_id=approval.pk).status_code, 204)
        with self.assertRaises(ValidationError):
            eligible_access(self.tenant, approval.email)

    def access_request(self, record, method, data=None):
        from users.school_access_views import SchoolUserAccessView
        from rest_framework.test import APIRequestFactory, force_authenticate
        request = getattr(APIRequestFactory(), method)("/auth/school-user-access/", data=data or {}, format="json")
        request.tenant = self.tenant
        force_authenticate(request, user=self.actor)
        return SchoolUserAccessView.as_view()(request, access_id=record.pk)

    def test_edit_invalidates_proof_and_sends_updated_instructions(self):
        approval = self.approve()
        challenge, data = self.proof(approval.email)
        with patch("common.email_service.send_notification_email", return_value=True) as mail:
            response = self.access_request(approval, "patch", {"email": approval.email, "first_name": "Updated", "last_name": "Name", "role": "viewer"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["instructions_sent"])
        self.assertIn("School user", mail.call_args.args[2])
        self.assertIn("/account-setup", mail.call_args.kwargs["action_url"])
        approval.refresh_from_db()
        self.assertEqual(approval.first_name, "Updated")
        self.assertIsNotNone(approval.instructions_sent_at)
        with self.assertRaises(ValidationError):
            complete_setup(self.tenant, challenge.pk, data["proof"], data["details"], "Unique-Strong!846218")

    def test_approval_email_failure_is_reported_and_retry_is_available(self):
        from users.viewsets import UserViewSet
        from rest_framework.test import APIRequestFactory, force_authenticate
        request = APIRequestFactory().post("/auth/users/", {"account_type": "other", "email": "delivery@example.com", "first_name": "Delivery", "last_name": "Test", "role": "viewer"}, format="json")
        request.tenant = self.tenant
        force_authenticate(request, user=self.actor)
        with patch("common.email_service.send_notification_email", return_value=False):
            response = UserViewSet.as_view({"post": "create"})(request)
        self.assertEqual(response.status_code, 201)
        self.assertFalse(response.data["instructions_sent"])
        approval = SchoolUserAccess.objects.get(pk=response.data["pending_access_id"])
        self.assertTrue(approval.instructions_failed)
        with patch("common.email_service.send_notification_email", return_value=True):
            response = self.access_request(approval, "post", {"action": "resend"})
        self.assertEqual(response.status_code, 200)
        approval.refresh_from_db()
        self.assertFalse(approval.instructions_failed)
        self.assertIsNotNone(approval.instructions_sent_at)

    def test_revoke_retains_record_and_delete_does_not_delete_account(self):
        approval = self.approve(self.user.email)
        self.assertEqual(self.access_request(approval, "post", {"action": "revoke"}).status_code, 204)
        approval.refresh_from_db()
        self.assertEqual(approval.status, "revoked")
        with self.assertRaises(ValidationError):
            eligible_access(self.tenant, approval.email)
        self.assertEqual(self.access_request(approval, "delete").status_code, 204)
        self.assertFalse(SchoolUserAccess.objects.filter(pk=approval.pk).exists())
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())
        self.assertTrue(TenantRoleAssignment.objects.filter(membership__user=self.user, is_active=True).exists())

    def test_duplicate_account_email_rejected_case_insensitively(self):
        from users.serializers import UserCreateSerializer
        from rest_framework import serializers
        from django.db import IntegrityError, transaction
        serializer = UserCreateSerializer()
        for email in (self.user.email, "  " + self.user.email.upper() + "  "):
            with self.assertRaises(serializers.ValidationError):
                serializer.validate_email(email)
            with self.assertRaises(IntegrityError), transaction.atomic():
                User.objects.create(email=email, id_number="DUPLICATE-EMAIL")
        self.assertEqual(serializer.validate_email("  New@Example.COM  "), "new@example.com")

    def test_duplicate_pending_and_active_role_rejected(self):
        self.approve(self.user.email)
        with self.assertRaisesMessage(ValidationError, "Pending access already exists"):
            self.approve("  " + self.user.email.upper() + "  ")
        # A different role remains eligible for the same global account.
        self.approve(self.user.email, "accountant")
        add_role(user=self.user, role=Role.objects.get(system_key="viewer"))
        with self.assertRaisesMessage(ValidationError, "already has this role"):
            self.approve(self.user.email)
        # The role in this school must not prevent an approval in another school.
        with schema_context(self.other_tenant.schema_name):
            other_actor = self.other_tenant.owner
            add_role(user=other_actor, role=Role.objects.get(system_key="admin"))
            record = approve_access(self.other_tenant, other_actor, {
                "email": self.user.email, "first_name": "Existing", "last_name": "User", "role": "viewer",
            })
            self.assertEqual(record.tenant_id, self.other_tenant.pk)


def load_tests(loader, tests, pattern):
    """Reuse tenant fixtures without rerunning the inherited parent suite."""
    import unittest
    return unittest.TestSuite(SchoolAccessTests(name) for name in SchoolAccessTests.__dict__ if name.startswith("test_"))
