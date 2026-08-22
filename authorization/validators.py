from __future__ import annotations

import re
from collections.abc import Iterable

import msgspec


RiskLevel = str
Scope = str

RISK_LEVELS = frozenset({"low", "medium", "high", "critical"})
SCOPES = frozenset({"own", "assigned", "all"})
MODULE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
PERMISSION_CODE_PATTERN = re.compile(
    r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$"
)


class PermissionSpec(msgspec.Struct, frozen=True):
    code: str
    name: str
    description: str = ""
    risk: RiskLevel = "low"
    assignable: bool = True
    scopes: list[Scope] = msgspec.field(default_factory=lambda: ["all"])
    requires: list[str] = msgspec.field(default_factory=list)


class PermissionModuleSpec(msgspec.Struct, frozen=True):
    module: str
    label: str
    description: str = ""
    permissions: list[PermissionSpec] = msgspec.field(default_factory=list)


class SystemRoleGrantSpec(msgspec.Struct, frozen=True):
    permission: str
    scope: Scope


class SystemRoleSpec(msgspec.Struct, frozen=True):
    key: str
    name: str
    description: str = ""
    grants: list[SystemRoleGrantSpec] = msgspec.field(default_factory=list)


class RegistryValidationError(ValueError):
    pass


def validate_dependency_graph(
    permissions: dict[str, PermissionSpec],
) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(code: str, path: tuple[str, ...]) -> None:
        if code in visiting:
            cycle_start = path.index(code)
            cycle = (*path[cycle_start:], code)
            raise RegistryValidationError(
                f"Circular permission dependency: {' -> '.join(cycle)}"
            )
        if code in visited:
            return

        visiting.add(code)
        permission = permissions[code]
        for required_code in permission.requires:
            visit(required_code, (*path, code))
        visiting.remove(code)
        visited.add(code)

    for permission_code in permissions:
        visit(permission_code, ())


def validate_unique_values(values: Iterable[str], *, label: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise RegistryValidationError(f"Duplicate {label}: {value}")
        seen.add(value)
