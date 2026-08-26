from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import msgspec

from authorization.constants import SUPERADMIN_ROLE_KEYS
from authorization.registry import PermissionRegistry, get_permission_registry
from authorization.validators import (
    MODULE_PATTERN,
    SystemRoleSpec,
    RegistryValidationError,
    validate_unique_values,
)


SYSTEM_ROLE_DIR = Path(__file__).resolve().parent / "system_roles"


def load_system_roles(
    directory: Path = SYSTEM_ROLE_DIR,
    *,
    registry: PermissionRegistry | None = None,
) -> tuple[SystemRoleSpec, ...]:
    registry = registry or get_permission_registry()
    roles: list[SystemRoleSpec] = []

    for path in sorted(directory.glob("*.json")):
        try:
            role = msgspec.json.decode(
                path.read_bytes(),
                type=SystemRoleSpec,
                strict=True,
            )
        except (OSError, msgspec.DecodeError, msgspec.ValidationError) as exc:
            raise RegistryValidationError(
                f"Invalid system role file {path.name}: {exc}"
            ) from exc

        if path.stem != role.key:
            raise RegistryValidationError(
                f"System role filename {path.name} does not match key {role.key!r}"
            )
        roles.append(role)

    if not roles:
        raise RegistryValidationError(f"No system roles found in {directory}")

    validate_unique_values((role.key for role in roles), label="system role key")
    validate_unique_values((role.name.lower() for role in roles), label="system role name")

    for role in roles:
        if not MODULE_PATTERN.fullmatch(role.key):
            raise RegistryValidationError(f"Invalid system role key: {role.key}")
        # Superadmin bypasses the permission map, so grants would be meaningless.
        if role.key in SUPERADMIN_ROLE_KEYS:
            if role.grants:
                raise RegistryValidationError(
                    f"System role {role.key} is unrestricted and must not declare grants"
                )
            continue
        if not role.grants:
            raise RegistryValidationError(f"System role {role.key} has no grants")

        grants = {grant.permission: grant for grant in role.grants}
        if len(grants) != len(role.grants):
            raise RegistryValidationError(
                f"System role {role.key} contains duplicate permission grants"
            )

        for grant in role.grants:
            permission = registry.require(grant.permission)
            if not permission.assignable:
                raise RegistryValidationError(
                    f"Permission {grant.permission} is not assignable"
                )
            if grant.scope not in permission.scopes:
                raise RegistryValidationError(
                    f"Scope {grant.scope} is not allowed for {grant.permission}"
                )
            missing_dependencies = set(permission.requires) - grants.keys()
            if missing_dependencies:
                raise RegistryValidationError(
                    f"System role {role.key} grants {grant.permission} without "
                    f"required permissions: {', '.join(sorted(missing_dependencies))}"
                )

    return tuple(roles)


@lru_cache(maxsize=1)
def get_system_roles() -> tuple[SystemRoleSpec, ...]:
    return load_system_roles()


def get_system_role(key: str) -> SystemRoleSpec:
    try:
        return next(role for role in get_system_roles() if role.key == key)
    except StopIteration as exc:
        raise RegistryValidationError(f"Unknown system role: {key}") from exc
