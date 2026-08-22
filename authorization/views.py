from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Count, Prefetch
from django_tenants.utils import get_public_schema_name
from django.db import connection, transaction
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from authorization.drf import RBACPermission
from authorization.models import Role, RolePermission, TenantMembership
from authorization.registry import get_permission_registry
from authorization.serializers import (
    RoleCloneSerializer,
    RolePermissionReplacementSerializer,
    RoleSerializer,
    RoleUpdateSerializer,
    RoleWriteSerializer,
    UserRoleAssignmentSerializer,
)
from authorization.services import (
    assign_user_role,
    clone_role,
    create_role,
    delete_role,
    replace_role_permissions,
    update_role,
)
from common.audit_utils import extract_device_metadata, get_client_ip
from users.models import User


def _metadata(request):
    return {
        "ip_address": get_client_ip(request) or None,
        "user_agent": extract_device_metadata(request).get("user_agent", ""),
    }


def _raise_api_validation(exc):
    messages = getattr(exc, "messages", None)
    raise ValidationError(messages[0] if messages else str(exc))


def _require_permission_assignment(request, permissions) -> None:
    if permissions is not None and not request.can("roles.assign_permissions"):
        raise PermissionDenied("You cannot assign permissions to roles.")


class TenantAuthorizationMixin:
    def initial(self, request, *args, **kwargs):
        if connection.schema_name == get_public_schema_name():
            raise NotFound("Tenant authorization is not available in this workspace.")
        return super().initial(request, *args, **kwargs)


class PermissionCatalogView(TenantAuthorizationMixin, APIView):
    permission_classes = [RBACPermission]
    permission_map = {"get": "roles.view"}

    def get(self, request):
        registry = get_permission_registry()
        return Response(
            {
                "modules": [
                    {
                        "code": module.module,
                        "label": module.label,
                        "description": module.description,
                        "permissions": [
                            {
                                "code": permission.code,
                                "name": permission.name,
                                "description": permission.description,
                                "risk": permission.risk,
                                "assignable": permission.assignable,
                                "allowed_scopes": permission.scopes,
                                "requires": permission.requires,
                            }
                            for permission in module.permissions
                        ],
                    }
                    for module in registry.modules
                ]
            }
        )


class RoleViewSet(TenantAuthorizationMixin, viewsets.ModelViewSet):
    permission_classes = [RBACPermission]
    permission_map = {
        "list": "roles.view",
        "retrieve": "roles.view",
        "create": "roles.create",
        "update": "roles.update",
        "partial_update": "roles.update",
        "destroy": "roles.delete",
        "clone": "roles.clone",
        "replace_permissions": "roles.assign_permissions",
    }
    lookup_field = "pk"

    def get_queryset(self):
        return (
            Role.objects.annotate(user_count=Count("memberships"))
            .prefetch_related(
                Prefetch(
                    "permission_grants",
                    queryset=RolePermission.objects.order_by("permission_code"),
                )
            )
            .order_by("name")
        )

    def get_serializer_class(self):
        if self.action == "create":
            return RoleWriteSerializer
        if self.action in {"update", "partial_update"}:
            return RoleUpdateSerializer
        return RoleSerializer

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        serializer = RoleWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        _require_permission_assignment(
            request,
            serializer.validated_data.get("permissions"),
        )
        try:
            role = create_role(
                name=serializer.validated_data["name"],
                description=serializer.validated_data.get("description", ""),
                actor=request.user,
                metadata=_metadata(request),
            )
            if not serializer.validated_data.get("is_active", True):
                role = update_role(
                    role=role,
                    changes={"is_active": False},
                    actor=request.user,
                    metadata=_metadata(request),
                )
            if "permissions" in serializer.validated_data:
                role = replace_role_permissions(
                    role,
                    {
                        grant["code"]: grant["scope"]
                        for grant in serializer.validated_data["permissions"]
                    },
                    actor=request.user,
                    metadata=_metadata(request),
                )
        except DjangoValidationError as exc:
            _raise_api_validation(exc)
        return Response(RoleSerializer(role).data, status=status.HTTP_201_CREATED)

    @transaction.atomic
    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        serializer = RoleUpdateSerializer(data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        _require_permission_assignment(
            request,
            serializer.validated_data.get("permissions"),
        )
        try:
            changes = dict(serializer.validated_data)
            permissions = changes.pop("permissions", None)
            role = update_role(
                role=self.get_object(),
                changes=changes,
                actor=request.user,
                metadata=_metadata(request),
            )
            if permissions is not None:
                role = replace_role_permissions(
                    role,
                    {grant["code"]: grant["scope"] for grant in permissions},
                    actor=request.user,
                    metadata=_metadata(request),
                )
        except DjangoValidationError as exc:
            _raise_api_validation(exc)
        return Response(RoleSerializer(role).data)

    def destroy(self, request, *args, **kwargs):
        try:
            delete_role(
                role=self.get_object(),
                actor=request.user,
                metadata=_metadata(request),
            )
        except DjangoValidationError as exc:
            _raise_api_validation(exc)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"])
    @transaction.atomic
    def clone(self, request, pk=None):
        serializer = RoleCloneSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if not request.can("roles.assign_permissions"):
            raise PermissionDenied("You cannot assign permissions to roles.")
        try:
            role = clone_role(
                source=self.get_object(),
                name=serializer.validated_data["name"],
                description=serializer.validated_data.get("description"),
                actor=request.user,
                metadata=_metadata(request),
            )
            if "permissions" in serializer.validated_data:
                role = replace_role_permissions(
                    role,
                    {
                        grant["code"]: grant["scope"]
                        for grant in serializer.validated_data["permissions"]
                    },
                    actor=request.user,
                    metadata=_metadata(request),
                )
        except DjangoValidationError as exc:
            _raise_api_validation(exc)
        return Response(RoleSerializer(role).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["put"], url_path="permissions")
    def replace_permissions(self, request, pk=None):
        serializer = RolePermissionReplacementSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        grants = {
            grant["code"]: grant["scope"]
            for grant in serializer.validated_data["permissions"]
        }
        try:
            role = replace_role_permissions(
                self.get_object(),
                grants,
                actor=request.user,
                metadata=_metadata(request),
            )
        except DjangoValidationError as exc:
            _raise_api_validation(exc)
        role = self.get_queryset().get(pk=role.pk)
        return Response(RoleSerializer(role).data)


class UserRoleView(TenantAuthorizationMixin, APIView):
    permission_classes = [RBACPermission]
    permission_map = {"get": "roles.view", "put": "roles.assign_users"}

    def _user(self, id_number):
        user = User.objects.filter(id_number=id_number).first()
        if user is None:
            raise NotFound("User not found.")
        from tenant_users.permissions.models import UserTenantPermissions

        if not (
            TenantMembership.objects.filter(user=user).exists()
            or UserTenantPermissions.objects.filter(profile_id=user.pk).exists()
        ):
            raise NotFound("User not found in this tenant.")
        return user

    def get(self, request, id_number):
        user = self._user(id_number)
        membership = TenantMembership.objects.select_related("role").filter(user=user).first()
        return Response(
            {
                "user_id": str(user.pk),
                "id_number": user.id_number,
                "membership_id": str(membership.pk) if membership else None,
                "role": RoleSerializer(membership.role).data if membership else None,
                "is_active": membership.is_active if membership else False,
            }
        )

    def put(self, request, id_number):
        user = self._user(id_number)
        serializer = UserRoleAssignmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            role = Role.objects.get(pk=serializer.validated_data["role_id"])
        except Role.DoesNotExist as exc:
            raise ValidationError("Role not found.") from exc
        try:
            membership = assign_user_role(
                user=user,
                role=role,
                actor=request.user,
                metadata=_metadata(request),
            )
        except DjangoValidationError as exc:
            _raise_api_validation(exc)
        return Response(
            {
                "user_id": str(user.pk),
                "id_number": user.id_number,
                "membership_id": str(membership.pk),
                "role": RoleSerializer(role).data,
                "is_active": membership.is_active,
            }
        )
