"""Tests for transcript access authorization and workflow."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from django.utils import timezone

from grading.models import TranscriptAccessRequest
from grading.services.transcript_access import (
    build_access_status,
    can_download_transcript,
    delete_transcript_request,
    deny_request,
    get_default_download_days,
    update_transcript_request_status,
)


class TranscriptAccessAuthorizationTests(SimpleTestCase):
    @patch("grading.services.transcript_access.get_active_approved_access")
    def test_admin_can_download_with_granted_access(self, mock_active):
        mock_active.return_value = SimpleNamespace(
            is_download_active=True,
            allow_download=True,
        )
        admin = SimpleNamespace(
            is_authenticated=True,
            is_superuser=False,
            is_admin=True,
            is_student_user=False,
            role="ADMIN",
            privileges=[],
            get_student=lambda: None,
        )
        student = SimpleNamespace(id="s1", status="active")
        allowed, reason = can_download_transcript(admin, student)
        self.assertTrue(allowed)
        self.assertEqual(reason, "admin")

    @patch("grading.services.transcript_access.get_active_approved_access")
    @patch("grading.services.transcript_access.get_grading_settings")
    @patch("grading.services.transcript_access._student_eligible_for_self_service")
    @patch("grading.services.transcript_access._student_matches_user")
    def test_admin_can_download_without_granted_access(
        self,
        mock_matches,
        mock_eligible,
        mock_settings,
        mock_active,
    ):
        mock_active.return_value = None
        mock_settings.return_value = None
        mock_eligible.return_value = False
        mock_matches.return_value = False

        admin = SimpleNamespace(
            is_authenticated=True,
            is_superuser=False,
            is_admin=True,
            is_student_user=False,
            role="ADMIN",
            privileges=[],
            get_student=lambda: None,
        )
        student = SimpleNamespace(id="s1", status="active")
        allowed, reason = can_download_transcript(admin, student)
        self.assertTrue(allowed)
        self.assertEqual(reason, "admin")

    @patch("grading.services.transcript_access.get_active_approved_access")
    @patch("grading.services.transcript_access.get_grading_settings")
    @patch("grading.services.transcript_access._student_eligible_for_self_service")
    @patch("grading.services.transcript_access._student_matches_user")
    def test_student_self_service(
        self,
        mock_matches,
        mock_eligible,
        mock_settings,
        mock_active,
    ):
        mock_active.return_value = None
        mock_settings.return_value = SimpleNamespace(
            allow_student_transcript_download=True,
            student_transcript_download_scope="enrolled",
            transcript_download_days=3,
        )
        mock_eligible.return_value = True
        mock_matches.return_value = True

        user = SimpleNamespace(
            is_authenticated=True,
            is_superuser=False,
            is_admin=False,
            is_student_user=True,
            role="STUDENT",
            privileges=[],
            get_student=lambda: SimpleNamespace(id="s1"),
        )
        student = SimpleNamespace(id="s1", status="active")

        allowed, reason = can_download_transcript(user, student)
        self.assertTrue(allowed)
        self.assertEqual(reason, "self_service")

    @patch("grading.services.transcript_access.get_active_approved_access")
    @patch("grading.services.transcript_access.get_grading_settings")
    @patch("grading.services.transcript_access._student_eligible_for_self_service")
    @patch("grading.services.transcript_access._student_matches_user")
    def test_student_with_approved_access(
        self,
        mock_matches,
        mock_eligible,
        mock_settings,
        mock_active,
    ):
        mock_settings.return_value = SimpleNamespace(
            allow_student_transcript_download=False,
            student_transcript_download_scope="enrolled",
            transcript_download_days=3,
        )
        mock_eligible.return_value = False
        mock_matches.return_value = True
        mock_active.return_value = SimpleNamespace(
            is_download_active=True,
            allow_download=True,
        )

        user = SimpleNamespace(
            is_authenticated=True,
            is_superuser=False,
            is_admin=False,
            is_student_user=True,
            role="STUDENT",
            privileges=[],
            get_student=lambda: SimpleNamespace(id="s1"),
        )
        student = SimpleNamespace(id="s1", status="active")

        allowed, reason = can_download_transcript(user, student)
        self.assertTrue(allowed)
        self.assertEqual(reason, "approved_access")

    @patch("grading.services.transcript_access.get_active_approved_access")
    @patch("grading.services.transcript_access.get_grading_settings")
    @patch("grading.services.transcript_access._student_eligible_for_self_service")
    @patch("grading.services.transcript_access._student_matches_user")
    def test_student_denied_without_access(
        self,
        mock_matches,
        mock_eligible,
        mock_settings,
        mock_active,
    ):
        mock_settings.return_value = None
        mock_eligible.return_value = False
        mock_matches.return_value = True
        mock_active.return_value = None

        user = SimpleNamespace(
            is_authenticated=True,
            is_superuser=False,
            is_admin=False,
            is_student_user=True,
            role="STUDENT",
            privileges=[],
            get_student=lambda: SimpleNamespace(id="s1"),
        )
        student = SimpleNamespace(id="s1", status="active")

        allowed, reason = can_download_transcript(user, student)
        self.assertFalse(allowed)
        self.assertEqual(reason, "not_authorized")


class TranscriptAccessStatusTests(SimpleTestCase):
    @patch("grading.services.transcript_access.get_pending_request")
    @patch("grading.services.transcript_access.get_active_approved_access")
    @patch("grading.services.transcript_access.can_download_transcript")
    @patch("grading.services.transcript_access.get_grading_settings")
    @patch("grading.services.transcript_access._student_eligible_for_self_service")
    @patch("grading.services.transcript_access._student_matches_user")
    @patch("grading.services.transcript_access._is_transcript_admin")
    def test_build_access_status_for_student(
        self,
        mock_is_admin,
        mock_matches,
        mock_eligible,
        mock_settings,
        mock_can_download,
        mock_active,
        mock_pending,
    ):
        mock_is_admin.return_value = False
        mock_matches.return_value = True
        mock_eligible.return_value = False
        mock_settings.return_value = SimpleNamespace(
            allow_student_transcript_download=False,
            student_transcript_download_scope="enrolled",
            transcript_download_days=5,
        )
        mock_can_download.return_value = (False, "not_authorized")
        mock_active.return_value = None
        mock_pending.return_value = SimpleNamespace(
            id="req-1",
            status="pending",
            source="student_request",
            allow_download=False,
            send_email=False,
            download_expires_at=None,
            email_sent_at=None,
            student_note="Need for college",
            admin_note="",
            created_at=timezone.now(),
            reviewed_at=None,
            is_download_active=False,
            mark_expired_if_needed=lambda: False,
        )

        user = SimpleNamespace(is_student_user=True, get_student=lambda: SimpleNamespace(id="s1"))
        student = SimpleNamespace(id="s1", status="active")

        payload = build_access_status(user, student)
        self.assertFalse(payload["can_download"])
        self.assertTrue(payload["is_student_owner"])
        self.assertEqual(payload["pending_request"]["student_note"], "Need for college")
        self.assertEqual(payload["settings"]["transcript_download_days"], 5)


class TranscriptAccessDefaultsTests(SimpleTestCase):
    @patch("grading.services.transcript_access.get_grading_settings", return_value=None)
    def test_default_download_days_fallback(self, _mock_settings):
        self.assertEqual(get_default_download_days(None), 3)
        self.assertEqual(
            get_default_download_days(SimpleNamespace(transcript_download_days=0)),
            3,
        )


class TranscriptRequestAdminMutationTests(SimpleTestCase):
    def _admin(self):
        return SimpleNamespace(
            is_authenticated=True,
            is_superuser=False,
            is_admin=True,
            is_student_user=False,
            role="ADMIN",
            privileges=[],
        )

    @patch("grading.services.transcript_access._is_transcript_admin", return_value=True)
    def test_deny_request_from_approved_clears_download(self, _mock_admin):
        access = MagicMock()
        access.status = TranscriptAccessRequest.Status.APPROVED
        access.allow_download = True
        access.download_expires_at = timezone.now()

        result = deny_request(access, self._admin(), admin_note="Revoked")

        self.assertEqual(result.status, TranscriptAccessRequest.Status.DENIED)
        self.assertFalse(result.allow_download)
        self.assertIsNone(result.download_expires_at)
        self.assertEqual(result.admin_note, "Revoked")
        access.save.assert_called_once()

    @patch("grading.services.transcript_access._is_transcript_admin", return_value=True)
    def test_update_status_to_expired_clears_download(self, _mock_admin):
        access = MagicMock()
        access.status = TranscriptAccessRequest.Status.APPROVED
        access.allow_download = True
        access.download_expires_at = timezone.now()

        result = update_transcript_request_status(
            access,
            self._admin(),
            status=TranscriptAccessRequest.Status.EXPIRED,
            admin_note="Window closed",
        )

        self.assertEqual(result.status, TranscriptAccessRequest.Status.EXPIRED)
        self.assertFalse(result.allow_download)
        self.assertIsNone(result.download_expires_at)
        access.save.assert_called_once()

    @patch("grading.services.transcript_access._is_transcript_admin", return_value=True)
    def test_update_status_reopen_pending_clears_review(self, _mock_admin):
        access = MagicMock()
        access.status = TranscriptAccessRequest.Status.DENIED
        access.reviewed_by = self._admin()
        access.reviewed_at = timezone.now()
        access.allow_download = False
        access.download_expires_at = None

        result = update_transcript_request_status(
            access,
            self._admin(),
            status=TranscriptAccessRequest.Status.PENDING,
        )

        self.assertEqual(result.status, TranscriptAccessRequest.Status.PENDING)
        self.assertIsNone(result.reviewed_by)
        self.assertIsNone(result.reviewed_at)
        access.save.assert_called_once()

    @patch("grading.services.transcript_access._is_transcript_admin", return_value=True)
    def test_update_status_rejects_approved(self, _mock_admin):
        access = MagicMock()
        access.status = TranscriptAccessRequest.Status.PENDING

        with self.assertRaises(ValueError):
            update_transcript_request_status(
                access,
                self._admin(),
                status=TranscriptAccessRequest.Status.APPROVED,
            )

    @patch("grading.services.transcript_access._is_transcript_admin", return_value=False)
    def test_delete_requires_admin(self, _mock_admin):
        access = MagicMock()

        with self.assertRaises(PermissionError):
            delete_transcript_request(access, SimpleNamespace(is_authenticated=True))

        access.delete.assert_not_called()

    @patch("grading.services.transcript_access._is_transcript_admin", return_value=True)
    def test_delete_removes_record(self, _mock_admin):
        access = MagicMock()

        delete_transcript_request(access, self._admin())

        access.delete.assert_called_once()
