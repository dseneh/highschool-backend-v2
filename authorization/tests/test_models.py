from types import SimpleNamespace
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from authorization.models import Role, RolePermission
from authorization.signals import seed_system_roles_for_new_tenant


class RolePermissionValidationTests(SimpleTestCase):
    def test_rejects_unknown_permission_code(self):
        grant = RolePermission(permission_code="unknown.permission", scope="all")

        with self.assertRaises(ValidationError):
            grant.clean()

    def test_rejects_scope_not_allowed_by_registry(self):
        grant = RolePermission(permission_code="grades.approve", scope="assigned")

        with self.assertRaises(ValidationError):
            grant.clean()

    def test_accepts_registry_permission_scope(self):
        grant = RolePermission(permission_code="grades.enter", scope="assigned")

        grant.clean()


class SystemRoleProtectionTests(SimpleTestCase):
    def test_rejects_inconsistent_system_key(self):
        role = Role(name="Admin", is_system_role=True)

        with self.assertRaises(ValidationError):
            role.clean()

    def test_rejects_system_role_changes(self):
        role = Role(name="Admin", system_key="admin", is_system_role=True)
        role._loaded_values = {
            "name": "Admin",
            "description": "Original",
            "system_key": "admin",
            "is_system_role": True,
            "is_default": False,
            "is_active": True,
        }
        role.description = "Changed"

        with self.assertRaises(ValidationError):
            role.save()

    def test_rejects_system_role_deletion(self):
        role = Role(name="Admin", system_key="admin", is_system_role=True)

        with self.assertRaises(ValidationError):
            role.delete()

    def test_rejects_system_role_permission_changes(self):
        role = Role(name="Admin", system_key="admin", is_system_role=True)
        grant = RolePermission(
            role=role,
            permission_code="students.view",
            scope="all",
        )

        with self.assertRaises(ValidationError):
            grant.save()
        with self.assertRaises(ValidationError):
            grant.delete()


class ProvisioningSignalTests(SimpleTestCase):
    @patch("authorization.signals.sync_system_roles")
    def test_public_schema_is_never_seeded(self, mock_sync):
        seed_system_roles_for_new_tenant(
            sender=None,
            tenant=SimpleNamespace(schema_name="public"),
        )

        mock_sync.assert_not_called()
