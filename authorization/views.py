from common.update_utils import validate_partial_update

from common.viewsets import PartialUpdateModelViewSet

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Count, Prefetch
from django_tenants.utils import get_public_schema_name, schema_context
from django.db import connection, transaction
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from authorization.constants import SUPERADMIN_ROLE_KEYS
from authorization.drf import RBACPermission
from authorization.models import Role, RolePermission, TenantMembership, TenantRoleAssignment
from authorization.registry import get_permission_registry, get_platform_permission_registry
from authorization.serializers import (
    BulkUserRoleAssignmentSerializer,
    RoleCloneSerializer,
    RolePermissionReplacementSerializer,
    RoleSerializer,
    RoleUpdateSerializer,
    RoleWriteSerializer,
    UserRoleAssignmentSerializer,
)
from authorization.services import (
    assign_user_shared_role,
    assign_user_role,
    clone_role,
    create_role,
    delete_role,
    get_applicable_shared_role,
    get_unified_role_payloads,
    replace_role_permissions,
    serialize_shared_role,
    update_role,
)
from common.audit_utils import extract_device_metadata, get_client_ip
from users.tenant_access import is_global_superadmin
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


def _require_public_role_admin(request) -> None:
    if not is_global_superadmin(getattr(request, "user", None)):
        raise PermissionDenied("You cannot assign public roles.")


class TenantAuthorizationMixin:
    def initial(self, request, *args, **kwargs):
        if connection.schema_name == get_public_schema_name():
            raise NotFound("Tenant authorization is not available in this workspace.")
        return super().initial(request, *args, **kwargs)


class PermissionCatalogView(TenantAuthorizationMixin, APIView):
    permission_classes = [RBACPermission]
    permission_map = {"get": "roles.view"}

    def initial(self, request, *args, **kwargs):
        if connection.schema_name == get_public_schema_name() and request.method == "GET":
            return APIView.initial(self, request, *args, **kwargs)
        return super().initial(request, *args, **kwargs)

    def get_permissions(self):
        if connection.schema_name == get_public_schema_name() and self.request.method == "GET":
            return [IsAuthenticated()]
        return super().get_permissions()

    def get(self, request):
        registry = (
            get_platform_permission_registry()
            if connection.schema_name == get_public_schema_name()
            else get_permission_registry()
        )
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


class RoleViewSet(TenantAuthorizationMixin, PartialUpdateModelViewSet):
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
        "users": "roles.view",
    }
    lookup_field = "pk"

    def initial(self, request, *args, **kwargs):
        if connection.schema_name == get_public_schema_name() and request.method == "GET":
            return viewsets.ModelViewSet.initial(self, request, *args, **kwargs)
        return super().initial(request, *args, **kwargs)

    def get_permissions(self):
        if connection.schema_name == get_public_schema_name() and self.request.method == "GET":
            return [IsAuthenticated()]
        return super().get_permissions()

    def get_queryset(self):
        if connection.schema_name == get_public_schema_name():
            return Role.objects.none()
        queryset = (
            Role.objects.annotate(user_count=Count("assignments"))
            .prefetch_related(
                Prefetch(
                    "permission_grants",
                    queryset=RolePermission.objects.order_by("permission_code"),
                )
            )
            .order_by("name")
        )
        # Keep the reserved superadmin role out of role-management surfaces so
        # it is never offered for assignment or editing.
        return queryset.exclude(system_key__in=SUPERADMIN_ROLE_KEYS)

    def list(self, request, *args, **kwargs):
        roles = get_unified_role_payloads(schema_name=connection.schema_name)
        return Response({
            "count": len(roles),
            "next": None,
            "previous": None,
            "results": roles,
        })

    @staticmethod
    def _shared_role_payload(role):
        return serialize_shared_role(role)

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
        role = self.get_object()
        serializer = validate_partial_update(RoleUpdateSerializer, role, request.data)
        _require_permission_assignment(
            request,
            serializer.validated_data.get("permissions"),
        )
        try:
            changes = dict(serializer.validated_data)
            permissions = changes.pop("permissions", None)
            role = update_role(
                role=role,
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

    @action(detail=True, methods=["get"], url_path="users")
    def users(self, request, pk=None):
        if connection.schema_name == get_public_schema_name():
            from core.models import SharedRole, SharedRoleAssignment

            try:
                role = SharedRole.objects.get(
                    pk=pk,
                    is_active=True,
                    scope__in=["PUBLIC", "GLOBAL"],
                )
            except SharedRole.DoesNotExist as exc:
                raise NotFound("Role not found.") from exc
            assignments = SharedRoleAssignment.objects.filter(
                role=role,
                is_active=True,
            ).select_related("user")
            return Response(
                {
                    "count": assignments.count(),
                    "results": [
                        {
                            "id": str(assignment.user.pk),
                            "id_number": assignment.user.id_number,
                            "first_name": assignment.user.first_name,
                            "last_name": assignment.user.last_name,
                            "email": assignment.user.email,
                            "account_type": assignment.user.account_type,
                            "is_active": assignment.user.is_active,
                        }
                        for assignment in assignments
                    ],
                }
            )

        try:
            shared_role = get_applicable_shared_role(pk)
        except DjangoValidationError:
            shared_role = None
        if shared_role is not None:
            memberships = TenantMembership.objects.filter(
                role_assignments__role_key=(f"system:{shared_role.system_key}" if shared_role.system_key else f"core.sharedrole:{shared_role.pk}"),
                role_assignments__is_active=True,
                is_active=True,
            ).select_related("user")
            return Response(
                {
                    "count": memberships.count(),
                    "results": [
                        {
                            "id": str(membership.user.pk),
                            "id_number": membership.user.id_number,
                            "first_name": membership.user.first_name,
                            "last_name": membership.user.last_name,
                            "email": membership.user.email,
                            "account_type": membership.user.account_type,
                            "is_active": membership.user.is_active,
                        }
                        for membership in memberships
                    ],
                }
            )

        role = self.get_object()
        memberships = TenantMembership.objects.filter(role_assignments__role=role, role_assignments__is_active=True).select_related("user")
        return Response(
            {
                "count": memberships.count(),
                "results": [
                    {
                        "id": str(membership.user.pk),
                        "id_number": membership.user.id_number,
                        "first_name": membership.user.first_name,
                        "last_name": membership.user.last_name,
                        "email": membership.user.email,
                        "account_type": membership.user.account_type,
                        "is_active": membership.is_active,
                    }
                    for membership in memberships
                ],
            }
        )


class UserRoleView(TenantAuthorizationMixin, APIView):
    permission_classes = [RBACPermission]
    permission_map = {"get": "roles.view", "put": "roles.assign_users"}

    def initial(self, request, *args, **kwargs):
        if connection.schema_name == get_public_schema_name() and request.method in {"GET", "PUT", "POST"}:
            return APIView.initial(self, request, *args, **kwargs)
        return super().initial(request, *args, **kwargs)

    def get_permissions(self):
        if connection.schema_name == get_public_schema_name() and self.request.method in {"GET", "PUT", "POST"}:
            return [IsAuthenticated()]
        if self.request.method == "GET" and str(self.kwargs.get("id_number")) == str(getattr(self.request.user, "id_number", "")):
            return [IsAuthenticated()]
        return super().get_permissions()

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

    def _public_user(self, id_number):
        user = User.objects.filter(id_number=id_number).first()
        if user is None:
            raise NotFound("User not found.")
        return user

    def _public_role(self, role_id):
        from core.models import SharedRole

        try:
            return SharedRole.objects.get(
                pk=role_id,
                is_active=True,
                scope__in=["PUBLIC", "GLOBAL"],
            )
        except SharedRole.DoesNotExist as exc:
            raise ValidationError("Role not found.") from exc

    def _public_assignment_payload(self, user, assignment):
        return {
            "user_id": str(user.pk),
            "id_number": user.id_number,
            "membership_id": str(assignment.pk) if assignment else None,
            "role": RoleViewSet._shared_role_payload(assignment.role) if assignment else None,
            "is_active": assignment.is_active if assignment else False,
        }

    def get(self, request, id_number):
        if connection.schema_name == get_public_schema_name():
            from core.models import SharedRoleAssignment

            user = self._public_user(id_number)
            assignment = SharedRoleAssignment.objects.select_related("role").filter(
                user=user,
                is_active=True,
            ).first()
            return Response(self._public_assignment_payload(user, assignment))

        from authorization.multiple_roles import user_assignments_payload
        user = self._user(id_number)
        selection = getattr(request.user, "_active_role_selection", None) if user.pk == request.user.pk else None
        return Response(user_assignments_payload(user, selection=selection))

    def put(self, request, id_number):
        serializer = UserRoleAssignmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        if connection.schema_name == get_public_schema_name():
            from core.models import SharedRoleAssignment

            _require_public_role_admin(request)
            user = self._public_user(id_number)
            role = self._public_role(serializer.validated_data["role_id"])
            assignment, _ = SharedRoleAssignment.objects.update_or_create(
                user=user,
                defaults={"role": role, "is_active": True},
            )
            return Response(self._public_assignment_payload(user, assignment))

        user = self._user(id_number)
        try:
            role = Role.objects.get(pk=serializer.validated_data["role_id"])
        except Role.DoesNotExist as exc:
            try:
                role = get_applicable_shared_role(serializer.validated_data["role_id"])
            except DjangoValidationError as shared_exc:
                raise ValidationError("Role not found.") from shared_exc
            try:
                membership = assign_user_shared_role(
                    user=user,
                    role=role,
                    actor=request.user,
                    metadata=_metadata(request),
                )
            except DjangoValidationError as shared_exc:
                _raise_api_validation(shared_exc)
            return Response(
                {
                    "user_id": str(user.pk),
                    "id_number": user.id_number,
                    "membership_id": str(membership.pk),
                    "role": RoleViewSet._shared_role_payload(role),
                    "is_active": membership.is_active,
                }
            )
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


class BulkUserRoleAssignmentView(UserRoleView):
    permission_map = {"post": "roles.assign_users"}

    @transaction.atomic
    def post(self, request):
        serializer = BulkUserRoleAssignmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        if connection.schema_name == get_public_schema_name():
            from core.models import SharedRoleAssignment

            _require_public_role_admin(request)
            role = self._public_role(serializer.validated_data["role_id"])
            assignments = []
            for id_number in serializer.validated_data["id_numbers"]:
                user = self._public_user(id_number)
                assignment, _ = SharedRoleAssignment.objects.update_or_create(
                    user=user,
                    defaults={"role": role, "is_active": True},
                )
                assignments.append(
                    {
                        "user_id": str(user.pk),
                        "id_number": user.id_number,
                        "membership_id": str(assignment.pk),
                    }
                )
            return Response({"role": RoleViewSet._shared_role_payload(role), "assignments": assignments})

        try:
            role = Role.objects.get(pk=serializer.validated_data["role_id"])
        except Role.DoesNotExist as exc:
            try:
                role = get_applicable_shared_role(serializer.validated_data["role_id"])
            except DjangoValidationError as shared_exc:
                raise ValidationError("Role not found.") from shared_exc

            users = [self._user(id_number) for id_number in serializer.validated_data["id_numbers"]]
            assignments = []
            try:
                for user in users:
                    membership = assign_user_shared_role(
                        user=user,
                        role=role,
                        actor=request.user,
                        metadata=_metadata(request),
                    )
                    assignments.append(
                        {
                            "user_id": str(user.pk),
                            "id_number": user.id_number,
                            "membership_id": str(membership.pk),
                        }
                    )
            except DjangoValidationError as shared_exc:
                _raise_api_validation(shared_exc)
            return Response({"role": RoleViewSet._shared_role_payload(role), "assignments": assignments})

        users = [self._user(id_number) for id_number in serializer.validated_data["id_numbers"]]
        assignments = []
        try:
            for user in users:
                membership = assign_user_role(
                    user=user,
                    role=role,
                    actor=request.user,
                    metadata=_metadata(request),
                )
                assignments.append(
                    {
                        "user_id": str(user.pk),
                        "id_number": user.id_number,
                        "membership_id": str(membership.pk),
                    }
                )
        except DjangoValidationError as exc:
            _raise_api_validation(exc)
        return Response({"role": RoleSerializer(role).data, "assignments": assignments})


class UserRoleRevokeView(UserRoleView):
    permission_map = {"delete": "roles.assign_users"}

    def delete(self, request, id_number, assignment_id):
        from authorization.multiple_roles import revoke_role, user_assignments_payload
        user = self._user(id_number)
        try:
            revoke_role(user=user, assignment_id=assignment_id, actor=request.user, metadata=_metadata(request))
        except DjangoValidationError as exc:
            _raise_api_validation(exc)
        return Response(user_assignments_payload(user))


class MyRolesView(TenantAuthorizationMixin, APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from authorization.multiple_roles import user_assignments_payload
        payload = user_assignments_payload(request.user)
        payload["assignments"] = [item for item in payload["assignments"]
                                  if item["role"].get("system_key") not in SUPERADMIN_ROLE_KEYS]
        payload["can_use_platform_context"] = bool(request.user.is_platform_superuser)
        payload["platform_context_active"] = bool(request.user.is_platform_superuser and
            getattr(request.user, "_active_role_selection", None) in (None, "platform"))
        return Response(payload)

    def post(self, request):
        from authorization.multiple_roles import selected_assignment, user_assignments_payload
        selection = str(request.data.get("assignment_id") or "")
        if selection == "platform":
            if not request.user.is_platform_superuser:
                raise PermissionDenied("Platform access is not assigned to this account.")
        elif not selected_assignment(request.user, selection) or not selection:
            raise PermissionDenied("This role assignment is not active in this school.")
        from authorization.models import AuthorizationAuditLog
        AuthorizationAuditLog.objects.create(
            actor=request.user, action="role_context.selected", target_type="role_assignment",
            target_id=selection, after={"assignment_id": selection}, **_metadata(request),
        )
        payload = user_assignments_payload(request.user, selection=selection)
        payload["selected_assignment_id"] = selection
        return Response(payload)
