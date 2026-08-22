from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import msgspec

from authorization.validators import (
    MODULE_PATTERN,
    PERMISSION_CODE_PATTERN,
    RISK_LEVELS,
    SCOPES,
    PermissionModuleSpec,
    PermissionSpec,
    RegistryValidationError,
    validate_dependency_graph,
    validate_unique_values,
)


BASE_DIR = Path(__file__).resolve().parent
TENANT_PERMISSION_DIR = BASE_DIR / "permissions"
PLATFORM_PERMISSION_DIR = BASE_DIR / "platform_permissions"


class PermissionRegistry(msgspec.Struct, frozen=True):
    modules: tuple[PermissionModuleSpec, ...]
    permissions: dict[str, PermissionSpec]

    def get(self, code: str) -> PermissionSpec | None:
        return self.permissions.get(code)

    def require(self, code: str) -> PermissionSpec:
        try:
            return self.permissions[code]
        except KeyError as exc:
            raise RegistryValidationError(f"Unknown permission: {code}") from exc


def load_permission_registry(directory: Path) -> PermissionRegistry:
    modules: list[PermissionModuleSpec] = []
    for path in sorted(directory.glob("*.json")):
        try:
            module = msgspec.json.decode(
                path.read_bytes(),
                type=PermissionModuleSpec,
                strict=True,
            )
        except (OSError, msgspec.DecodeError, msgspec.ValidationError) as exc:
            raise RegistryValidationError(
                f"Invalid permission file {path.name}: {exc}"
            ) from exc

        if path.stem != module.module:
            raise RegistryValidationError(
                f"Permission filename {path.name} does not match module "
                f"{module.module!r}"
            )
        modules.append(module)

    if not modules:
        raise RegistryValidationError(
            f"No permission files found in {directory}"
        )

    validate_unique_values(
        (module.module for module in modules),
        label="permission module",
    )

    permissions: dict[str, PermissionSpec] = {}
    for module in modules:
        if not MODULE_PATTERN.fullmatch(module.module):
            raise RegistryValidationError(
                f"Invalid permission module name: {module.module}"
            )
        if not module.permissions:
            raise RegistryValidationError(
                f"Permission module {module.module} has no permissions"
            )

        for permission in module.permissions:
            if permission.code in permissions:
                raise RegistryValidationError(
                    f"Duplicate permission code: {permission.code}"
                )
            if not PERMISSION_CODE_PATTERN.fullmatch(permission.code):
                raise RegistryValidationError(
                    f"Invalid permission code: {permission.code}"
                )
            if permission.risk not in RISK_LEVELS:
                raise RegistryValidationError(
                    f"Invalid risk level for {permission.code}: {permission.risk}"
                )
            if not permission.scopes:
                raise RegistryValidationError(
                    f"Permission {permission.code} must allow at least one scope"
                )
            invalid_scopes = set(permission.scopes) - SCOPES
            if invalid_scopes:
                raise RegistryValidationError(
                    f"Invalid scopes for {permission.code}: "
                    f"{', '.join(sorted(invalid_scopes))}"
                )
            if len(permission.scopes) != len(set(permission.scopes)):
                raise RegistryValidationError(
                    f"Duplicate scopes for permission {permission.code}"
                )
            if permission.code in permission.requires:
                raise RegistryValidationError(
                    f"Permission {permission.code} cannot require itself"
                )
            if len(permission.requires) != len(set(permission.requires)):
                raise RegistryValidationError(
                    f"Duplicate dependencies for permission {permission.code}"
                )
            permissions[permission.code] = permission

    for permission in permissions.values():
        unknown = set(permission.requires) - permissions.keys()
        if unknown:
            raise RegistryValidationError(
                f"Unknown dependencies for {permission.code}: "
                f"{', '.join(sorted(unknown))}"
            )

    validate_dependency_graph(permissions)
    return PermissionRegistry(tuple(modules), permissions)


@lru_cache(maxsize=1)
def get_permission_registry() -> PermissionRegistry:
    return load_permission_registry(TENANT_PERMISSION_DIR)


@lru_cache(maxsize=1)
def get_platform_permission_registry() -> PermissionRegistry:
    return load_permission_registry(PLATFORM_PERMISSION_DIR)


def clear_registry_caches() -> None:
    get_permission_registry.cache_clear()
    get_platform_permission_registry.cache_clear()
