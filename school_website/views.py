from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from authorization.drf import RBACPermission
from core.services.features import WEBSITE_FEATURE_KEY, feature_access
from school_website.models import (
    WebsiteMedia,
    WebsiteNavigationItem,
    WebsitePage,
    WebsiteSection,
    WebsiteSettings,
)
from school_website.serializers import (
    WebsiteMediaSerializer,
    WebsiteNavigationItemSerializer,
    WebsitePageSerializer,
    WebsiteSectionSerializer,
    WebsiteSettingsSerializer,
)
from school_website.services import (
    ensure_default_website,
    public_website_fallback,
    publish_website,
    published_website_snapshot,
)


class PublicWebsiteView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "website_public"

    def get(self, request):
        access = feature_access(request.tenant, WEBSITE_FEATURE_KEY)
        if not access.enabled:
            return Response(
                public_website_fallback(tenant=request.tenant, enabled=False)
            )
        settings = WebsiteSettings.objects.select_related("published_revision").first()
        if not settings or not settings.published_revision:
            return Response(
                public_website_fallback(tenant=request.tenant, enabled=True)
            )
        return Response(
            published_website_snapshot(
                tenant=request.tenant,
                snapshot=settings.published_revision.snapshot,
            )
        )


class WebsiteFeatureRequiredMixin:
    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        access = feature_access(request.tenant, WEBSITE_FEATURE_KEY)
        if not access.enabled:
            raise PermissionDenied(
                {
                    "detail": "The School Website add-on is not enabled for this workspace.",
                    "error_code": access.reason.upper(),
                    "feature_key": WEBSITE_FEATURE_KEY,
                }
            )
        ensure_default_website(tenant=request.tenant, user=request.user)


class WebsiteSettingsViewSet(WebsiteFeatureRequiredMixin, viewsets.ViewSet):
    permission_classes = [RBACPermission]
    permission_map = {
        "retrieve": "website.view",
        "update": "website.manage",
        "partial_update": "website.manage",
        "publish": "website.publish",
    }

    def retrieve(self, request, pk=None):
        settings = ensure_default_website(tenant=request.tenant, user=request.user)
        return Response(WebsiteSettingsSerializer(settings).data)

    def _save(self, request, *, partial):
        instance = ensure_default_website(tenant=request.tenant, user=request.user)
        serializer = WebsiteSettingsSerializer(
            instance, data=request.data, partial=partial
        )
        serializer.is_valid(raise_exception=True)
        serializer.save(updated_by=request.user)
        return Response(serializer.data)

    def update(self, request, pk=None):
        return self._save(request, partial=False)

    def partial_update(self, request, pk=None):
        return self._save(request, partial=True)

    @action(detail=False, methods=["post"])
    def publish(self, request):
        revision = publish_website(
            user=request.user,
            tenant=request.tenant,
            note=request.data.get("note", ""),
        )
        return Response(
            {
                "id": revision.id,
                "revision_number": revision.revision_number,
                "created_at": revision.created_at,
            },
            status=status.HTTP_201_CREATED,
        )


class WebsiteOwnedModelViewSet(WebsiteFeatureRequiredMixin, viewsets.ModelViewSet):
    permission_classes = [RBACPermission]
    permission_map = {
        "list": "website.view",
        "retrieve": "website.view",
        "create": "website.manage",
        "update": "website.manage",
        "partial_update": "website.manage",
        "destroy": "website.manage",
    }

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user, updated_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)


class WebsitePageViewSet(WebsiteOwnedModelViewSet):
    queryset = WebsitePage.objects.prefetch_related("sections").all()
    serializer_class = WebsitePageSerializer


class WebsiteSectionViewSet(WebsiteOwnedModelViewSet):
    queryset = WebsiteSection.objects.select_related("page").all()
    serializer_class = WebsiteSectionSerializer


class WebsiteNavigationViewSet(WebsiteOwnedModelViewSet):
    queryset = WebsiteNavigationItem.objects.select_related("page", "parent").all()
    serializer_class = WebsiteNavigationItemSerializer


class WebsiteMediaViewSet(WebsiteOwnedModelViewSet):
    queryset = WebsiteMedia.objects.all()
    serializer_class = WebsiteMediaSerializer
    parser_classes = [MultiPartParser, FormParser]

    def perform_destroy(self, instance):
        instance.file.delete(save=False)
        instance.delete()
