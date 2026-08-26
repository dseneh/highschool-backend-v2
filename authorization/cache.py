from __future__ import annotations

import logging
from dataclasses import dataclass

import msgspec
from django.conf import settings
from django.core.cache import cache
from django.db import transaction


logger = logging.getLogger(__name__)

DEFAULT_MEMBERSHIP_TIMEOUT = 300
DEFAULT_ROLE_POINTER_TIMEOUT = 300
DEFAULT_ROLE_PERMISSION_TIMEOUT = 86400


class CachedMembership(msgspec.Struct, frozen=True):
    exists: bool
    membership_id: str = ""
    membership_version: int = 0
    role_id: str = ""
    active: bool = False


class CachedRolePointer(msgspec.Struct, frozen=True):
    role_id: str
    permission_version: int
    active: bool
    system_key: str = ""


class CachedRolePermissions(msgspec.Struct, frozen=True):
    role_id: str
    permission_version: int
    permissions: dict[str, str]


@dataclass(frozen=True)
class CachedAuthorizationBundle:
    membership: CachedMembership
    role: CachedRolePointer | None = None
    role_permissions: CachedRolePermissions | None = None


REDIS_BUNDLE_SCRIPT = """
local membership_value = redis.call('GET', KEYS[1])
if not membership_value then
    return {false, false, false}
end

local ok_membership, membership = pcall(cjson.decode, membership_value)
if not ok_membership or not membership['exists'] or not membership['active'] then
    return {membership_value, false, false}
end

local role_id = membership['role_id']
local role_pointer_key = ARGV[1] .. 'role-current:' .. role_id
local role_value = redis.call('GET', role_pointer_key)
if not role_value then
    return {membership_value, false, false}
end

local ok_role, role = pcall(cjson.decode, role_value)
if not ok_role or not role['active'] then
    return {membership_value, role_value, false}
end

local permission_key = ARGV[1] .. 'role:' .. role_id .. ':v' .. role['permission_version']
local permission_value = redis.call('GET', permission_key)
return {membership_value, role_value, permission_value or false}
"""


class AuthorizationCache:
    @staticmethod
    def _prefix(schema_name: str) -> str:
        configured_prefix = getattr(
            settings,
            "AUTHORIZATION_CACHE_PREFIX",
            "ezyschool:rbac:v1",
        ).rstrip(":")
        return f"{configured_prefix}:{{{schema_name}}}:"

    @classmethod
    def membership_key(cls, schema_name: str, user_id) -> str:
        return f"{cls._prefix(schema_name)}membership:{user_id}"

    @classmethod
    def role_pointer_key(cls, schema_name: str, role_id) -> str:
        return f"{cls._prefix(schema_name)}role-current:{role_id}"

    @classmethod
    def role_permissions_key(
        cls,
        schema_name: str,
        role_id,
        permission_version: int,
    ) -> str:
        return (
            f"{cls._prefix(schema_name)}role:{role_id}:v{permission_version}"
        )

    @staticmethod
    def _redis_connection():
        if not getattr(settings, "USE_REDIS", False):
            return None
        try:
            from django_redis import get_redis_connection

            return get_redis_connection("default")
        except Exception:
            logger.exception("Unable to acquire Redis authorization connection")
            return None

    @classmethod
    def get_bundle(
        cls,
        schema_name: str,
        user_id,
    ) -> CachedAuthorizationBundle | None:
        redis_connection = cls._redis_connection()
        if getattr(settings, "USE_REDIS", False) and redis_connection is None:
            return None
        if redis_connection is not None:
            try:
                values = redis_connection.eval(
                    REDIS_BUNDLE_SCRIPT,
                    1,
                    cls.membership_key(schema_name, user_id),
                    cls._prefix(schema_name),
                )
                return cls._decode_bundle(*values)
            except Exception:
                logger.exception("Redis authorization bundle read failed")
                return None

        membership_value = cache.get(cls.membership_key(schema_name, user_id))
        if membership_value is None:
            return None
        try:
            membership = msgspec.json.decode(
                membership_value,
                type=CachedMembership,
            )
        except (msgspec.DecodeError, msgspec.ValidationError, TypeError):
            cls.invalidate_membership(schema_name, user_id)
            return None

        if not membership.exists or not membership.active:
            return CachedAuthorizationBundle(membership=membership)

        role_value = cache.get(
            cls.role_pointer_key(schema_name, membership.role_id)
        )
        if role_value is None:
            return None
        try:
            role = msgspec.json.decode(role_value, type=CachedRolePointer)
        except (msgspec.DecodeError, msgspec.ValidationError, TypeError):
            cls.invalidate_role(schema_name, membership.role_id)
            return None

        if not role.active:
            return CachedAuthorizationBundle(membership=membership, role=role)

        permission_value = cache.get(
            cls.role_permissions_key(
                schema_name,
                role.role_id,
                role.permission_version,
            )
        )
        if permission_value is None:
            return None
        try:
            role_permissions = msgspec.msgpack.decode(
                permission_value,
                type=CachedRolePermissions,
            )
        except (msgspec.DecodeError, msgspec.ValidationError, TypeError):
            cls.invalidate_role(schema_name, role.role_id)
            return None
        return cls._validate_bundle(membership, role, role_permissions)

    @classmethod
    def _decode_bundle(
        cls,
        membership_value,
        role_value,
        permission_value,
    ) -> CachedAuthorizationBundle | None:
        if membership_value is None:
            return None
        try:
            membership = msgspec.json.decode(
                membership_value,
                type=CachedMembership,
            )
            if not membership.exists or not membership.active:
                return CachedAuthorizationBundle(membership=membership)
            if role_value is None:
                return None
            role = msgspec.json.decode(role_value, type=CachedRolePointer)
            if not role.active:
                return CachedAuthorizationBundle(membership=membership, role=role)
            if permission_value is None:
                return None
            role_permissions = msgspec.msgpack.decode(
                permission_value,
                type=CachedRolePermissions,
            )
        except (msgspec.DecodeError, msgspec.ValidationError, TypeError):
            return None
        return cls._validate_bundle(membership, role, role_permissions)

    @staticmethod
    def _validate_bundle(
        membership: CachedMembership,
        role: CachedRolePointer,
        role_permissions: CachedRolePermissions,
    ) -> CachedAuthorizationBundle | None:
        if membership.role_id != role.role_id:
            return None
        if role_permissions.role_id != role.role_id:
            return None
        if role_permissions.permission_version != role.permission_version:
            return None
        return CachedAuthorizationBundle(membership, role, role_permissions)

    @classmethod
    def set_authorization(
        cls,
        schema_name: str,
        user_id,
        membership: CachedMembership,
        role: CachedRolePointer | None = None,
        role_permissions: CachedRolePermissions | None = None,
    ) -> None:
        entries = [
            (
                cls.membership_key(schema_name, user_id),
                msgspec.json.encode(membership),
                getattr(
                    settings,
                    "AUTHORIZATION_MEMBERSHIP_CACHE_TIMEOUT",
                    DEFAULT_MEMBERSHIP_TIMEOUT,
                ),
            )
        ]
        if role is not None:
            entries.append(
                (
                    cls.role_pointer_key(schema_name, role.role_id),
                    msgspec.json.encode(role),
                    getattr(
                        settings,
                        "AUTHORIZATION_ROLE_POINTER_CACHE_TIMEOUT",
                        DEFAULT_ROLE_POINTER_TIMEOUT,
                    ),
                )
            )
        if role_permissions is not None:
            entries.append(
                (
                    cls.role_permissions_key(
                        schema_name,
                        role_permissions.role_id,
                        role_permissions.permission_version,
                    ),
                    msgspec.msgpack.encode(role_permissions),
                    getattr(
                        settings,
                        "AUTHORIZATION_ROLE_PERMISSION_CACHE_TIMEOUT",
                        DEFAULT_ROLE_PERMISSION_TIMEOUT,
                    ),
                )
            )

        redis_connection = cls._redis_connection()
        if getattr(settings, "USE_REDIS", False) and redis_connection is None:
            return
        if redis_connection is not None:
            try:
                pipeline = redis_connection.pipeline(transaction=False)
                for key, value, timeout in entries:
                    pipeline.setex(key, timeout, value)
                pipeline.execute()
                return
            except Exception:
                logger.exception("Redis authorization bundle write failed")
                return

        for key, value, timeout in entries:
            cache.set(key, value, timeout)

    @classmethod
    def invalidate_membership(cls, schema_name: str, user_id) -> None:
        cls._delete(cls.membership_key(schema_name, user_id))

    @classmethod
    def invalidate_role(cls, schema_name: str, role_id) -> None:
        cls._delete(cls.role_pointer_key(schema_name, role_id))

    @classmethod
    def _delete(cls, key: str) -> None:
        redis_connection = cls._redis_connection()
        if getattr(settings, "USE_REDIS", False) and redis_connection is None:
            return
        if redis_connection is not None:
            for attempt in range(3):
                try:
                    redis_connection.delete(key)
                    return
                except Exception:
                    if attempt == 2:
                        logger.exception(
                            "Redis authorization cache invalidation failed after retries"
                        )
            return
        cache.delete(key)


def schedule_membership_invalidation(schema_name: str, user_id) -> None:
    schema = str(schema_name)
    user = str(user_id)
    transaction.on_commit(
        lambda: AuthorizationCache.invalidate_membership(schema, user)
    )


def schedule_role_invalidation(schema_name: str, role_id) -> None:
    schema = str(schema_name)
    role = str(role_id)
    transaction.on_commit(lambda: AuthorizationCache.invalidate_role(schema, role))
