import json
import tempfile
import unittest
from pathlib import Path

from authorization.generator import render_permission_constants
from authorization.registry import (
    get_permission_registry,
    load_permission_registry,
)
from authorization.system_roles import get_system_roles
from authorization.validators import RegistryValidationError


def write_module(directory: Path, filename: str, module: dict) -> None:
    (directory / filename).write_text(json.dumps(module), encoding="utf-8")


def permission_module(
    module: str,
    permissions: list[dict] | None = None,
) -> dict:
    return {
        "module": module,
        "label": module.title(),
        "permissions": permissions
        or [
            {
                "code": f"{module}.view",
                "name": f"View {module.title()}",
                "scopes": ["all"],
            }
        ],
    }


class PermissionRegistryTests(unittest.TestCase):
    def test_application_registry_is_process_cached(self):
        self.assertIs(get_permission_registry(), get_permission_registry())

    def test_discovers_all_json_files(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            write_module(directory, "alpha.json", permission_module("alpha"))
            write_module(directory, "beta.json", permission_module("beta"))

            registry = load_permission_registry(directory)

        self.assertEqual([module.module for module in registry.modules], ["alpha", "beta"])
        self.assertEqual(set(registry.permissions), {"alpha.view", "beta.view"})

    def test_rejects_filename_module_mismatch(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            write_module(directory, "wrong.json", permission_module("students"))

            with self.assertRaisesRegex(
                RegistryValidationError,
                "does not match module",
            ):
                load_permission_registry(directory)

    def test_rejects_duplicate_permission_codes_across_modules(self):
        duplicate_permission = {
            "code": "shared.view",
            "name": "View Shared",
            "scopes": ["all"],
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            write_module(
                directory,
                "alpha.json",
                permission_module("alpha", [duplicate_permission]),
            )
            write_module(
                directory,
                "beta.json",
                permission_module("beta", [duplicate_permission]),
            )

            with self.assertRaisesRegex(
                RegistryValidationError,
                "Duplicate permission code",
            ):
                load_permission_registry(directory)

    def test_rejects_unknown_dependencies(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            write_module(
                directory,
                "alpha.json",
                permission_module(
                    "alpha",
                    [
                        {
                            "code": "alpha.manage",
                            "name": "Manage Alpha",
                            "scopes": ["all"],
                            "requires": ["alpha.view"],
                        }
                    ],
                ),
            )

            with self.assertRaisesRegex(
                RegistryValidationError,
                "Unknown dependencies",
            ):
                load_permission_registry(directory)

    def test_rejects_circular_dependencies(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            write_module(
                directory,
                "alpha.json",
                permission_module(
                    "alpha",
                    [
                        {
                            "code": "alpha.view",
                            "name": "View Alpha",
                            "scopes": ["all"],
                            "requires": ["alpha.manage"],
                        },
                        {
                            "code": "alpha.manage",
                            "name": "Manage Alpha",
                            "scopes": ["all"],
                            "requires": ["alpha.view"],
                        },
                    ],
                ),
            )

            with self.assertRaisesRegex(
                RegistryValidationError,
                "Circular permission dependency",
            ):
                load_permission_registry(directory)

    def test_rejects_invalid_and_empty_scopes(self):
        for scopes in ([], ["department"]):
            with self.subTest(scopes=scopes):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    directory = Path(temporary_directory)
                    write_module(
                        directory,
                        "alpha.json",
                        permission_module(
                            "alpha",
                            [
                                {
                                    "code": "alpha.view",
                                    "name": "View Alpha",
                                    "scopes": scopes,
                                }
                            ],
                        ),
                    )
                    with self.assertRaises(RegistryValidationError):
                        load_permission_registry(directory)


class SystemRoleManifestTests(unittest.TestCase):
    def test_defines_only_the_approved_system_roles(self):
        roles = get_system_roles()

        self.assertEqual(
            {role.key for role in roles},
            {
                "admin",
                "registrar",
                "teacher",
                "accountant",
                "staff",
                "student",
                "parent",
                "viewer",
            },
        )

    def test_admin_explicitly_grants_every_tenant_permission(self):
        registry = get_permission_registry()
        admin = next(role for role in get_system_roles() if role.key == "admin")

        self.assertEqual(
            {grant.permission for grant in admin.grants},
            set(registry.permissions),
        )

    def test_generated_constants_are_importable_and_typed_by_namespace(self):
        source = render_permission_constants(
            get_permission_registry(),
            root_class="Permissions",
        )
        namespace: dict = {}
        exec(source, namespace)

        permissions = namespace["Permissions"]
        self.assertEqual(permissions.Students.VIEW, "students.view")
        self.assertEqual(permissions.Grading.ENTER, "grades.enter")
        self.assertEqual(
            permissions.Finance.Transactions.APPROVE,
            "finance.transactions.approve",
        )

    def test_generator_rejects_normalized_constant_collisions(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            write_module(
                directory,
                "alpha.json",
                permission_module(
                    "alpha",
                    [
                        {"code": "alpha.foo_bar", "name": "One"},
                        {"code": "alpha.foo__bar", "name": "Two"},
                    ],
                ),
            )
            registry = load_permission_registry(directory)

            with self.assertRaisesRegex(ValueError, "constant name collision"):
                render_permission_constants(registry, root_class="Permissions")


if __name__ == "__main__":
    unittest.main()
