"""Tenant-scoped branding asset endpoints."""

from io import BytesIO

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import connection
from django.utils import timezone
from django_tenants.utils import schema_context
from PIL import Image, ImageOps, UnidentifiedImageError
from rest_framework import status
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from common.permissions import IsSuperAdmin
from core.models import Tenant


AUTH_BACKGROUND_STORAGE_NAME = "branding/auth-bg.webp"
AUTH_BACKGROUND_MAX_BYTES = 5 * 1024 * 1024
AUTH_BACKGROUND_MAX_DIMENSION = 2560
AUTH_BACKGROUND_ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}


def _tenant_or_404(schema_name: str) -> Tenant:
    if connection.schema_name != "public":
        raise ValidationError(
            {"detail": "Tenant branding operations must be performed in the public schema."}
        )

    try:
        return Tenant.objects.get(schema_name=schema_name)
    except Tenant.DoesNotExist as exc:
        raise NotFound("Tenant not found.") from exc


def _versioned_url(url: str) -> str:
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}v={int(timezone.now().timestamp())}"


def _update_login_background(tenant: Tenant, background_url: str) -> None:
    theme_config = dict(tenant.theme_config or {})
    login_experience = dict(theme_config.get("login_experience") or {})
    login_experience["background_image"] = background_url
    theme_config["login_experience"] = login_experience
    tenant.theme_config = theme_config
    tenant.save(update_fields=["theme_config", "updated_at"])


class TenantAuthBackgroundView(APIView):
    """Upload, replace, or remove a tenant login background image.

    The physical object key is intentionally stable. Under the production
    TenantAwareS3Storage backend this becomes:

        tenants/<schema_name>/branding/auth-bg.webp

    The previous object is deleted before saving so django-storages cannot
    create suffixed duplicates when ``file_overwrite`` is disabled.
    """

    permission_classes = [IsAuthenticated, IsSuperAdmin]
    parser_classes = [MultiPartParser, FormParser]

    def put(self, request, schema_name: str):
        tenant = _tenant_or_404(schema_name)
        uploaded = request.FILES.get("background")
        if not uploaded:
            raise ValidationError({"background": "Background image file is required."})

        if uploaded.size > AUTH_BACKGROUND_MAX_BYTES:
            raise ValidationError({"background": "Background image must be 5 MB or smaller."})

        content_type = (getattr(uploaded, "content_type", "") or "").lower()
        if content_type not in AUTH_BACKGROUND_ALLOWED_TYPES:
            raise ValidationError(
                {"background": "Use a JPEG, PNG, or WebP image."}
            )

        try:
            uploaded.seek(0)
            image = Image.open(uploaded)
            image = ImageOps.exif_transpose(image)
            image.thumbnail(
                (AUTH_BACKGROUND_MAX_DIMENSION, AUTH_BACKGROUND_MAX_DIMENSION),
                Image.Resampling.LANCZOS,
            )

            if image.mode not in ("RGB", "RGBA"):
                image = image.convert("RGBA" if "transparency" in image.info else "RGB")

            output = BytesIO()
            image.save(output, format="WEBP", quality=85, method=6)
            output.seek(0)
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise ValidationError({"background": "The selected file is not a valid image."}) from exc

        # Switch into the target tenant schema while using storage so both
        # TenantFileSystemStorage in development and TenantAwareS3Storage/R2
        # in production resolve the same tenant-scoped path correctly.
        with schema_context(tenant.schema_name):
            if default_storage.exists(AUTH_BACKGROUND_STORAGE_NAME):
                default_storage.delete(AUTH_BACKGROUND_STORAGE_NAME)

            saved_name = default_storage.save(
                AUTH_BACKGROUND_STORAGE_NAME,
                ContentFile(output.read(), name="auth-bg.webp"),
            )
            background_url = _versioned_url(default_storage.url(saved_name))

        _update_login_background(tenant, background_url)

        return Response(
            {
                "background_image": background_url,
                "replaced": True,
            },
            status=status.HTTP_200_OK,
        )

    def delete(self, request, schema_name: str):
        tenant = _tenant_or_404(schema_name)

        with schema_context(tenant.schema_name):
            if default_storage.exists(AUTH_BACKGROUND_STORAGE_NAME):
                default_storage.delete(AUTH_BACKGROUND_STORAGE_NAME)

        _update_login_background(tenant, "")
        return Response({"background_image": ""}, status=status.HTTP_200_OK)
