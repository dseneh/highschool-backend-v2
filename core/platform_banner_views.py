"""Views for the cross-tenant :class:`PlatformBanner` feature.

Two surfaces:

* **Admin** (:class:`PlatformBannerViewSet`) — full CRUD for platform
  superadmins. Lives in the public schema; the schema is forced to
  ``public`` even when the request arrives with an ``X-Tenant`` header
  so superadmins can manage banners from any workspace.
* **Public** (:class:`MyPlatformBannersView`) — any authenticated user
  can fetch the banners that currently target them. Used by the
  frontend ``BannerHost`` alongside per-tenant banners.
"""

from __future__ import annotations

from django.db import connection
from django.utils import timezone
from django_tenants.utils import schema_context
from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from common.permissions import IsSuperAdmin
from core.models import PlatformBanner, PlatformBannerDismissal, Tenant
from core.platform_banner_serializers import (
    PlatformBannerPublicSerializer,
    PlatformBannerSerializer,
)


def _active_banners_for_user(user):
    """Return the queryset of platform banners that should currently be
    visible to ``user`` (active, in-window, targeting matches, not yet
    dismissed by the user). Must be called inside the public schema."""
    now = timezone.now()
    qs = PlatformBanner.objects.filter(active=True)
    qs = qs.filter(
        models_q_or_null("starts_at", now, less_or_equal=True)
    )
    qs = qs.filter(
        models_q_or_null("ends_at", now, greater_than=True)
    )

    # Role targeting — empty list = ALL roles.
    role = (getattr(user, "role", "") or "").lower() or None
    if role:
        from django.db.models import Q

        qs = qs.filter(Q(target_roles=[]) | Q(target_roles__contains=[role]))
    else:
        qs = qs.filter(target_roles=[])

    # Tenant targeting — empty list = ALL tenants. We attempt to determine
    # the user's current tenant context from the connection schema.
    schema = connection.schema_name
    if schema and schema != "public":
        from django.db.models import Q

        qs = qs.filter(
            Q(target_tenants=[]) | Q(target_tenants__contains=[schema])
        )
    else:
        # No tenant context — only show banners that target everyone.
        qs = qs.filter(target_tenants=[])

    # Exclude banners the user has already dismissed.
    dismissed = PlatformBannerDismissal.objects.filter(user=user).values_list(
        "banner_id", flat=True
    )
    qs = qs.exclude(id__in=list(dismissed))
    return qs.order_by("-created_at")


def models_q_or_null(field: str, value, *, less_or_equal=False, greater_than=False):
    """Build a Django ``Q`` matching null OR a comparison."""
    from django.db.models import Q

    if less_or_equal:
        return Q(**{f"{field}__isnull": True}) | Q(**{f"{field}__lte": value})
    if greater_than:
        return Q(**{f"{field}__isnull": True}) | Q(**{f"{field}__gt": value})
    raise ValueError("must pass one of less_or_equal=True / greater_than=True")


class PlatformBannerViewSet(viewsets.ModelViewSet):
    """Superadmin CRUD for platform banners.

    Always operates in the public schema. The list endpoint returns every
    banner so the admin portal can show drafts / expired ones in a table.
    """

    permission_classes = [IsSuperAdmin]
    serializer_class = PlatformBannerSerializer

    def get_queryset(self):
        # Force public schema for all admin reads/writes.
        with schema_context("public"):
            return PlatformBanner.objects.all().order_by("-created_at")

    def _in_public(self, fn, *args, **kwargs):
        with schema_context("public"):
            return fn(*args, **kwargs)

    def list(self, request, *args, **kwargs):
        return self._in_public(super().list, request, *args, **kwargs)

    def retrieve(self, request, *args, **kwargs):
        return self._in_public(super().retrieve, request, *args, **kwargs)

    def create(self, request, *args, **kwargs):
        with schema_context("public"):
            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            serializer.save(created_by=request.user)
            return Response(serializer.data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        return self.partial_update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        with schema_context("public"):
            instance = self.get_object()
            serializer = self.get_serializer(instance, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return Response(serializer.data)

    def destroy(self, request, *args, **kwargs):
        with schema_context("public"):
            instance = self.get_object()
            instance.active = False
            instance.save(update_fields=["active", "updated_at"])
            return Response(status=status.HTTP_204_NO_CONTENT)


class MyPlatformBannersView(APIView):
    """Active platform banners for the authenticated user.

    Reads from the public schema regardless of the current connection schema
    so users in any workspace can see banners that target everyone.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        with schema_context("public"):
            qs = _active_banners_for_user(request.user)
            data = PlatformBannerPublicSerializer(qs, many=True).data
        return Response({"banners": data})


class DismissPlatformBannerView(APIView):
    """Mark a platform banner as dismissed for the authenticated user."""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        with schema_context("public"):
            try:
                banner = PlatformBanner.objects.get(pk=pk, active=True)
            except PlatformBanner.DoesNotExist:
                return Response(status=status.HTTP_404_NOT_FOUND)
            if not banner.dismissible:
                return Response(
                    {"detail": "This banner is not dismissible."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            PlatformBannerDismissal.objects.get_or_create(
                banner=banner, user=request.user
            )
        return Response({"id": str(pk), "dismissed": True})


class PlatformBannerTargetingMetaView(APIView):
    """Helper endpoint for the admin compose form. Lists tenant slugs and
    available roles so the form can build select inputs."""

    permission_classes = [IsSuperAdmin]

    def get(self, request):
        with schema_context("public"):
            tenants = list(
                Tenant.objects.filter(active=True)
                .order_by("name")
                .values("schema_name", "name")
            )
        return Response(
            {
                "tenants": tenants,
                "roles": [
                    {"value": "admin", "label": "Admin"},
                    {"value": "teacher", "label": "Teacher"},
                    {"value": "student", "label": "Student"},
                    {"value": "parent", "label": "Parent"},
                    {"value": "registrar", "label": "Registrar"},
                ],
            }
        )
