"""Tenant-scoped login branding endpoints."""

from io import BytesIO

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import connection
from django.utils import timezone
from django_tenants.utils import schema_context
from PIL import Image, ImageOps, UnidentifiedImageError
from rest_framework import status
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import Tenant


AUTH_BACKGROUND_STORAGE_NAME = "branding/auth-bg.webp"
AUTH_BACKGROUND_MAX_BYTES = 5 * 1024 * 1024
AUTH_BACKGROUND_MAX_DIMENSION = 2560
AUTH_BACKGROUND_MAX_PIXELS = 40_000_000
AUTH_BACKGROUND_ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}
LOGIN_LAYOUTS = {"classic", "split", "hero", "minimal"}


def _tenant_or_404(schema_name: str) -> Tenant:
    """Resolve the public Tenant row without losing the caller's tenant scope."""
    current_schema = connection.schema_name

    with schema_context("public"):
        try:
            tenant = Tenant.objects.get(schema_name=schema_name)
        except Tenant.DoesNotExist as exc:
            raise NotFound("Tenant not found.") from exc

    if current_schema != "public" and current_schema != tenant.schema_name:
        raise PermissionDenied("You cannot manage another workspace's login branding.")

    return tenant


def _require_branding_access(user, tenant: Tenant) -> None:
    """Allow platform superadmins and active tenant administrators only."""
    if getattr(user, "is_platform_superuser", False):
        return

    with schema_context(tenant.schema_name):
        from authorization.models import TenantMembership

        is_tenant_admin = TenantMembership.objects.filter(
            user=user,
            is_active=True,
            role__is_active=True,
            role__system_key="admin",
        ).exists()

    if not is_tenant_admin:
        raise PermissionDenied(
            "Only a tenant administrator can manage this workspace's login experience."
        )


def _absolute_media_url(request, url: str) -> str:
    """Return a browser-usable URL in both local storage and R2 environments."""
    if not url:
        return ""
    return request.build_absolute_uri(url)


def _versioned_url(url: str) -> str:
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}v={int(timezone.now().timestamp())}"


def _login_experience(tenant: Tenant) -> dict:
    """Always read login branding from the canonical public Tenant row."""
    with schema_context("public"):
        fresh_tenant = Tenant.objects.only("theme_config").get(pk=tenant.pk)
        theme_config = fresh_tenant.theme_config or {}

    raw = theme_config.get("login_experience") if isinstance(theme_config, dict) else None
    return dict(raw) if isinstance(raw, dict) else {}


def _save_login_experience(tenant: Tenant, login_experience: dict) -> None:
    """Persist login branding against the public Tenant table explicitly."""
    with schema_context("public"):
        fresh_tenant = Tenant.objects.get(pk=tenant.pk)
        theme_config = dict(fresh_tenant.theme_config or {})
        theme_config["login_experience"] = dict(login_experience)
        fresh_tenant.theme_config = theme_config
        fresh_tenant.save(update_fields=["theme_config", "updated_at"])

    tenant.theme_config = theme_config


def _update_login_background(tenant: Tenant, background_url: str) -> dict:
    login_experience = _login_experience(tenant)
    login_experience["background_image"] = background_url
    _save_login_experience(tenant, login_experience)
    return login_experience


class TenantLoginExperienceView(APIView):
    """Update tenant login presentation without exposing tenant CRUD."""

    permission_classes = [IsAuthenticated]
    parser_classes = [JSONParser]

    def put(self, request, schema_name: str):
        tenant = _tenant_or_404(schema_name)
        _require_branding_access(request.user, tenant)

        incoming = request.data.get("login_experience")
        if not isinstance(incoming, dict):
            raise ValidationError(
                {"login_experience": "A login experience configuration is required."}
            )

        current = _login_experience(tenant)
        layout = incoming.get("layout", current.get("layout", "classic"))
        if layout not in LOGIN_LAYOUTS:
            raise ValidationError({"layout": "Select a supported login layout."})

        heading = incoming.get("heading", current.get("heading", "Welcome back!"))
        subheading = incoming.get(
            "subheading",
            current.get("subheading", "Sign in to continue to your school workspace."),
        )
        if not isinstance(heading, str) or len(heading.strip()) > 80:
            raise ValidationError({"heading": "Heading must be 80 characters or fewer."})
        if not isinstance(subheading, str) or len(subheading.strip()) > 160:
            raise ValidationError({"subheading": "Subheading must be 160 characters or fewer."})

        background_image = current.get("background_image", "")
        if isinstance(background_image, str) and background_image.startswith("/"):
            background_image = _absolute_media_url(request, background_image)

        updated = {
            **current,
            "layout": layout,
            "heading": heading.strip(),
            "subheading": subheading.strip(),
            "background_image": background_image,
            "show_school_name": bool(
                incoming.get("show_school_name", current.get("show_school_name", True))
            ),
            "show_logo": bool(incoming.get("show_logo", current.get("show_logo", True))),
        }
        _save_login_experience(tenant, updated)
        return Response({"login_experience": updated}, status=status.HTTP_200_OK)


class TenantAuthBackgroundView(APIView):
    """Upload, replace, or remove a tenant login background image.

    The logical storage name is always ``branding/auth-bg.webp``. Under the
    production TenantAwareS3Storage backend that resolves to:

        tenants/<schema_name>/branding/auth-bg.webp

    The previous object is deleted before saving so django-storages cannot
    create suffixed duplicates when ``file_overwrite`` is disabled.
    """

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def put(self, request, schema_name: str):
        tenant = _tenant_or_404(schema_name)
        _require_branding_access(request.user, tenant)

        uploaded = request.FILES.get("background")
        if not uploaded:
            raise ValidationError({"background": "Background image file is required."})

        if uploaded.size > AUTH_BACKGROUND_MAX_BYTES:
            raise ValidationError({"background": "Background image must be 5 MB or smaller."})

        content_type = (getattr(uploaded, "content_type", "") or "").lower()
        if content_type not in AUTH_BACKGROUND_ALLOWED_TYPES:
            raise ValidationError({"background": "Use a JPEG, PNG, or WebP image."})

        try:
            uploaded.seek(0)
            image = Image.open(uploaded)
            width, height = image.size
            if width <= 0 or height <= 0 or width * height > AUTH_BACKGROUND_MAX_PIXELS:
                raise ValidationError(
                    {"background": "The selected image dimensions are too large."}
                )

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
        except ValidationError:
            raise
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise ValidationError({"background": "The selected file is not a valid image."}) from exc

        with schema_context(tenant.schema_name):
            if default_storage.exists(AUTH_BACKGROUND_STORAGE_NAME):
                default_storage.delete(AUTH_BACKGROUND_STORAGE_NAME)

            saved_name = default_storage.save(
                AUTH_BACKGROUND_STORAGE_NAME,
                ContentFile(output.read(), name="auth-bg.webp"),
            )
            storage_url = default_storage.url(saved_name)

        background_url = _versioned_url(_absolute_media_url(request, storage_url))
        login_experience = _update_login_background(tenant, background_url)
        return Response(
            {
                "background_image": background_url,
                "login_experience": login_experience,
                "replaced": True,
            },
            status=status.HTTP_200_OK,
        )

    def delete(self, request, schema_name: str):
        tenant = _tenant_or_404(schema_name)
        _require_branding_access(request.user, tenant)

        with schema_context(tenant.schema_name):
            if default_storage.exists(AUTH_BACKGROUND_STORAGE_NAME):
                default_storage.delete(AUTH_BACKGROUND_STORAGE_NAME)

        login_experience = _update_login_background(tenant, "")
        return Response(
            {"background_image": "", "login_experience": login_experience},
            status=status.HTTP_200_OK,
        )