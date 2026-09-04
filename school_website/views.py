from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from authorization.drf import RBACPermission
from school_website.models import WebsiteNavigationItem, WebsitePage, WebsiteSection, WebsiteSettings
from school_website.serializers import WebsiteNavigationItemSerializer, WebsitePageSerializer, WebsiteSectionSerializer, WebsiteSettingsSerializer
from school_website.services import publish_website


class PublicWebsiteView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "website_public"

    def get(self, request):
        settings = WebsiteSettings.objects.select_related("published_revision").first()
        if not settings or not settings.published_revision:
            return Response({"detail": "This school website is not published."}, status=404)
        return Response(settings.published_revision.snapshot)


class WebsiteSettingsViewSet(viewsets.ViewSet):
    permission_classes = [RBACPermission]
    permission_map = {"retrieve": "website.view", "update": "website.manage", "partial_update": "website.manage", "publish": "website.publish"}

    def retrieve(self, request, pk=None):
        return Response(WebsiteSettingsSerializer(WebsiteSettings.get_solo()).data)

    def _save(self, request, *, partial):
        instance = WebsiteSettings.get_solo()
        serializer = WebsiteSettingsSerializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        serializer.save(updated_by=request.user)
        return Response(serializer.data)

    def update(self, request, pk=None):
        return self._save(request, partial=False)

    def partial_update(self, request, pk=None):
        return self._save(request, partial=True)

    @action(detail=False, methods=["post"])
    def publish(self, request):
        revision = publish_website(user=request.user, note=request.data.get("note", ""))
        return Response({"id": revision.id, "revision_number": revision.revision_number, "created_at": revision.created_at}, status=status.HTTP_201_CREATED)


class WebsiteOwnedModelViewSet(viewsets.ModelViewSet):
    permission_classes = [RBACPermission]
    permission_map = {"list": "website.view", "retrieve": "website.view", "create": "website.manage", "update": "website.manage", "partial_update": "website.manage", "destroy": "website.manage"}

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
