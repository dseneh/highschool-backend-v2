from types import SimpleNamespace
from unittest.mock import patch

from rest_framework.exceptions import ValidationError, PermissionDenied
from students.models import StudentContact, StudentGuardian
from students.views.guardian import StudentGuardianListView, StudentGuardianDetailView
from users.models import User
from authorization.models import TenantRoleAssignment
from users.test_parent_portal import ParentPortalTests


class GuardianRecordLifecycleTests(ParentPortalTests):
    def request(self, data=None, delete=False):
        return SimpleNamespace(user=self.tenant.owner, tenant=self.tenant, data=data or {},
                               query_params={"delete_record": "true"} if delete else {})

    def test_form_access_defaults_off_and_validates_before_commit(self):
        view = StudentGuardianListView()
        data = {"first_name": "Another", "last_name": "Parent", "email": "new-parent@example.com"}
        with patch("students.views.guardian.user_can_access_student_for_permission", return_value=True), patch("students.authorization.permission_scope", return_value="all"):
            response = view.post(self.request(data), self.student.pk)
            self.assertEqual(response.status_code, 201)
            self.assertFalse(response.data["give_access"])
            before = StudentGuardian.objects.count()
            with self.assertRaises(ValidationError):
                view.post(self.request({**data, "email": "", "give_access": True}), self.student.pk)
            self.assertEqual(StudentGuardian.objects.count(), before)
            response = view.post(self.request({**data, "give_access": True}), self.student.pk)
            self.assertTrue(response.data["give_access"])
            self.assertEqual(response.data["portal_state"], "unverified")
            self.assertFalse(User.objects.filter(email=data["email"]).exists())

    def test_access_switch_requires_school_approval_scope(self):
        with patch("students.views.guardian.user_can_access_student_for_permission", return_value=True), patch("students.authorization.permission_scope", return_value="own"):
            with self.assertRaises(PermissionDenied):
                StudentGuardianListView().post(self.request({"first_name": "Parent", "last_name": "Two", "email": "p@example.com", "give_access": True}), self.student.pk)

    def test_explicit_delete_removes_record_and_mirror_but_keeps_identity(self):
        profile, link = self.activate()
        guardian_id = self.guardian.pk
        self.assertTrue(StudentContact.objects.filter(portal_guardian_id=guardian_id).exists())
        other = StudentGuardian.objects.create(student=self.student, first_name="Other", last_name="Guardian")
        with patch("students.views.guardian.user_can_access_student_for_permission", return_value=True):
            response = StudentGuardianDetailView().delete(self.request(delete=True), guardian_id)
        self.assertEqual(response.status_code, 204)
        self.assertFalse(StudentGuardian.objects.filter(pk=guardian_id).exists())
        self.assertFalse(StudentContact.objects.filter(portal_guardian_id=guardian_id).exists())
        self.assertTrue(StudentGuardian.objects.filter(pk=other.pk).exists())
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())
        self.assertTrue(TenantRoleAssignment.objects.filter(membership__user=self.user, role_key="system:teacher", is_active=True).exists())
        self.assertFalse(TenantRoleAssignment.objects.filter(membership__user=self.user, role_key="system:parent", is_active=True).exists())
        self.student.refresh_from_db()
        link.refresh_from_db()
        self.assertFalse(link.active)

    def test_form_disable_disconnects_without_deleting_school_records(self):
        profile, link = self.activate()
        with patch("students.views.guardian.user_can_access_student_for_permission", return_value=True), patch("students.authorization.permission_scope", return_value="all"):
            response = StudentGuardianDetailView().put(self.request({"give_access": False}), self.guardian.pk)
        self.assertEqual(response.status_code, 200)
        self.guardian.refresh_from_db()
        self.assertFalse(self.guardian.give_access)
        self.assertEqual(self.guardian.portal_state, "disconnected")
        self.assertTrue(StudentContact.objects.filter(portal_guardian_id=self.guardian.pk).exists())
        link.refresh_from_db()
        self.assertFalse(link.active)
