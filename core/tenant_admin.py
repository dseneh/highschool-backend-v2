"""Tenant workspace admin user provisioning helpers."""

from __future__ import annotations

from django_tenants.utils import get_public_schema_name, schema_context

from common.status import Roles, UserAccountType
from common.utils import ID_ENTITY_EMPLOYEE, generate_entity_id_number
from core.models import Tenant
from users.models import User


def _get_user_by_email(email: str) -> User | None:
    with schema_context(get_public_schema_name()):
        return User.objects.filter(email__iexact=email.strip()).first()


def _get_user_by_username(username: str) -> User | None:
    with schema_context(get_public_schema_name()):
        return User.objects.filter(username__iexact=username.strip()).first()


def validate_tenant_admin_account(
    *,
    email: str,
    username: str,
) -> None:
    """Ensure admin credentials can be used for a new or existing tenant admin."""
    from rest_framework import serializers

    email = email.strip()
    username = username.strip()

    existing_by_email = _get_user_by_email(email)
    if existing_by_email:
        existing_username = (existing_by_email.username or "").strip()
        if existing_username and existing_username.lower() != username.lower():
            raise serializers.ValidationError(
                {
                    "admin_username": (
                        f"This email is already registered to username "
                        f"'{existing_by_email.username}'."
                    )
                }
            )
        return

    existing_by_username = _get_user_by_username(username)
    if existing_by_username:
        raise serializers.ValidationError(
            {"admin_username": f"Username '{username}' is already taken."}
        )


def resolve_or_create_tenant_admin_user(
    *,
    tenant: Tenant,
    first_name: str,
    last_name: str,
    email: str,
    username: str,
    password: str,
) -> tuple[User, bool]:
    """
    Create a tenant admin user or attach an existing global account by email.

    Returns ``(user, created)`` where ``created`` is False when an existing
    account was linked instead of provisioning a new login.
    """
    from rest_framework import serializers

    email = email.strip()
    username = username.strip()
    first_name = first_name.strip()
    last_name = last_name.strip()

    validate_tenant_admin_account(email=email, username=username)

    with schema_context(get_public_schema_name()):
        existing = _get_user_by_email(email)
        if existing:
            update_fields: list[str] = []

            if first_name and existing.first_name != first_name:
                existing.first_name = first_name
                update_fields.append("first_name")
            if last_name and existing.last_name != last_name:
                existing.last_name = last_name
                update_fields.append("last_name")
            if not existing.username:
                existing.username = username
                update_fields.append("username")

            if existing.role not in (Roles.SUPERADMIN, Roles.ADMIN):
                existing.role = Roles.ADMIN
                update_fields.append("role")
            if existing.account_type != UserAccountType.GLOBAL:
                existing.account_type = UserAccountType.GLOBAL
                update_fields.append("account_type")
            if not existing.is_active:
                existing.is_active = True
                update_fields.append("is_active")

            if password:
                existing.set_password(password)
                existing.is_default_password = False
                existing.last_password_updated = None
                update_fields.extend(
                    ["password", "is_default_password", "last_password_updated"]
                )

            if update_fields:
                existing.save(update_fields=update_fields)

            return existing, False

        id_number = generate_entity_id_number(User, ID_ENTITY_EMPLOYEE, tenant=tenant)

        user = User(
            username=username,
            email=email,
            first_name=first_name,
            last_name=last_name,
            id_number=id_number,
            account_type=UserAccountType.GLOBAL,
            role=Roles.ADMIN,
            is_active=True,
        )
        user.set_password(password)
        user.is_default_password = False
        user.last_password_updated = None
        user.save()
        return user, True


def create_tenant_admin_user(
    *,
    tenant: Tenant,
    first_name: str,
    last_name: str,
    email: str,
    username: str,
    password: str,
) -> User:
    """Create the tenant admin user in the public schema."""
    user, _created = resolve_or_create_tenant_admin_user(
        tenant=tenant,
        first_name=first_name,
        last_name=last_name,
        email=email,
        username=username,
        password=password,
    )
    return user
