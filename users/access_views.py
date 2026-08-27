"""Elevated endpoints for platform access and EzySchool employment management."""

from django.core.exceptions import PermissionDenied, ValidationError as DjangoValidationError
from django_tenants.utils import get_public_schema_name, schema_context
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from users.access_service import (
    disable_platform_access,
    enable_platform_access,
    hire_platform_employee,
    terminate_platform_employee,
)
from users.serializers import UserSerializer


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
