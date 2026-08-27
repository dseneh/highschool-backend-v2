"""Elevated endpoints for platform identity, access, and employment management."""

import secrets

from django.core.exceptions import PermissionDenied, ValidationError as DjangoValidationError
from django.db import transaction
from django_tenants.utils import get_public_schema_name, schema_context
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from users.access_service import (
    disable_platform_access,
    enable_platform_access,
    hire_platform_employee,
    require_platform_access_manager,
    terminate_platform_employee,
)
from users.serializers import UserSerializer


class PlatformUserCreateSerializer(serializers.Serializer):
    email = serializers.EmailField(required=True)
    first_name = serializers.CharField(required=True, max_length=100)
    last_name = serializers.CharField(required=True, max_length=100)
    gender = serializers.ChoiceField(choices=["male", "female"], default="male")
    username = serializers.CharField(required=False, allow_blank=True, max_length=150)
    password = serializers.CharField(required=False, allow_blank=True, min_length=8, write_only=True)
    notify_user = serializers.BooleanField(required=False, default=True)
    role = serializers.CharField(required=True)


class PlatformAccessSerializer(serializers.Serializer):
    role = serializers.CharField(required=True)


class PlatformEmploymentSerializer(serializers.Serializer):
    employee_number = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    position = serializers.CharField(required=False, allow_blank=True, default="")
    department = serializers.CharField(required=False, allow_blank=True, default="")
    hire_date = serializers.DateField(required=False, allow_null=True)
    role = serializers.CharField(required=False, allow_blank=True, allow_null=True)


class PlatformEmploymentTerminationSerializer(serializers.Serializer):
    termination_date = serializers.DateField(required=True)
    revoke_access = serializers.BooleanField(required=False, default=False)


class PublicUserManagementAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def _target_user(self, id_number):
        from users.models import User

        with schema_context(get_public_schema_name()):
            try:
                return User.objects.get(id_number=id_number)
            except User.DoesNotExist:
                return None

    @staticmethod
    def _error(exc):
        if isinstance(exc, PermissionDenied):
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        if hasattr(exc, "message_dict"):
            return Response(exc.message_dict, status=status.HTTP_400_BAD_REQUEST)
        messages = getattr(exc, "messages", None)
        return Response(
            {"detail": messages[0] if messages else str(exc)},
            status=status.HTTP_400_BAD_REQUEST,
        )


class PlatformUserCreateView(PublicUserManagementAPIView):
    """Create a standalone platform identity with an explicit public role.

    Existing tenant users must use PlatformAccessView instead so their existing
    User identity and linked profiles are reused rather than duplicated.
    """

    @staticmethod
    def _new_id_number(User) -> str:
        while True:
            candidate = f"P{secrets.token_hex(3).upper()}"
            if not User.objects.filter(id_number=candidate).exists():
                return candidate

    @staticmethod
    def _unique_username(User, preferred: str, fallback: str) -> str:
        base = (preferred or fallback).strip()
        candidate = base
        suffix = 1
        while User.objects.filter(username=candidate).exists():
            candidate = f"{base}_{suffix}"
            suffix += 1
        return candidate

    def post(self, request):
        serializer = PlatformUserCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            require_platform_access_manager(request.user)
        except PermissionDenied as exc:
            return self._error(exc)

        from common.status import UserAccountScope, UserAccountType
        from users.models import User

        public_schema = get_public_schema_name()
        try:
            with schema_context(public_schema), transaction.atomic():
                email = str(data["email"]).strip().lower()
                if User.objects.filter(email__iexact=email).exists():
                    return Response(
                        {
                            "detail": (
                                "A user with this email already exists. Enable platform "
                                "access on the existing account instead of creating a duplicate."
                            )
                        },
                        status=status.HTTP_409_CONFLICT,
                    )

                id_number = self._new_id_number(User)
                username = self._unique_username(
                    User,
                    str(data.get("username") or ""),
                    id_number,
                )
                raw_password = str(data.get("password") or "") or id_number
                user = User(
                    email=email,
                    username=username,
                    id_number=id_number,
                    first_name=str(data["first_name"]).strip(),
                    last_name=str(data["last_name"]).strip(),
                    gender=data.get("gender") or "male",
                    account_type=UserAccountType.OTHER.value,
                    account_scope=UserAccountScope.PLATFORM.value,
                    is_active=True,
                    is_platform_superuser=False,
                    is_default_password=not bool(data.get("password")),
                )
                user.set_password(raw_password)
                user.save()

                enable_platform_access(
                    user=user,
                    role=data["role"],
                    actor=request.user,
                )

                if data.get("notify_user", True):
                    try:
                        from users.utils import send_welcome_email
                        send_welcome_email(user, raw_password)
                    except Exception:
                        # Email delivery is not part of the identity transaction.
                        pass

                user.refresh_from_db()
                return Response(
                    UserSerializer(user, context={"request": request}).data,
                    status=status.HTTP_201_CREATED,
                )
        except (DjangoValidationError, PermissionDenied) as exc:
            return self._error(exc)


class PlatformAccessView(PublicUserManagementAPIView):
    """Grant, change, or revoke a user's public/platform role."""

    def post(self, request, id_number):
        target = self._target_user(id_number)
        if target is None:
            return Response({"detail": "User not found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = PlatformAccessSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            enable_platform_access(
                user=target,
                role=serializer.validated_data["role"],
                actor=request.user,
            )
        except (PermissionDenied, DjangoValidationError) as exc:
            return self._error(exc)
        with schema_context(get_public_schema_name()):
            target.refresh_from_db()
            return Response(UserSerializer(target, context={"request": request}).data)

    def delete(self, request, id_number):
        target = self._target_user(id_number)
        if target is None:
            return Response({"detail": "User not found."}, status=status.HTTP_404_NOT_FOUND)
        try:
            disable_platform_access(user=target, actor=request.user)
        except (PermissionDenied, DjangoValidationError) as exc:
            return self._error(exc)
        with schema_context(get_public_schema_name()):
            target.refresh_from_db()
            return Response(UserSerializer(target, context={"request": request}).data)


class PlatformEmploymentView(PublicUserManagementAPIView):
    """Create/reactivate or terminate the user's EzySchool employment record."""

    def post(self, request, id_number):
        target = self._target_user(id_number)
        if target is None:
            return Response({"detail": "User not found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = PlatformEmploymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            hire_platform_employee(
                user=target,
                actor=request.user,
                employee_number=data.get("employee_number") or None,
                position=data.get("position", ""),
                department=data.get("department", ""),
                hire_date=data.get("hire_date"),
                platform_role=data.get("role") or None,
            )
        except (PermissionDenied, DjangoValidationError) as exc:
            return self._error(exc)
        with schema_context(get_public_schema_name()):
            target.refresh_from_db()
            return Response(UserSerializer(target, context={"request": request}).data)

    def delete(self, request, id_number):
        target = self._target_user(id_number)
        if target is None:
            return Response({"detail": "User not found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = PlatformEmploymentTerminationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            terminate_platform_employee(
                user=target,
                actor=request.user,
                termination_date=serializer.validated_data["termination_date"],
                revoke_access=serializer.validated_data["revoke_access"],
            )
        except (PermissionDenied, DjangoValidationError) as exc:
            return self._error(exc)
        with schema_context(get_public_schema_name()):
            target.refresh_from_db()
            return Response(UserSerializer(target, context={"request": request}).data)
