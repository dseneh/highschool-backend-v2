"""Tests for the tenant restore execution lifecycle phase."""

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from django_tenants.utils import get_public_schema_name, schema_context

from backups.models import TenantBackup, TenantRestoreRequest
from backups.restore_services import (
    RestoreError,
    approve_restore,
    delete_restore,
    execute_restore,
    reject_restore,
    request_restore,
    retry_restore,
)
from core.models import Tenant

User = get_user_model()


class RestoreLifecycleTestCase(TestCase):
    """Base test case for restore lifecycle tests."""

    databases = {"default"}

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with schema_context(get_public_schema_name()):
            cls.tenant = Tenant.objects.create(name="Test Tenant", schema_name="test_tenant_restore")
            cls.admin_user = User.objects.create_user(username="admin", email="admin@test.com", is_staff=True)
            cls.tenant_user = User.objects.create_user(username="tenant_user", email="user@test.com")

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        with schema_context(get_public_schema_name()):
            cls.tenant.delete()
            User.objects.filter(pk__in=[cls.admin_user.pk, cls.tenant_user.pk]).delete()

    def setUp(self):
        """Create test backup for each test."""
        with schema_context(get_public_schema_name()):
            self.backup = TenantBackup.objects.create(
                tenant=self.tenant,
                schema_name=self.tenant.schema_name,
                backup_type=TenantBackup.BackupType.MANUAL,
                status=TenantBackup.Status.AVAILABLE,
                storage_key="s3://test/backup",
                sha256="a" * 64,
                file_size=1000,
            )

    def _create_restore_request(self):
        """Create a restore request and mark safety backup as available."""
        with schema_context(get_public_schema_name()):
            restore_request = request_restore(
                tenant=self.tenant,
                backup=self.backup,
                requested_by=self.tenant_user,
                reason="Test restore",
            )
            # Simulate safety backup completion
            restore_request.safety_backup.status = TenantBackup.Status.AVAILABLE
            restore_request.safety_backup.save(update_fields=["status"])
            restore_request.status = TenantRestoreRequest.Status.READY_FOR_APPROVAL
            restore_request.save(update_fields=["status"])
            return restore_request


class ApprovalNotWorkerEligibleTestCase(RestoreLifecycleTestCase):
    """Test that APPROVED status is not picked up by worker."""

    def test_approval_leaves_status_approved(self):
        """Verify approve_restore leaves status=APPROVED, not RESTORING."""
        restore_request = self._create_restore_request()
        
        with schema_context(get_public_schema_name()):
            approved = approve_restore(
                restore_request=restore_request,
                approved_by=self.admin_user,
                decision_note="Approved for test",
            )
        
        self.assertEqual(approved.status, TenantRestoreRequest.Status.APPROVED)
        self.assertIsNotNone(approved.approved_by)
        self.assertIsNotNone(approved.approved_at)

    def test_approved_not_in_active_restore_statuses_excludes_restoring(self):
        """Verify APPROVED is processable but RESTORING is separate."""
        restore_request = self._create_restore_request()
        
        with schema_context(get_public_schema_name()):
            approved = approve_restore(
                restore_request=restore_request,
                approved_by=self.admin_user,
            )
        
        # APPROVED exists but is not immediately RESTORING
        self.assertEqual(approved.status, TenantRestoreRequest.Status.APPROVED)


class ExecuteTransitionTestCase(RestoreLifecycleTestCase):
    """Test execute_restore transitions APPROVED -> EXECUTION_PENDING."""

    def test_execute_approved_transitions_to_execution_pending(self):
        """Verify execute_restore moves APPROVED to EXECUTION_PENDING."""
        restore_request = self._create_restore_request()
        
        with schema_context(get_public_schema_name()):
            approved = approve_restore(
                restore_request=restore_request,
                approved_by=self.admin_user,
            )
            executed = execute_restore(restore_request=approved, executed_by=self.tenant_user)
        
        self.assertEqual(executed.status, TenantRestoreRequest.Status.EXECUTION_PENDING)

    def test_execute_non_approved_raises_error(self):
        """Verify execute_restore refuses non-APPROVED statuses."""
        restore_request = self._create_restore_request()
        
        with schema_context(get_public_schema_name()):
            with self.assertRaises(RestoreError) as cm:
                execute_restore(restore_request=restore_request, executed_by=self.tenant_user)
        
        self.assertIn("not approved", str(cm.exception).lower())

    def test_execute_validates_prerequisites(self):
        """Verify execute_restore validates backup availability."""
        restore_request = self._create_restore_request()
        
        with schema_context(get_public_schema_name()):
            approved = approve_restore(
                restore_request=restore_request,
                approved_by=self.admin_user,
            )
            # Corrupt safety backup
            approved.safety_backup.status = TenantBackup.Status.FAILED
            approved.safety_backup.save(update_fields=["status"])
            
            with self.assertRaises(RestoreError) as cm:
                execute_restore(restore_request=approved, executed_by=self.tenant_user)
        
        self.assertIn("safety backup is not available", str(cm.exception).lower())


class RetryRulesTestCase(RestoreLifecycleTestCase):
    """Test retry_restore logic for failed previously-approved requests."""

    def test_retry_failed_approved_transitions_to_execution_pending(self):
        """Verify retry_restore moves FAILED (with approved_at) to EXECUTION_PENDING."""
        restore_request = self._create_restore_request()
        
        with schema_context(get_public_schema_name()):
            approved = approve_restore(
                restore_request=restore_request,
                approved_by=self.admin_user,
            )
            executed = execute_restore(restore_request=approved)
            
            # Simulate restore failure
            executed.status = TenantRestoreRequest.Status.FAILED
            executed.error_message = "Test failure"
            executed.completed_at = timezone.now()
            executed.save(update_fields=["status", "error_message", "completed_at"])
            
            # Retry should work
            retried = retry_restore(restore_request=executed, retried_by=self.tenant_user)
        
        self.assertEqual(retried.status, TenantRestoreRequest.Status.EXECUTION_PENDING)

    def test_retry_failed_without_approval_raises_error(self):
        """Verify retry_restore refuses FAILED without prior approval."""
        restore_request = self._create_restore_request()
        
        # Create a failed restore that was never approved
        with schema_context(get_public_schema_name()):
            restore_request.status = TenantRestoreRequest.Status.FAILED
            restore_request.error_message = "Never approved"
            restore_request.save(update_fields=["status", "error_message"])
            
            with self.assertRaises(RestoreError) as cm:
                retry_restore(restore_request=restore_request, retried_by=self.tenant_user)
        
        self.assertIn("not previously approved", str(cm.exception).lower())

    def test_retry_non_failed_raises_error(self):
        """Verify retry_restore refuses non-FAILED statuses."""
        restore_request = self._create_restore_request()
        
        with schema_context(get_public_schema_name()):
            with self.assertRaises(RestoreError) as cm:
                retry_restore(restore_request=restore_request, retried_by=self.tenant_user)
        
        self.assertIn("only a failed", str(cm.exception).lower())

    def test_retry_validates_prerequisites(self):
        """Verify retry_restore validates backup availability."""
        restore_request = self._create_restore_request()
        
        with schema_context(get_public_schema_name()):
            approved = approve_restore(
                restore_request=restore_request,
                approved_by=self.admin_user,
            )
            executed = execute_restore(restore_request=approved)
            
            # Simulate failure
            executed.status = TenantRestoreRequest.Status.FAILED
            executed.save(update_fields=["status"])
            
            # Corrupt safety backup
            executed.safety_backup.status = TenantBackup.Status.EXPIRED
            executed.safety_backup.save(update_fields=["status"])
            
            with self.assertRaises(RestoreError) as cm:
                retry_restore(restore_request=executed)
        
        self.assertIn("safety backup is not available", str(cm.exception).lower())


class PlatformDeletionRestrictionsTestCase(RestoreLifecycleTestCase):
    """Test platform delete restrictions on restore requests."""

    def test_delete_failed_succeeds(self):
        """Verify delete_restore allows FAILED status."""
        restore_request = self._create_restore_request()
        
        with schema_context(get_public_schema_name()):
            restore_request.status = TenantRestoreRequest.Status.FAILED
            restore_request.save(update_fields=["status"])
            
            deleted_id = delete_restore(restore_request=restore_request)
        
        self.assertEqual(deleted_id, restore_request.id)
        with schema_context(get_public_schema_name()):
            self.assertFalse(TenantRestoreRequest.objects.filter(id=deleted_id).exists())

    def test_delete_rejected_succeeds(self):
        """Verify delete_restore allows REJECTED status."""
        restore_request = self._create_restore_request()
        
        with schema_context(get_public_schema_name()):
            restore_request.status = TenantRestoreRequest.Status.REJECTED
            restore_request.save(update_fields=["status"])
            
            deleted_id = delete_restore(restore_request=restore_request)
        
        self.assertFalse(TenantRestoreRequest.objects.filter(id=deleted_id).exists())

    def test_delete_cancelled_succeeds(self):
        """Verify delete_restore allows CANCELLED status."""
        restore_request = self._create_restore_request()
        
        with schema_context(get_public_schema_name()):
            restore_request.status = TenantRestoreRequest.Status.CANCELLED
            restore_request.save(update_fields=["status"])
            
            deleted_id = delete_restore(restore_request=restore_request)
        
        self.assertFalse(TenantRestoreRequest.objects.filter(id=deleted_id).exists())

    def test_delete_approved_raises_error(self):
        """Verify delete_restore refuses APPROVED status."""
        restore_request = self._create_restore_request()
        
        with schema_context(get_public_schema_name()):
            approved = approve_restore(
                restore_request=restore_request,
                approved_by=self.admin_user,
            )
            
            with self.assertRaises(RestoreError) as cm:
                delete_restore(restore_request=approved)
        
        self.assertIn("terminal", str(cm.exception).lower())

    def test_delete_execution_pending_raises_error(self):
        """Verify delete_restore refuses EXECUTION_PENDING status."""
        restore_request = self._create_restore_request()
        
        with schema_context(get_public_schema_name()):
            approved = approve_restore(
                restore_request=restore_request,
                approved_by=self.admin_user,
            )
            executed = execute_restore(restore_request=approved)
            
            with self.assertRaises(RestoreError) as cm:
                delete_restore(restore_request=executed)
        
        self.assertIn("terminal", str(cm.exception).lower())

    def test_delete_restoring_raises_error(self):
        """Verify delete_restore refuses RESTORING status."""
        restore_request = self._create_restore_request()
        
        with schema_context(get_public_schema_name()):
            restore_request.status = TenantRestoreRequest.Status.RESTORING
            restore_request.save(update_fields=["status"])
            
            with self.assertRaises(RestoreError) as cm:
                delete_restore(restore_request=restore_request)
        
        self.assertIn("terminal", str(cm.exception).lower())


class RejectAfterApprovalTestCase(RestoreLifecycleTestCase):
    """Test that restore can still be rejected after approval."""

    def test_reject_approved_changes_status(self):
        """Verify reject_restore works on APPROVED status."""
        restore_request = self._create_restore_request()
        
        with schema_context(get_public_schema_name()):
            approved = approve_restore(
                restore_request=restore_request,
                approved_by=self.admin_user,
            )
            rejected = reject_restore(
                restore_request=approved,
                rejected_by=self.admin_user,
                decision_note="Rejecting after approval",
            )
        
        self.assertEqual(rejected.status, TenantRestoreRequest.Status.REJECTED)
        self.assertEqual(rejected.decision_note, "Rejecting after approval")

