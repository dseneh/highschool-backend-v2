"""Authorization constants shared across the registry, runtime, and services."""

from __future__ import annotations

# Roles whose holders bypass the permission map entirely. They are seeded for
# platform superusers only and are never assignable through the RBAC APIs.
SUPERADMIN_ROLE_KEYS = frozenset({"superadmin", "super_admin"})
PLATFORM_SUPERADMIN_ROLE_KEY = "superadmin"
