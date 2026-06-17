"""Tests for transcript workflow notifications."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from grading.models import TranscriptAccessRequest
from grading.services.transcript_notifications import (
    notify_transcript_approved,
    notify_transcript_denied,
    notify_transcript_requested,
)
from notifications.models import NotificationRule


class TranscriptNotificationDispatchTests(SimpleTestCase):
    @patch("grading.services.transcript_notifications._resolve_transcript_admin_user_ids", return_value=["admin-1"])
    @patch("notifications.services.dispatch.dispatch_from_rule")
    def test_notify_transcript_requested_targets_admins(self, mock_dispatch, _mock_admin_ids):
        student = SimpleNamespace(id="s1", id_number="STU-001")
        student.get_full_name = lambda: "Jane Doe"
        access = SimpleNamespace(student_note="For college")
        reviewer = SimpleNamespace(id="u1")

        notify_transcript_requested(access, student, reviewer)

        mock_dispatch.assert_called_once()
        event_type, payload = mock_dispatch.call_args[0]
        self.assertEqual(event_type, NotificationRule.EventType.TRANSCRIPT_REQUESTED)
        self.assertEqual(payload["audience"], {"scope": "user_ids", "user_ids": ["admin-1"]})
        self.assertEqual(payload["action_url"], "/grading/transcript-requests")
        self.assertIn("Jane Doe", payload["student_name"])

    @patch("notifications.services.dispatch.dispatch_from_rule")
    def test_notify_transcript_approved_targets_student(self, mock_dispatch):
        student = SimpleNamespace(id="s1", id_number="STU-001")
        student.get_full_name = lambda: "Jane Doe"
        access = MagicMock()
        access.allow_download = True
        access.send_email = False
        reviewer = SimpleNamespace(id="admin1")

        notify_transcript_approved(access, student, reviewer)

        mock_dispatch.assert_called_once()
        event_type, payload = mock_dispatch.call_args[0]
        self.assertEqual(event_type, NotificationRule.EventType.TRANSCRIPT_APPROVED)
        self.assertEqual(
            payload["audience"],
            {"scope": "students", "student_ids": ["s1"]},
        )
        self.assertEqual(payload["action_url"], "/my-reports")

    def test_notify_transcript_requested_skips_when_no_admins(self):
        student = SimpleNamespace(id="s1", id_number="STU-001")
        student.get_full_name = lambda: "Jane Doe"
        access = SimpleNamespace(id="req-1", student_note="")
        reviewer = SimpleNamespace(id="u1")

        with patch(
            "grading.services.transcript_notifications._resolve_transcript_admin_user_ids",
            return_value=[],
        ), patch("notifications.services.dispatch.dispatch_from_rule") as mock_dispatch:
            notify_transcript_requested(access, student, reviewer)

        mock_dispatch.assert_not_called()

    @patch("notifications.services.dispatch.dispatch_from_rule")
    def test_notify_transcript_denied_targets_student(self, mock_dispatch):
        student = SimpleNamespace(id="s1", id_number="STU-001")
        student.get_full_name = lambda: "Jane Doe"
        access = SimpleNamespace(admin_note="Missing documents")
        reviewer = SimpleNamespace(id="admin1")

        notify_transcript_denied(access, student, reviewer)

        mock_dispatch.assert_called_once()
        event_type, payload = mock_dispatch.call_args[0]
        self.assertEqual(event_type, NotificationRule.EventType.TRANSCRIPT_DENIED)
        self.assertEqual(
            payload["audience"],
            {"scope": "students", "student_ids": ["s1"]},
        )


class TranscriptAccessNotificationHooksTests(SimpleTestCase):
    @patch("grading.services.transcript_notifications.notify_transcript_requested")
    @patch("grading.services.transcript_access.TranscriptAccessRequest.objects.create")
    @patch("grading.services.transcript_access.get_active_approved_access", return_value=None)
    @patch("grading.services.transcript_access.get_pending_request", return_value=None)
    @patch("grading.services.transcript_access.get_grading_settings", return_value=None)
    @patch("grading.services.transcript_access._student_matches_user", return_value=True)
    def test_create_student_request_emits_notification(
        self,
        _mock_match,
        _mock_settings,
        _mock_pending,
        _mock_active,
        mock_create,
        mock_notify,
    ):
        from grading.services.transcript_access import create_student_request

        user = SimpleNamespace(id="u1")
        student = SimpleNamespace(id="s1")
        record = MagicMock()
        mock_create.return_value = record

        result = create_student_request(user, student, student_note="Need transcript")

        self.assertIs(result, record)
        mock_notify.assert_called_once_with(record, student, user)

    @patch("grading.services.transcript_notifications.notify_transcript_approved")
    @patch("grading.services.transcript_access._deliver_transcript_email_async")
    @patch("grading.services.transcript_access._is_transcript_admin", return_value=True)
    @patch("grading.services.transcript_access.get_default_download_days", return_value=3)
    @patch("grading.services.transcript_access.get_grading_settings", return_value=None)
    def test_approve_pending_student_request_notifies_student(
        self,
        _mock_settings,
        _mock_days,
        _mock_admin,
        _mock_email,
        mock_notify,
    ):
        from grading.services.transcript_access import approve_or_grant_access

        student = SimpleNamespace(id="s1")
        reviewer = SimpleNamespace(id="admin1")
        access_request = MagicMock()
        access_request.status = TranscriptAccessRequest.Status.PENDING
        access_request.source = TranscriptAccessRequest.Source.STUDENT_REQUEST
        access_request.email_sent_at = None

        record = approve_or_grant_access(
            student=student,
            reviewer=reviewer,
            allow_download=True,
            send_email=False,
            access_request=access_request,
        )

        mock_notify.assert_called_once_with(record, student, reviewer)

    @patch("grading.services.transcript_notifications.notify_transcript_denied")
    @patch("grading.services.transcript_access._is_transcript_admin", return_value=True)
    def test_deny_student_request_notifies_student(self, _mock_admin, mock_notify):
        from grading.services.transcript_access import deny_request

        student = SimpleNamespace(id="s1")
        access_request = MagicMock()
        access_request.status = TranscriptAccessRequest.Status.PENDING
        access_request.source = TranscriptAccessRequest.Source.STUDENT_REQUEST
        access_request.student = student
        reviewer = SimpleNamespace(id="admin1")

        deny_request(access_request, reviewer, admin_note="Incomplete")

        mock_notify.assert_called_once_with(access_request, student, reviewer)
