from django_tenants.utils import schema_context
from rest_framework.test import APIRequestFactory, force_authenticate
from users.test_parent_portal import ParentPortalTests
from users.models import ParentProfile, User
from students.models import Student, StudentContact
from students.contact_notifications import send_contact_notice
from notifications.models import Notification, NotificationDelivery
from users.parent_notifications import ParentNotificationsView


class ContactNotificationTests(ParentPortalTests):
    def setUp(self):
        with self.captureOnCommitCallbacks(execute=True):
            super().setUp()

    def test_guardian_notice_is_in_app_once_and_does_not_grant_access(self):
        notice = Notification.objects.get(recipient=self.user)
        self.assertEqual(notice.campaign.channels, ["in_app"])
        self.assertEqual(notice.campaign.title, "Added as a guardian")
        self.assertNotIn(self.student.get_full_name(), notice.campaign.body)
        self.assertFalse(NotificationDelivery.objects.exists())
        self.assertFalse(ParentProfile.objects.filter(user=self.user).exists())
        self.guardian.phone_number = "1234"
        self.guardian.save()
        contact = self.student.contacts.get(portal_guardian_id=self.guardian.pk)
        send_contact_notice(self.tenant.schema_name, contact.pk)
        self.assertEqual(Notification.objects.filter(recipient=self.user).count(), 1)
        from django.db import transaction
        with self.captureOnCommitCallbacks(execute=True):
            try:
                with transaction.atomic():
                    StudentContact.objects.create(student=self.student, first_name="Rollback", last_name="Contact", email=self.user.email)
                    raise ValueError("rollback")
            except ValueError:
                pass
        self.assertEqual(Notification.objects.filter(recipient=self.user).count(), 1)

    def test_parent_and_other_contact_notices_target_only_existing_account(self):
        for relation in ("parent", "teacher"):
            with self.captureOnCommitCallbacks(execute=True):
                StudentContact.objects.create(student=self.student, first_name="Contact", last_name=relation, email=self.user.email.upper(), relationship=relation)
        self.assertEqual(Notification.objects.filter(recipient=self.user).count(), 3)
        self.assertTrue(Notification.objects.filter(campaign__title="Added as a parent").exists())
        self.assertTrue(Notification.objects.filter(campaign__title="Added as a contact").exists())
        with self.captureOnCommitCallbacks(execute=True):
            StudentContact.objects.create(student=self.student, first_name="No", last_name="Account", email="absent@example.invalid")
        self.assertEqual(Notification.objects.count(), 3)

    def test_global_inbox_combines_schools_and_blocks_other_recipients(self):
        ParentProfile.objects.create(user=self.user)
        with schema_context(self.other_tenant.schema_name):
            student = Student.objects.create(first_name="Other", last_name="Child", id_number="99901", entry_as="new", school_code=1, student_seq=99901)
            with self.captureOnCommitCallbacks(execute=True):
                StudentContact.objects.create(student=student, first_name="Parent", last_name="Contact", email=self.user.email, relationship="parent")
            other_notice = Notification.objects.get(recipient=self.user)
            key = f"{self.other_tenant.pk}:{other_notice.pk}"
        factory = APIRequestFactory()
        def call(method, action="", user=None, data=None):
            request = getattr(factory, method)("/api/v1/auth/parent/notifications/", data or {}, format="json")
            force_authenticate(request, user=user or self.user)
            with schema_context("public"):
                return ParentNotificationsView.as_view()(request, action=action)
        result = call("get")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.data["count"], 2)
        self.assertTrue(all(not item["can_delete"] for item in result.data["results"]))
        self.assertEqual(call("patch", key + "/mark-read", data={"read": True}).status_code, 200)
        self.assertEqual(call("get", "unread-count").data["unread_count"], 1)
        stranger = User.objects.create(email="stranger@example.invalid", id_number="STRANGER")
        ParentProfile.objects.create(user=stranger)
        self.assertEqual(call("patch", key + "/mark-read", user=stranger).status_code, 404)
        self.assertEqual(call("get", user=stranger).data["count"], 0)
        self.assertEqual(call("patch", "mark-all-read").data["marked"], 1)
