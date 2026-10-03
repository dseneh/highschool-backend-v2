from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings


class BackupRuntimeCheckTests(SimpleTestCase):
    @override_settings(USE_S3_STORAGE=False)
    @patch("backups.management.commands.check_backup_runtime.connection")
    @patch("backups.management.commands.check_backup_runtime.shutil.which", return_value=None)
    def test_production_backup_worker_rejects_missing_tools_and_object_storage(
        self, _which, connection
    ):
        connection.ensure_connection.return_value = None
        connection.cursor.return_value.__enter__.return_value = MagicMock()

        with self.assertRaisesMessage(CommandError, "pg_dump is not installed"):
            call_command(
                "check_backup_runtime",
                mode="backup",
                require_object_storage=True,
            )

    @override_settings(USE_S3_STORAGE=True)
    @patch(
        "backups.management.commands.check_backup_runtime.storages",
        {"backups": SimpleNamespace(bucket_name="production-backups")},
    )
    @patch("backups.management.commands.check_backup_runtime.connection")
    @patch("backups.management.commands.check_backup_runtime.shutil.which", return_value="/usr/bin/pg_restore")
    def test_restore_worker_accepts_complete_runtime(self, _which, connection):
        cursor = MagicMock()
        connection.ensure_connection.return_value = None
        connection.cursor.return_value.__enter__.return_value = cursor

        call_command(
            "check_backup_runtime",
            mode="restore",
            require_object_storage=True,
        )

        cursor.execute.assert_called_once_with("SELECT 1")
