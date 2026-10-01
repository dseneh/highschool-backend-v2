import uuid
from datetime import timedelta
from django.core.cache import cache
from django.test import SimpleTestCase
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from django_tenants.test.cases import TenantTestCase
from django_tenants.utils import schema_context
from rest_framework.exceptions import ValidationError, NotFound, PermissionDenied
from rest_framework.test import APIRequestFactory, force_authenticate
from authorization.models import Role, TenantRoleAssignment
from authorization.multiple_roles import add_role, revoke_role
from students.models import Student, StudentGuardian
from users.models import User, ParentStudentLink, ParentInvitation
from users.parent_portal import (issue_invitation, accept_invitation, resolve_link, end_link,
    verified_guardians, attach_approved_relationship, reconcile_parent)
from users.parent_views import ParentSummaryView, ParentStudentView, GuardianPortalView


class ParentPortalTests(TenantTestCase):
    @classmethod
    def get_test_schema_name(cls):
        return "parent_portal_test"

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.name, tenant.id_number, tenant.status = "Parent school", "PPT001", "active"
        tenant.owner, _ = User.objects.get_or_create(email="parent-owner@example.com", defaults={"id_number": "PP-OWNER"})

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from core.models import Tenant
        with schema_context("public"):
            cls.other_tenant = Tenant.objects.create(schema_name="parent_other_test", name="Other school", id_number="PPT002", owner=cls.tenant.owner, status="active")
        from django.db import connection
        connection.set_tenant(cls.tenant)

    @classmethod
    def tearDownClass(cls):
        from django.db import connection
        connection.set_schema_to_public()
        cls.other_tenant.delete(force_drop=True)
        super().tearDownClass()

    def setUp(self):
        cache.clear()
        self.user = User.objects.create(email="parent-staff@example.com", id_number="PP-STAFF", account_type="staff")
        self.student = Student.objects.create(first_name="Child", last_name="One", id_number="91001", entry_as="new", school_code=1, student_seq=91001)
        self.guardian = StudentGuardian.objects.create(student=self.student, first_name="Parent", last_name="One", email=self.user.email)
        add_role(user=self.user, role=Role.objects.get(system_key="teacher"))

    def invite(self):
        invitation, token = issue_invitation(tenant=self.tenant, guardian_id=self.guardian.pk, actor=self.tenant.owner)
        invitation.delivered_at = timezone.now()
        invitation.save(update_fields=["delivered_at"])
        return invitation, token

    def activate(self):
        _, token = self.invite()
        profile = accept_invitation(token=token, user=self.user)
        return profile, ParentStudentLink.objects.get(profile=profile, guardian_id=self.guardian.pk)

    def call(self, view, method="get", data=None, **kwargs):
        request = getattr(APIRequestFactory(), method)("/auth/parent/", data=data or {}, format="json")
        request.tenant = self.tenant
        if getattr(self.user, "_active_role_selection", None):
            request.META["HTTP_X_ROLE_ASSIGNMENT"] = self.user._active_role_selection
        force_authenticate(request, user=self.user)
        return view.as_view()(request, **kwargs)

    def select_parent(self):
        self.user._active_role_selection = str(TenantRoleAssignment.objects.get(membership__user=self.user, role_key="system:parent").pk)

    def test_employee_reused_and_role_granted(self):
        count = User.objects.count()
        profile, link = self.activate()
        self.assertEqual(User.objects.count(), count)
        self.user.refresh_from_db()
        self.assertEqual(self.user.account_type, "staff")
        self.assertEqual(profile.user_id, self.user.pk)
        self.assertEqual(TenantRoleAssignment.objects.filter(membership__user=self.user, is_active=True).count(), 2)
        self.assertEqual(resolve_link(self.user, link.pk)[1].student_id, self.student.pk)

    def test_platform_account_restricted_in_parent_context(self):
        self.user.is_platform_superuser = True
        self.user.save()
        self.activate()
        self.select_parent()
        from authorization.runtime import resolve_authorization_context
        self.assertIsNone(resolve_authorization_context(self.user).permission_scope("roles.assign_users"))

    def test_replay_wrong_account_expiry_and_delivery(self):
        invitation, token = self.invite()
        wrong = User.objects.create(email="wrong@example.com", id_number="PP-WRONG")
        with self.assertRaises(ValidationError):
            accept_invitation(token=token, user=wrong)
        invitation.expires_at = timezone.now()-timedelta(seconds=1)
        invitation.save()
        with self.assertRaises(ValidationError):
            accept_invitation(token=token, user=self.user)
        invitation.expires_at = timezone.now()+timedelta(days=1)
        invitation.delivered_at = None
        invitation.save()
        with self.assertRaises(ValidationError):
            accept_invitation(token=token, user=self.user)
        invitation.delivered_at = timezone.now()
        invitation.save()
        accept_invitation(token=token, user=self.user)
        with self.assertRaises(ValidationError):
            accept_invitation(token=token, user=self.user)

    def test_resend_cooldown(self):
        self.invite()
        with self.assertRaises(ValidationError):
            self.invite()

    def test_registration_requires_invitation_and_reuses_accounts(self):
        with self.assertRaises(ValidationError):
            accept_invitation(token="invalid", password="strong-password-123")
        _, token = self.invite()
        with self.assertRaises(ValidationError):
            accept_invitation(token=token, password="strong-password-123")
        self.guardian.email = "new-parent@example.com"
        self.guardian.save()
        ParentInvitation.objects.all().update(created_at=timezone.now()-timedelta(minutes=2))
        _, token = self.invite()
        profile = accept_invitation(token=token, password="new-Long-unique!1234")
        self.assertTrue(profile.user.check_password("new-Long-unique!1234"))
        self.assertEqual(profile.user.email, self.guardian.email)

    def test_unverified_email_or_account_reference_never_authorizes(self):
        self.guardian.user_account_id_number = self.user.id_number
        self.guardian.save()
        self.assertFalse(verified_guardians(self.user).exists())
        self.assertFalse(self.user.get_children().exists())
        self.assertEqual(self.call(ParentSummaryView).data["linked_students"], [])

    def test_summary_safe_shape_and_unrelated_link_denial(self):
        _, link = self.activate()
        payload = self.call(ParentSummaryView).data["linked_students"][0]
        self.assertEqual(set(payload), {"link_id", "student", "school", "relationship", "is_primary", "dashboard"})
        self.assertNotIn("email", payload["student"])
        with self.assertRaises(NotFound):
            resolve_link(self.user, uuid.uuid4())
        other = User.objects.create(email="outsider@example.com", id_number="OUTSIDER")
        with self.assertRaises(NotFound):
            resolve_link(other, link.pk)

    def test_role_context_and_student_switching(self):
        profile, link = self.activate()
        self.assertEqual(self.call(ParentStudentView, link_id=link.pk).status_code, 403)
        self.select_parent()
        self.assertEqual(self.call(ParentStudentView, link_id=link.pk).status_code, 200)
        second = Student.objects.create(first_name="Child", last_name="Two", id_number="91002", entry_as="new", school_code=1, student_seq=91002)
        guardian = StudentGuardian.objects.create(student=second, first_name="Parent", last_name="One")
        attach_approved_relationship(tenant=self.tenant, guardian_id=guardian.pk, profile_id=profile.pk, actor=self.tenant.owner)
        second_link = ParentStudentLink.objects.get(guardian_id=guardian.pk)
        self.assertEqual(self.call(ParentStudentView, link_id=second_link.pk).data["student"]["id"], str(second.pk))
        end_link(tenant=self.tenant, guardian_id=guardian.pk, actor=self.user)
        self.assertEqual(self.call(ParentStudentView, link_id=second_link.pk).status_code, 404)
        self.assertEqual(self.call(ParentStudentView, link_id=link.pk).status_code, 200)

    def test_role_protection_and_disconnect_preserves_records(self):
        self.activate()
        assignment = TenantRoleAssignment.objects.get(membership__user=self.user, role_key="system:parent")
        with self.assertRaises(DjangoValidationError):
            revoke_role(user=self.user, assignment_id=assignment.pk, actor=self.tenant.owner)
        end_link(tenant=self.tenant, guardian_id=self.guardian.pk, actor=self.user)
        self.assertTrue(Student.objects.filter(pk=self.student.pk).exists())
        self.guardian.refresh_from_db()
        self.assertEqual(self.guardian.portal_state, "disconnected")
        assignment.refresh_from_db()
        self.assertFalse(assignment.is_active)
        self.assertTrue(TenantRoleAssignment.objects.filter(membership__user=self.user, role_key="system:teacher", is_active=True).exists())

    def test_stale_index_and_disabled_school(self):
        _, link = self.activate()
        self.tenant.active = False
        self.tenant.save(update_fields=["active"])
        with self.assertRaises(NotFound):
            resolve_link(self.user, link.pk)
        self.tenant.active = True
        self.tenant.save(update_fields=["active"])
        self.guardian.portal_state = "suspended"
        self.guardian.save()
        with self.assertRaises(NotFound):
            resolve_link(self.user, link.pk)

    def test_parent_cannot_manage_or_use_admin_serializer(self):
        self.activate()
        self.select_parent()
        self.assertEqual(self.call(GuardianPortalView, "post", {"action": "invite"}, guardian_id=self.guardian.pk).status_code, 403)
        from students.views.guardian import StudentGuardianDetailView
        self.assertEqual(self.call(StudentGuardianDetailView, id=self.guardian.pk).status_code, 403)

    def test_reconciliation_idempotent(self):
        profile, _ = self.activate()
        reconcile_parent(profile, self.tenant)
        reconcile_parent(profile, self.tenant)
        self.assertEqual(ParentStudentLink.objects.filter(profile=profile).count(), 1)

    def test_wrong_school_context(self):
        _, link = self.activate()
        self.select_parent()
        with schema_context("public"):
            with self.assertRaises(PermissionDenied):
                resolve_link(self.user, link.pk, require_context=True)

    def test_two_school_discovery_rechecks_each_schema_and_role(self):
        from core.models import Tenant
        from django.db import connection
        profile, first_link = self.activate()
        self.select_parent()
        original_selection = self.user._active_role_selection
        second_school = self.other_tenant
        try:
            with schema_context(second_school.schema_name):
                # Deliberately repeat the student display identifier across schools.
                child = Student.objects.create(first_name="Other", last_name="Child", id_number=self.student.id_number, entry_as="new", school_code=2, student_seq=91001)
                guardian = StudentGuardian.objects.create(student=child, first_name="Same", last_name="Parent", email=self.user.email)
                invitation, token = issue_invitation(tenant=second_school, guardian_id=guardian.pk, actor=self.tenant.owner)
                invitation.delivered_at = timezone.now()
                invitation.save()
                second_profile = accept_invitation(token=token, user=self.user)
                self.assertEqual(profile.pk, second_profile.pk)
                second_link = ParentStudentLink.objects.get(guardian_id=guardian.pk, tenant=second_school)
                with self.assertRaises(PermissionDenied):
                    resolve_link(self.user, second_link.pk, require_context=True)
                self.user._active_role_selection = str(TenantRoleAssignment.objects.get(membership__user=self.user, role_key="system:parent").pk)
                self.assertEqual(resolve_link(self.user, second_link.pk, require_context=True)[1].student_id, child.pk)
            self.user._active_role_selection = original_selection
            rows = self.call(ParentSummaryView).data["linked_students"]
            self.assertEqual({row["school"]["id"] for row in rows}, {str(self.tenant.pk), str(second_school.pk)})
            self.assertEqual(resolve_link(self.user, first_link.pk, require_context=True)[1].student_id, self.student.pk)
            with self.assertRaises(PermissionDenied):
                resolve_link(self.user, second_link.pk, require_context=True)
            second_school.active = False
            with schema_context("public"):
                second_school.save(update_fields=["active"])
            self.assertEqual(len(self.call(ParentSummaryView).data["linked_students"]), 1)
        finally:
            connection.set_tenant(self.tenant)

    def test_badge_respects_viewer_permission_and_current_school(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from hr.serializers import EmployeeSerializer
        self.activate()
        employee = SimpleNamespace(user_account_id_number=self.user.id_number)
        request = SimpleNamespace(user=self.tenant.owner, permission_scope=Mock(return_value="all"))
        serializer = EmployeeSerializer(context={"request": request})
        self.assertEqual(serializer.get_parent_of(employee)[0]["id"], str(self.student.pk))
        request.permission_scope.return_value = None
        self.assertEqual(serializer.get_parent_of(employee), [])
        self.assertEqual(EmployeeSerializer().get_parent_of(employee), [])

    def test_changed_contact_invalidates_invitation_and_suspend_blocks_replay(self):
        _, token = self.invite()
        self.guardian.email = "changed@example.com"
        self.guardian.save()
        with self.assertRaises(ValidationError):
            accept_invitation(token=token, user=self.user)
        self.guardian.email = self.user.email
        self.guardian.save()
        end_link(tenant=self.tenant, guardian_id=self.guardian.pk, actor=self.tenant.owner, state="suspended")
        with self.assertRaises(ValidationError):
            accept_invitation(token=token, user=self.user)

    def test_overview_uses_only_published_grades_and_safe_attendance(self):
        from datetime import date
        from academics.models import AcademicYear, Division, GradeLevel, Section, Subject, SectionSubject
        from students.models import Enrollment, Attendance
        from grading.models import GradeBook, Assessment, Grade
        from unittest.mock import patch
        year = AcademicYear.objects.create(name="2026-2027", start_date=date(2026, 9, 1), end_date=date(2027, 7, 1), current=True)
        division = Division.objects.create(name="Parent test division")
        level = GradeLevel.objects.create(name="Grade 1", level=1, division=division)
        section = Section.objects.create(name="1A", grade_level=level)
        subject = Subject.objects.create(name="Math", code="PPM")
        section_subject = SectionSubject.objects.create(section=section, subject=subject)
        enrollment = Enrollment.objects.create(student=self.student, academic_year=year, section=section, grade_level=level)
        book = GradeBook.objects.create(section_subject=section_subject, section=section, subject=subject, academic_year=year, name="Math")
        approved = Assessment.objects.create(gradebook=book, name="Published assessment")
        draft = Assessment.objects.create(gradebook=book, name="Hidden draft")
        # Suppress outbound notification hooks; tests never send messages.
        with patch("grading.signals._maybe_notify_grade_published"):
            Grade.objects.create(assessment=approved, enrollment=enrollment, student=self.student, academic_year=year, section=section, subject=subject, score=80, condition_status="graded", status="approved")
            Grade.objects.create(assessment=draft, enrollment=enrollment, student=self.student, academic_year=year, section=section, subject=subject, score=50, condition_status="graded", status="draft")
        Attendance.objects.create(enrollment=enrollment, date=date(2026, 9, 28), status="present", notes="Private staff note")
        _, link = self.activate()
        self.select_parent()
        response = self.call(ParentStudentView, link_id=link.pk)
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row["assessment__name"] for row in response.data["grades"]], ["Published assessment"])
        self.assertNotIn("notes", response.data["attendance"][0])
        self.assertIsNotNone(response.data["fees"])
        with patch("grading.services.grade_access.enforce_grade_access", side_effect=PermissionDenied("Balance restriction")):
            restricted = self.call(ParentStudentView, link_id=link.pk)
        self.assertEqual(restricted.data["grades"], [])
        self.assertTrue(restricted.data["grades_restricted"])

    def test_disabled_parent_read_permission_denies_discovery(self):
        _, link = self.activate()
        from authorization.models import RolePermission
        # Simulate an application-owned grant withdrawal; system grants cannot be edited by users.
        from django.db.models import QuerySet
        QuerySet.delete(RolePermission.objects.filter(role__system_key="parent", permission_code="students.view"))
        with self.assertRaises(NotFound):
            resolve_link(self.user, link.pk)
        self.assertEqual(self.call(ParentSummaryView).data["linked_students"], [])


    def test_staff_prefill_is_scoped_and_server_enforced(self):
        from datetime import date
        from hr.models import Employee
        from users.parent_portal import invitation_staff_details, register_invited_parent
        from users.parent_views import ParentInvitationEmailView
        self.guardian.email = "staff-new@example.com"
        self.guardian.save()
        with schema_context(self.other_tenant.schema_name):
            Employee.objects.create(employee_number="OTHER", first_name="Private", last_name="Other", email=self.guardian.email)
        invitation, token = self.invite()
        self.assertIsNone(invitation_staff_details(invitation))
        employee = Employee.objects.create(employee_number="PREFILL", first_name="Staff", last_name="Record",
            email=self.guardian.email, gender="female", date_of_birth=date(1985, 4, 3))
        def check(email):
            request = APIRequestFactory().post("/auth/parent/invitations/email/", {"token": token, "email": email}, format="json")
            return ParentInvitationEmailView.as_view()(request)
        self.assertEqual(check("wrong@example.com").status_code, 400)
        response = check(self.guardian.email)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["staff_details"]["first_name"], "Staff")
        user, _ = register_invited_parent(token=token, email=self.guardian.email, password="Strong-Unique!998877",
            first_name="Tampered", last_name="Tampered", gender="male", date_of_birth=date(2000, 1, 1))
        user.refresh_from_db()
        self.assertEqual((user.first_name, user.last_name, user.gender, user.date_of_birth),
                         ("Staff", "Record", "female", date(1985, 4, 3)))
        self.assertFalse(TenantRoleAssignment.objects.filter(membership__user=user).exists())
        employee.refresh_from_db()
        self.assertFalse(employee.user_account_id_number)
        invitation.refresh_from_db()
        self.assertIsNone(invitation.accepted_at)

    def test_staff_prefill_refuses_duplicate_or_account_linked_records(self):
        from hr.models import Employee
        from users.parent_portal import invitation_staff_details, register_invited_parent
        self.guardian.email = "ambiguous-staff@example.com"
        self.guardian.save()
        employee = Employee.objects.create(employee_number="DUP1", first_name="One", last_name="Staff", email=self.guardian.email)
        duplicate = Employee.objects.create(employee_number="DUP2", first_name="Two", last_name="Staff", email=self.guardian.email)
        invitation, token = self.invite()
        with self.assertRaises(ValidationError):
            invitation_staff_details(invitation)
        with self.assertRaises(ValidationError):
            register_invited_parent(token=token, email=self.guardian.email, password="Strong-Unique!998877", first_name="X", last_name="Y")
        duplicate.delete()
        employee.user_account_id_number = self.user.id_number
        employee.save()
        with self.assertRaises(ValidationError):
            invitation_staff_details(invitation)

    def test_parent_registration_preserves_bio_and_rejects_future_dob(self):
        from datetime import date
        from users.parent_portal import register_invited_parent
        self.guardian.email = "bio-parent@example.com"
        self.guardian.save()
        _, token = self.invite()
        fields = dict(token=token, email=self.guardian.email, password="Strong-Unique!998877", first_name="New", last_name="Parent", gender="female")
        with self.assertRaises(ValidationError):
            register_invited_parent(**fields, date_of_birth=timezone.localdate() + timedelta(days=1))
        user, _ = register_invited_parent(**fields, date_of_birth=date(1990, 2, 1))
        user.refresh_from_db()
        self.assertEqual(user.gender, "female")
        self.assertEqual(user.date_of_birth, date(1990, 2, 1))

    def test_registration_wizard_requires_matching_email_and_grants_nothing(self):
        from users.parent_portal import validate_invitation_email, register_invited_parent
        self.guardian.email = "wizard-parent@example.com"
        self.guardian.save()
        invitation, token = self.invite()
        with self.assertRaises(ValidationError):
            validate_invitation_email(token=token, email="wrong@example.com")
        user, _ = register_invited_parent(token=token, email="WIZARD-PARENT@example.com", password="Strong-Unique!998877", first_name="Wizard", last_name="Parent")
        self.assertTrue(user.check_password("Strong-Unique!998877"))
        self.assertFalse(TenantRoleAssignment.objects.filter(membership__user=user).exists())
        invitation.refresh_from_db()
        self.assertIsNone(invitation.accepted_at)
        with self.assertRaises(ValidationError):
            register_invited_parent(token=token, email=user.email, password="Strong-Unique!998877", first_name="Again", last_name="Parent")
        profile = accept_invitation(token=token, user=user)
        self.assertEqual(profile.user, user)

    def test_invitation_login_requires_credentials_and_live_matching_school_invitation(self):
        from users.parent_portal import register_invited_parent
        from users.security_auth import SecurityTokenObtainPairSerializer
        from rest_framework.request import Request
        self.guardian.email = "wizard-login@example.com"
        self.guardian.save()
        invitation, token = self.invite()
        user, _ = register_invited_parent(token=token, email=self.guardian.email, password="Strong-Unique!998877", first_name="Wizard", last_name="Parent")
        from authorization.exceptions import NoAssignedRole
        request = Request(APIRequestFactory().post("/auth/login/"))
        request.tenant = self.tenant
        with self.assertRaises(NoAssignedRole):
            SecurityTokenObtainPairSerializer(context={"request": request}).validate({"username": user.email, "password": "Strong-Unique!998877"})
        request = APIRequestFactory().post("/auth/login/", {"parent_invitation": token}, format="json")
        # Direct serializer tests supply the parsed DRF payload explicitly.
        from rest_framework.parsers import JSONParser
        from django.contrib.auth.models import AnonymousUser
        parsed = Request(request, parsers=[JSONParser()])
        parsed.tenant = self.tenant
        parsed.user = AnonymousUser()
        context = {"request": parsed}
        payload = SecurityTokenObtainPairSerializer(context=context).validate({"username": user.email, "password": "Strong-Unique!998877"})
        self.assertIn("access", payload)
        self.assertFalse(TenantRoleAssignment.objects.filter(membership__user=user).exists())
        with self.assertRaises(ValidationError):
            SecurityTokenObtainPairSerializer(context=context).validate({"username": user.email, "password": "wrong"})
        invitation.revoked_at = timezone.now()
        invitation.save()
        with self.assertRaises(ValidationError):
            SecurityTokenObtainPairSerializer(context=context).validate({"username": user.email, "password": "Strong-Unique!998877"})

    def test_accept_endpoint_requires_sign_in_and_registration_sends_confirmation(self):
        from unittest.mock import patch
        from django.test import override_settings
        from users.parent_views import ParentAcceptView, ParentInvitationRegisterView
        request = APIRequestFactory().post("/auth/parent/invitations/accept/", {"token": "x"*32}, format="json")
        self.assertIn(ParentAcceptView.as_view()(request).status_code, (401, 403))
        self.guardian.email = "wizard-mail@example.com"
        self.guardian.save()
        _, token = self.invite()
        request = APIRequestFactory().post("/auth/parent/invitations/register/", {"token": token, "email": self.guardian.email, "password": "Strong-Unique!998877", "first_name": "Wizard", "last_name": "Parent"}, format="json")
        with override_settings(PARENT_INVITATIONS_ENABLED=True), patch("common.email_service.send_notification_email", return_value=True) as mail:
            response = ParentInvitationRegisterView.as_view()(request)
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.data["confirmation_sent"])
        mail.assert_called_once()
        self.assertNotIn("Strong-Unique!998877", str(mail.call_args))


class GuardianPortalMutationTests(SimpleTestCase):
    def test_portal_relationship_cannot_be_moved_to_another_student(self):
        from types import SimpleNamespace
        from students.serializers.guardian import StudentGuardianSerializer
        original, other = uuid.uuid4(), uuid.uuid4()
        for state in ("invited", "active", "suspended", "disconnected"):
            serializer = StudentGuardianSerializer(instance=SimpleNamespace(portal_state=state, student_id=original))
            with self.assertRaises(ValidationError):
                serializer.validate_student(SimpleNamespace(pk=other))
            self.assertEqual(serializer.validate_student(SimpleNamespace(pk=original)).pk, original)


class ApprovedGuardianMutationTests(SimpleTestCase):
    def test_approved_waiting_guardian_cannot_move_students(self):
        from types import SimpleNamespace
        from students.serializers.guardian import StudentGuardianSerializer
        guardian = SimpleNamespace(portal_state="unverified", give_access=True, student_id=uuid.uuid4())
        with self.assertRaises(ValidationError):
            StudentGuardianSerializer(instance=guardian).validate_student(SimpleNamespace(pk=uuid.uuid4()))

    def test_deleting_approved_waiting_guardian_disconnects_instead(self):
        from types import SimpleNamespace
        from unittest.mock import patch, Mock
        from students.views.guardian import StudentGuardianDetailView
        guardian = SimpleNamespace(pk=uuid.uuid4(), give_access=True, portal_state="unverified", parent_profile_id=None, student=object(), delete=Mock())
        request = SimpleNamespace(tenant=object(), user=object())
        view = StudentGuardianDetailView()
        with patch.object(view, "get_object", return_value=guardian), patch("students.views.guardian.user_can_access_student_for_permission", return_value=True), patch("users.parent_portal.end_link") as disconnect:
            self.assertEqual(view.delete(request, guardian.pk).status_code, 204)
        disconnect.assert_called_once()
        guardian.delete.assert_not_called()
