from __future__ import annotations

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import connection, models, transaction
from django.db.models import F

from authorization.registry import get_permission_registry


class Scope(models.TextChoices):
    OWN = "own", "Own"
    ASSIGNED = "assigned", "Assigned"
    ALL = "all", "All"


class RoleQuerySet(models.QuerySet):
    protected_system_fields = {
        "name",
        "description",
        "system_key",
        "is_system_role",
        "is_default",
        "is_active",
        "permission_version",
    }

    def update(self, **kwargs):
        creates_system_role = bool(
            {"system_key", "is_system_role"}.intersection(kwargs)
        )
        changes_existing_system_role = self.protected_system_fields.intersection(
            kwargs
        ) and self.filter(is_system_role=True).exists()
        changes_authorization_state = bool(
            {"is_active", "permission_version"}.intersection(kwargs)
        )
        if (
            creates_system_role
            or changes_existing_system_role
            or changes_authorization_state
        ):
            raise ValidationError(
                "System roles are application-owned and cannot be modified."
            )
        return super().update(**kwargs)

    def bulk_create(self, objs, **kwargs):
        if any(role.is_system_role or role.system_key for role in objs):
            raise ValidationError(
                "System roles are application-owned and cannot be created in bulk."
            )
        return super().bulk_create(objs, **kwargs)

    def bulk_update(self, objs, fields, **kwargs):
        changes_system_role = self.protected_system_fields.intersection(fields) and any(
            role.is_system_role for role in objs
        )
        if changes_system_role or {"is_active", "permission_version"}.intersection(
            fields
        ):
            raise ValidationError(
                "System roles are application-owned and cannot be modified."
            )
        return super().bulk_update(objs, fields, **kwargs)

    def application_update(self, **kwargs):
        return super().update(**kwargs)

    def delete(self):
        if self.filter(is_system_role=True).exists():
            raise ValidationError(
                "System roles are application-owned and cannot be deleted."
            )
        return super().delete()


class Role(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, default="")
    system_key = models.CharField(
        max_length=50,
        unique=True,
        null=True,
        blank=True,
        editable=False,
    )
    is_system_role = models.BooleanField(default=False, editable=False)
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    permission_version = models.PositiveBigIntegerField(default=1, editable=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_authorization_roles",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = RoleQuerySet.as_manager()

    class Meta:
        db_table = "authorization_role"
        ordering = ("name",)
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(is_system_role=False, system_key__isnull=True)
                    | models.Q(is_system_role=True, system_key__isnull=False)
                ),
                name="authorization_role_system_key_consistent",
            ),
        ]

    def __str__(self) -> str:
        return self.name

    @classmethod
    def from_db(cls, db, field_names, values):
        instance = super().from_db(db, field_names, values)
        instance._loaded_values = dict(zip(field_names, values))
        return instance

    def clean(self) -> None:
        super().clean()
        if self.is_system_role != bool(self.system_key):
            raise ValidationError(
                "System roles must have a system key, and custom roles must not."
            )

    def save(self, *args, **kwargs):
        if self._state.adding and self.is_system_role and not getattr(
            self, "_application_owned", False
        ):
            raise ValidationError(
                "System roles can only be created by the application synchronizer."
            )
        if not self._state.adding:
            current = type(self).objects.filter(pk=self.pk).values(
                *RoleQuerySet.protected_system_fields
            ).first()
            changed = (
                {
                    field
                    for field in RoleQuerySet.protected_system_fields
                    if current and current[field] != getattr(self, field)
                }
                if current
                else set()
            )
            changes_system_identity = {"system_key", "is_system_role"}.intersection(
                changed
            )
            changes_version = "permission_version" in changed
            changes_system_role = bool(current and current["is_system_role"] and changed)
            if changes_system_identity or changes_version or changes_system_role:
                raise ValidationError(
                    "System roles are application-owned and cannot be modified."
                )
        self.full_clean()
        result = super().save(*args, **kwargs)
        from authorization.cache import schedule_role_invalidation

        schedule_role_invalidation(connection.schema_name, self.pk)
        return result

    def delete(self, *args, **kwargs):
        if self.is_system_role:
            raise ValidationError(
                "System roles are application-owned and cannot be deleted."
            )
        role_id = self.pk
        result = super().delete(*args, **kwargs)
        from authorization.cache import schedule_role_invalidation

        schedule_role_invalidation(connection.schema_name, role_id)
        return result


class RolePermission(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    role = models.ForeignKey(
        Role,
        on_delete=models.CASCADE,
        related_name="permission_grants",
    )
    permission_code = models.CharField(max_length=150)
    scope = models.CharField(max_length=20, choices=Scope.choices)
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="granted_role_permissions",
    )
    granted_at = models.DateTimeField(auto_now_add=True)

    class GrantQuerySet(models.QuerySet):
        def update(self, **kwargs):
            raise ValidationError(
                "Role grants must be changed through validated model or service operations."
            )

        def delete(self):
            raise ValidationError(
                "Role grants must be changed through validated model or service operations."
            )

        def bulk_create(self, objs, **kwargs):
            raise ValidationError(
                "Role grants must be changed through validated model or service operations."
            )

        def bulk_update(self, objs, fields, **kwargs):
            raise ValidationError(
                "Role grants must be changed through validated model or service operations."
            )

        def application_delete(self):
            return super().delete()

        def application_bulk_create(self, objs, **kwargs):
            return super().bulk_create(objs, **kwargs)

    objects = GrantQuerySet.as_manager()

    class Meta:
        db_table = "authorization_role_permission"
        ordering = ("permission_code",)
        constraints = [
            models.UniqueConstraint(
                fields=("role", "permission_code"),
                name="authorization_unique_role_permission",
            ),
        ]
        indexes = [
            models.Index(
                fields=("role", "permission_code"),
                name="authz_role_perm_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.role}: {self.permission_code} ({self.scope})"

    def clean(self) -> None:
        super().clean()
        permission = get_permission_registry().get(self.permission_code)
        if permission is None:
            raise ValidationError(
                {"permission_code": "Unknown system-defined permission code."}
            )
        if not permission.assignable:
            raise ValidationError(
                {"permission_code": "This permission cannot be assigned to roles."}
            )
        if self.scope not in permission.scopes:
            raise ValidationError(
                {
                    "scope": (
                        f"Scope {self.scope!r} is not allowed for "
                        f"{self.permission_code}."
                    )
                }
            )

        if self.role_id:
            role_grants = dict(
                type(self).objects.filter(role_id=self.role_id)
                .exclude(pk=self.pk)
                .values_list("permission_code", "scope")
            )
            role_grants[self.permission_code] = self.scope
            registry = get_permission_registry()
            for granted_code in role_grants:
                missing_dependencies = (
                    set(registry.require(granted_code).requires) - role_grants.keys()
                )
                if missing_dependencies:
                    raise ValidationError(
                        {
                            "permission_code": (
                                f"Grant change leaves {granted_code} without: "
                                f"{', '.join(sorted(missing_dependencies))}."
                            )
                        }
                    )

    def save(self, *args, **kwargs):
        previous = None
        if not self._state.adding:
            previous = type(self).objects.filter(pk=self.pk).values(
                "role_id", "permission_code"
            ).first()
        if previous and previous["role_id"] != self.role_id:
            raise ValidationError(
                "Role grants cannot be reassigned between roles."
            )
        if self.role_id and self.role.is_system_role:
            raise ValidationError(
                "System role permissions are application-owned and cannot be modified."
            )
        self.full_clean()
        previous_role_id = previous["role_id"] if previous else None
        with transaction.atomic():
            result = super().save(*args, **kwargs)
            role_ids = {self.role_id, previous_role_id} - {None}
            Role.objects.filter(pk__in=role_ids).application_update(
                permission_version=F("permission_version") + 1
            )
            from authorization.cache import schedule_role_invalidation

            for role_id in role_ids:
                schedule_role_invalidation(connection.schema_name, role_id)
        return result

    def delete(self, *args, **kwargs):
        if self.role_id and self.role.is_system_role:
            raise ValidationError(
                "System role permissions are application-owned and cannot be deleted."
            )
        dependent_codes = [
            code
            for code, permission in get_permission_registry().permissions.items()
            if self.permission_code in permission.requires
        ]
        if type(self).objects.filter(
            role_id=self.role_id,
            permission_code__in=dependent_codes,
        ).exists():
            raise ValidationError(
                "This permission is required by another grant on the role."
            )
        role_id = self.role_id
        with transaction.atomic():
            result = super().delete(*args, **kwargs)
            Role.objects.filter(pk=role_id).application_update(
                permission_version=F("permission_version") + 1
            )
            from authorization.cache import schedule_role_invalidation

            schedule_role_invalidation(connection.schema_name, role_id)
        return result


class TenantMembershipQuerySet(models.QuerySet):
    def update(self, **kwargs):
        if {
            "user",
            "user_id",
            "role",
            "role_id",
            "is_active",
            "membership_version",
        }.intersection(kwargs):
            raise ValidationError(
                "Membership authorization fields must be changed through save()."
            )
        return super().update(**kwargs)

    def bulk_create(self, objs, **kwargs):
        raise ValidationError("Memberships must be created through validated saves.")

    def bulk_update(self, objs, fields, **kwargs):
        raise ValidationError("Memberships must be changed through validated saves.")


class TenantMembership(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="authorization_membership",
    )
    role = models.ForeignKey(
        Role,
        on_delete=models.PROTECT,
        related_name="memberships",
    )
    is_active = models.BooleanField(default=True)
    membership_version = models.PositiveBigIntegerField(default=1, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = TenantMembershipQuerySet.as_manager()

    class Meta:
        db_table = "authorization_tenant_membership"
        ordering = ("user_id",)
        indexes = [
            models.Index(
                fields=("user", "is_active"),
                name="authz_member_active_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.user} - {self.role}"

    def clean(self) -> None:
        super().clean()
        if self.is_active and self.role_id and not self.role.is_active:
            raise ValidationError(
                {"role": "An active membership requires an active role."}
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        authorization_changed = False
        if not self._state.adding:
            previous = type(self).objects.filter(pk=self.pk).values(
                "user_id", "role_id", "is_active", "membership_version"
            ).first()
            if previous and previous["user_id"] != self.user_id:
                raise ValidationError("Membership ownership cannot be changed.")
            if (
                previous
                and previous["membership_version"] != self.membership_version
            ):
                raise ValidationError(
                    "Membership version is managed by authorization changes."
                )
            if previous and (
                previous["role_id"] != self.role_id
                or previous["is_active"] != self.is_active
            ):
                authorization_changed = True
                self.membership_version = F("membership_version") + 1
                if kwargs.get("update_fields") is not None:
                    kwargs["update_fields"] = set(kwargs["update_fields"]) | {
                        "membership_version"
                    }
        result = super().save(*args, **kwargs)
        if authorization_changed:
            self.refresh_from_db(fields=("membership_version",))
        from authorization.cache import schedule_membership_invalidation

        schedule_membership_invalidation(connection.schema_name, self.user_id)
        return result

    def delete(self, *args, **kwargs):
        user_id = self.user_id
        result = super().delete(*args, **kwargs)
        from authorization.cache import schedule_membership_invalidation

        schedule_membership_invalidation(connection.schema_name, user_id)
        return result


class AuthorizationAuditLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="authorization_audit_events",
    )
    action = models.CharField(max_length=100)
    target_type = models.CharField(max_length=100)
    target_id = models.CharField(max_length=100, blank=True, default="")
    before = models.JSONField(null=True, blank=True)
    after = models.JSONField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True, default="")
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "authorization_audit_log"
        ordering = ("-timestamp",)
        indexes = [
            models.Index(
                fields=("action", "timestamp"),
                name="authz_audit_action_idx",
            ),
            models.Index(
                fields=("target_type", "target_id"),
                name="authz_audit_target_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.action}: {self.target_type} {self.target_id}".strip()
