import re
from datetime import date, timedelta
from unittest.mock import patch
from django.test import override_settings
from django.utils import timezone
from django_tenants.utils import schema_context
from rest_framework.exceptions import ValidationError
from authorization.models import Role, TenantRoleAssignment
from authorization.multiple_roles import add_role
from users.models import User, ParentStudentLink, AccountSetupChallenge, ParentLinkRequest
from users.test_parent_portal import ParentPortalTests
from users.account_setup import begin_setup, verify_setup, complete_setup, set_guardian_access, source_records, record_email_proof
from users.account_setup_views import ParentLinkRequestsView, ReviewParentRequestsView


@override_settings(ACCOUNT_SETUP_EMAIL_ENABLED=True)
class AccountSetupTests(ParentPortalTests):
    def setup_proof(self, kind, email):
        with override_settings(ACCOUNT_SETUP_EMAIL_ENABLED=True), patch("common.email_service.send_notification_email", return_value=True) as mail:
            challenge = begin_setup(self.tenant, kind, email)
        code = re.search(r"code is (\d{6})", mail.call_args.args[2]).group(1)
        data = verify_setup(self.tenant, challenge.pk, code)
        if kind == "parent":
            data["details"]["terms_accepted"] = True
        return challenge, data

    def new_parent(self):
        self.guardian.email = "self-service-parent@example.com"
        self.guardian.save()
        return self.guardian.email

    def test_parent_setup_updates_only_local_personal_details_and_no_unapproved_access(self):
        email = self.new_parent()
        self.guardian.address = "Existing school address"
        self.guardian.save(update_fields=["address"])
        challenge, data = self.setup_proof("parent", email)
        edited = {**data["details"], "first_name": "Corrected", "gender": "female", "date_of_birth": date(1980, 1, 2)}
        edited.pop("address", None)
        user, created = complete_setup(self.tenant, challenge.pk, data["proof"], edited, "Strong-Unique!998877")
        self.assertTrue(created)
        self.guardian.refresh_from_db()
        self.assertEqual(self.guardian.first_name, "Corrected")
        self.assertEqual(self.guardian.address, "Existing school address")
        self.assertIsNone(self.guardian.date_of_birth)
        self.assertFalse(self.guardian.give_access)
        self.assertFalse(ParentStudentLink.objects.filter(profile__user=user, active=True).exists())
        self.assertTrue(TenantRoleAssignment.objects.filter(membership__user=user, role_key="system:parent", is_active=True).exists())
        with self.assertRaises(ValidationError):
            complete_setup(self.tenant, challenge.pk, data["proof"], edited, "Strong-Unique!998877")

    def test_give_access_connects_verified_parent_and_disabling_preserves_records(self):
        email = self.new_parent()
        set_guardian_access(self.tenant, self.guardian, self.tenant.owner, True)
        challenge, data = self.setup_proof("parent", email)
        user, _ = complete_setup(self.tenant, challenge.pk, data["proof"], data["details"], "Strong-Unique!998877")
        self.assertTrue(ParentStudentLink.objects.filter(profile__user=user, active=True).exists())
        set_guardian_access(self.tenant, self.guardian, self.tenant.owner, False)
        self.assertFalse(ParentStudentLink.objects.filter(profile__user=user, active=True).exists())
        self.guardian.refresh_from_db()
        self.student.refresh_from_db()
        self.assertFalse(self.guardian.give_access)

    def test_admin_approval_appears_in_existing_account_without_parent_request(self):
        from users.parent_views import ParentSummaryView
        record_email_proof(self.user)
        count = User.objects.count()
        guardian = set_guardian_access(self.tenant, self.guardian, self.tenant.owner, True)
        self.assertEqual(guardian.portal_state, "active")
        self.assertEqual(User.objects.count(), count)
        self.assertFalse(ParentLinkRequest.objects.exists())
        self.select_parent()
        response = self.call(ParentSummaryView)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["linked_students"][0]["student"]["id_number"], self.student.id_number)
        self.assertTrue(TenantRoleAssignment.objects.filter(membership__user=self.user, role_key="system:teacher", is_active=True).exists())

    def test_admin_approval_waits_for_email_proof(self):
        from users.parent_views import ParentSummaryView
        guardian = set_guardian_access(self.tenant, self.guardian, self.tenant.owner, True)
        self.assertEqual(guardian.portal_state, "unverified")
        self.assertFalse(ParentStudentLink.objects.filter(profile__user=self.user, active=True).exists())
        self.assertEqual(self.call(ParentSummaryView).data["linked_students"], [])

    def test_staff_and_student_details_are_server_locked_and_roles_are_minimal(self):
        from hr.models import Employee
        employee = Employee.objects.create(employee_number="SELF-SERVICE", email="new-employee@example.com", first_name="Employee", last_name="Record", gender="female", date_of_birth=date(1982, 3, 4))
        self.student.email = "new-student@example.com"
        self.student.gender = "male"
        self.student.save()
        for kind, source in [("staff", employee), ("student", self.student)]:
            challenge, data = self.setup_proof(kind, source.email)
            user, _ = complete_setup(self.tenant, challenge.pk, data["proof"], {"first_name": "Tampered", "last_name": "Wrong", "gender": "female"}, "Strong-Unique!998877")
            source.refresh_from_db()
            self.assertEqual(user.first_name, source.first_name)
            self.assertEqual(source.user_account_id_number, user.id_number)
            self.assertEqual(list(TenantRoleAssignment.objects.filter(membership__user=user, is_active=True).values_list("role_key", flat=True)), [f"system:{kind}"])

    def test_code_attempt_limit_expiry_school_binding_and_replay(self):
        email = self.new_parent()
        with override_settings(ACCOUNT_SETUP_EMAIL_ENABLED=True), patch("common.email_service.send_notification_email", return_value=True) as mail:
            challenge = begin_setup(self.tenant, "parent", email)
        code = re.search(r"code is (\d{6})", mail.call_args.args[2]).group(1)
        with self.assertRaises(ValidationError):
            verify_setup(self.other_tenant, challenge.pk, code)
        wrong = "11111111" if code != "11111111" else "22222222"
        for _ in range(5):
            with self.assertRaises(ValidationError):
                verify_setup(self.tenant, challenge.pk, wrong)
        challenge.refresh_from_db()
        self.assertEqual(challenge.attempts, 5)
        with self.assertRaises(ValidationError):
            verify_setup(self.tenant, challenge.pk, code)
        challenge.attempts = 0
        challenge.expires_at = timezone.now()-timedelta(seconds=1)
        challenge.save()
        with self.assertRaises(ValidationError):
            verify_setup(self.tenant, challenge.pk, code)
        challenge.expires_at = timezone.now()+timedelta(minutes=5)
        challenge.save()
        verify_setup(self.tenant, challenge.pk, code)
        with self.assertRaises(ValidationError):
            verify_setup(self.tenant, challenge.pk, code)

    def test_existing_account_requires_sign_in_and_reuses_identity(self):
        challenge, data = self.setup_proof("parent", self.user.email)
        self.assertTrue(data["existing_account"])
        with self.assertRaises(ValidationError):
            complete_setup(self.tenant, challenge.pk, data["proof"], data["details"], "Strong-Unique!998877")
        count = User.objects.count()
        user, created = complete_setup(self.tenant, challenge.pk, data["proof"], data["details"], "", actor=self.user)
        self.assertEqual(user.pk, self.user.pk)
        self.assertFalse(created)
        self.assertEqual(User.objects.count(), count)
        self.assertEqual(user.account_type, "staff")

    def test_existing_account_can_confirm_password_without_new_school_session(self):
        self.user.set_password("Existing-Credentials!998877")
        self.user.save()
        challenge, data = self.setup_proof("parent", self.user.email)
        user, created = complete_setup(self.tenant, challenge.pk, data["proof"], data["details"], "Existing-Credentials!998877")
        self.assertFalse(created)
        self.assertEqual(user.pk, self.user.pk)
        self.assertTrue(user.check_password("Existing-Credentials!998877"))

    def test_setup_cannot_restore_a_revoked_school_role(self):
        from rest_framework.exceptions import PermissionDenied
        add_role(user=self.user, role=Role.objects.get(system_key="parent"))
        TenantRoleAssignment.objects.filter(membership__user=self.user, role_key="system:parent").update(is_active=False)
        challenge, data = self.setup_proof("parent", self.user.email)
        with self.assertRaises(PermissionDenied):
            complete_setup(self.tenant, challenge.pk, data["proof"], data["details"], "", actor=self.user)

    def test_changed_record_and_wrong_school_invalidate_setup_proof(self):
        email = self.new_parent()
        challenge, data = self.setup_proof("parent", email)
        with self.assertRaises(ValidationError):
            complete_setup(self.other_tenant, challenge.pk, data["proof"], data["details"], "Strong-Unique!998877")
        self.guardian.email = "changed-after-verification@example.com"
        self.guardian.save()
        with self.assertRaises(ValidationError):
            complete_setup(self.tenant, challenge.pk, data["proof"], data["details"], "Strong-Unique!998877")
        self.assertFalse(User.objects.filter(email=email).exists())

    def test_contact_parent_can_set_up_but_other_contacts_cannot(self):
        from students.models import StudentContact
        contact = StudentContact.objects.create(student=self.student, first_name="Contact", last_name="Parent", relationship="parent", email="contact-parent@example.com")
        challenge, data = self.setup_proof("parent", contact.email)
        user, _ = complete_setup(self.tenant, challenge.pk, data["proof"], {**data["details"], "first_name": "Edited"}, "Strong-Unique!998877")
        contact.refresh_from_db()
        self.assertEqual(contact.first_name, "Edited")
        self.assertFalse(ParentStudentLink.objects.filter(profile__user=user, active=True).exists())
        contact.relationship = "neighbor"
        contact.save()
        with self.assertRaises(ValidationError):
            source_records(self.tenant, "parent", contact.email)

    def test_lookup_and_parent_edits_do_not_cross_schools(self):
        from hr.models import Employee
        with schema_context(self.other_tenant.schema_name):
            Employee.objects.create(employee_number="PRIVATE", email="private@example.com", first_name="Private", last_name="Staff")
        with self.assertRaises(ValidationError):
            source_records(self.tenant, "staff", "private@example.com")
        with self.assertRaises(ValidationError):
            source_records(self.tenant, "student", "missing@example.com")
        with self.assertRaises(ValidationError):
            source_records(self.tenant, "parent", "missing@example.com")

    def test_exact_student_details_request_approval_and_never_grant_access_alone(self):
        from academics.models import GradeLevel, Division
        grade = GradeLevel.objects.create(name="Grade 1", level=1, division=Division.objects.create(name="Primary"))
        self.student.grade_level = grade
        self.student.gender = "male"
        self.student.save()
        record_email_proof(self.user)
        self.tenant.add_user(self.user, is_staff=False, is_superuser=False)
        payload = {"student_id_number": self.student.id_number, "first_name": self.student.first_name, "last_name": self.student.last_name, "relationship": "mother"}
        wrong = self.call(ParentLinkRequestsView, "post", {**payload, "first_name": "Wrong"})
        self.assertEqual(wrong.status_code, 400)
        for changed in ({"last_name": "Wrong"}, {"middle_name": "Wrong"}, {"gender": "female"}, {"student_id_number": "missing"}):
            rejected = self.call(ParentLinkRequestsView, "post", {**payload, **changed})
            self.assertEqual(rejected.status_code, 400)
        result = self.call(ParentLinkRequestsView, "post", payload)
        self.assertEqual(result.status_code, 202)
        self.assertFalse(ParentStudentLink.objects.filter(profile__user=self.user, active=True).exists())
        again = self.call(ParentLinkRequestsView, "post", payload)
        self.assertEqual(again.data["id"], result.data["id"])
        # A parent/teacher cannot approve their own request or bypass the school permission.
        denied = self.call(ReviewParentRequestsView, "post", {"request_id": result.data["id"], "approve": True}, student_id=self.student.pk)
        self.assertIn(denied.status_code, (403, 404))
        requester = self.user
        reviewer = User.objects.create(email="reviewer@example.com", id_number="SETUP-REVIEWER")
        add_role(user=reviewer, role=Role.objects.get(system_key="admin"))
        self.user = reviewer
        approved = self.call(ReviewParentRequestsView, "post", {"request_id": result.data["id"], "approve": True}, student_id=self.student.pk)
        self.assertEqual(approved.status_code, 200)
        self.assertTrue(ParentStudentLink.objects.filter(profile__user=requester, active=True).exists())
        self.user = requester
        linked = self.call(ParentLinkRequestsView, "post", payload)
        self.assertEqual(linked.data["status"], "linked")

    def test_parent_student_detail_routes_are_scoped_and_read_only(self):
        from students.models import Student
        from students.views.student import StudentDetailView
        self.activate()
        self.select_parent()
        linked = self.call(StudentDetailView, id=self.student.id_number)
        self.assertEqual(linked.status_code, 200)
        self.assertIsNone(linked.data["user_account"])
        unrelated = Student.objects.create(first_name="Other", last_name="Student", id_number="UNRELATED", entry_as="new", school_code=1, student_seq=99999)
        self.assertEqual(self.call(StudentDetailView, id=unrelated.id_number).status_code, 404)
        self.assertEqual(self.call(StudentDetailView, "put", {"first_name": "Changed"}, id=self.student.id_number).status_code, 403)
        self.assertEqual(self.call(StudentDetailView, "delete", id=self.student.id_number).status_code, 403)

    def test_global_parent_setup_checks_eligibility_before_email_and_connects_both_schools(self):
        from core.models import Tenant
        from students.models import Student, StudentGuardian
        from users import global_parent_setup
        with schema_context("public"):
            public, _ = Tenant.objects.get_or_create(schema_name="public", defaults={"name": "EzySchool", "id_number": "PUBLIC", "owner": self.tenant.owner, "status": "active"})
        set_guardian_access(self.tenant, self.guardian, self.tenant.owner, True)
        with schema_context(self.other_tenant.schema_name):
            child = Student.objects.create(first_name="Other", last_name="Child", id_number="91001", entry_as="new", school_code=1, student_seq=91001)
            guardian = StudentGuardian.objects.create(student=child, first_name="Parent", last_name="One", email=self.user.email)
            set_guardian_access(self.other_tenant, guardian, self.tenant.owner, True)
        with patch("common.email_service.send_notification_email", return_value=True) as mail, patch("users.global_parent_setup.discover", wraps=global_parent_setup.discover) as discover:
            challenge = global_parent_setup.begin(public, "parent", self.user.email)
            discover.assert_called_once_with(self.user.email)
            code = re.search(r"code is (\d{6})", mail.call_args.args[2]).group(1)
            data = global_parent_setup.verify(public, challenge.pk, code)
            data["details"]["terms_accepted"] = True
        user, created = global_parent_setup.complete(public, challenge.pk, data["proof"], data["details"], "", self.user)
        self.assertFalse(created)
        self.assertEqual(user.pk, self.user.pk)
        self.assertEqual(ParentStudentLink.objects.filter(profile__user=user, active=True).count(), 2)
        with self.assertRaises(ValidationError):
            global_parent_setup.complete(public, challenge.pk, data["proof"], data["details"], "", self.user)

    def test_parent_token_cannot_select_staff_role_or_access_public_admin(self):
        from rest_framework.test import APIRequestFactory
        from rest_framework_simplejwt.tokens import RefreshToken
        from api.authentication import TenantAwareJWTAuthentication
        from rest_framework.exceptions import PermissionDenied
        from core.models import Tenant
        record_email_proof(self.user)
        set_guardian_access(self.tenant, self.guardian, self.tenant.owner, True)
        token = RefreshToken.for_user(self.user).access_token
        token["parent_workspace"] = True
        request = APIRequestFactory().get("/api/v1/students/", HTTP_AUTHORIZATION=f"Bearer {token}", HTTP_X_ROLE_ASSIGNMENT="platform")
        request.tenant = self.tenant
        user, _ = TenantAwareJWTAuthentication().authenticate(request)
        parent = TenantRoleAssignment.objects.get(membership__user=user, role_key="system:parent")
        self.assertEqual(user._active_role_selection, str(parent.pk))
        with schema_context("public"):
            request = APIRequestFactory().get("/api/v1/tenants/", HTTP_AUTHORIZATION=f"Bearer {token}")
            request.tenant = Tenant(schema_name="public")
            with self.assertRaises(PermissionDenied):
                TenantAwareJWTAuthentication().authenticate(request)

    def test_parent_sso_code_is_single_use_and_parent_scoped(self):
        import base64, hashlib
        from core.models import Tenant
        from users.models import OAuthClient, OAuthRedirectURI
        from users.sso_views import SsoAuthorizeView, SsoTokenExchangeView
        from rest_framework_simplejwt.tokens import AccessToken
        with schema_context("public"):
            Tenant.objects.get_or_create(schema_name="public", defaults={"name": "EzySchool", "id_number": "PUBLIC", "owner": self.tenant.owner, "status": "active"})
        record_email_proof(self.user)
        set_guardian_access(self.tenant, self.guardian, self.tenant.owner, True)
        client = OAuthClient.objects.create(client_id="parent-test", name="Parent test")
        uri = "https://parent.example.com/auth/callback"
        OAuthRedirectURI.objects.create(client=client, redirect_uri=uri)
        verifier = "a" * 64
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        from urllib.parse import urlparse, parse_qs
        with schema_context("public"):
            response = self.call(SsoAuthorizeView, data={"client_id": client.client_id, "redirect_uri": uri, "tenant": "parent", "state": "test-state", "code_challenge": challenge, "code_challenge_method": "S256"})
            self.assertEqual(response.status_code, 302)
            code = parse_qs(urlparse(response["Location"]).query)["code"][0]
            payload = {"grant_type": "authorization_code", "code": code, "client_id": client.client_id, "redirect_uri": uri, "code_verifier": verifier}
            rejected = self.call(SsoTokenExchangeView, "post", {**payload, "code_verifier": "wrong"})
            self.assertEqual(rejected.status_code, 400)
            result = self.call(SsoTokenExchangeView, "post", payload)
            self.assertEqual(result.status_code, 200)
            self.assertTrue(AccessToken(result.data["access"])["parent_workspace"])
            self.assertEqual(self.call(SsoTokenExchangeView, "post", payload).status_code, 400)

            from users.models import AuthorizationCode
            from users.sso_views import hash_value
            expired_response = self.call(SsoAuthorizeView, data={"client_id": client.client_id, "redirect_uri": uri, "tenant": "parent", "state": "expiry", "code_challenge": challenge, "code_challenge_method": "S256"})
            expired_code = parse_qs(urlparse(expired_response["Location"]).query)["code"][0]
            AuthorizationCode.objects.filter(code_hash=hash_value(expired_code)).update(expires_at=timezone.now()-timedelta(seconds=1))
            expired = self.call(SsoTokenExchangeView, "post", {**payload, "code": expired_code})
            self.assertEqual(expired.status_code, 400)
            self.assertEqual(expired.data["error_code"], "CODE_EXPIRED")
