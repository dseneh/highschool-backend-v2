from hashlib import sha1

from django.db.models import Count, Max, Q
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from common.status import Roles
from notifications.access_policies import NotificationAccessPolicy
from notifications.models import (
    Notification,
    NotificationCampaign,
    NotificationRule,
    TenantNotificationSettings,
    UserNotificationPreference,
)
from notifications.serializers import (
    AnnouncementSerializer,
    BannerNotificationSerializer,
    NotificationCampaignCreateSerializer,
    NotificationCampaignSerializer,
    NotificationMarkReadSerializer,
    NotificationRuleSerializer,
    NotificationSerializer,
    TenantNotificationSettingsSerializer,
    UserNotificationPreferenceSerializer,
)
from notifications.services.campaign_send import create_and_send_campaign
from notifications.services.teacher_scope import assert_teacher_can_target_audience


class NotificationPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


def _inbox_version(user):
    """Return a tuple ``(latest_updated_at, total, unread)`` representing
    the current state of a user's inbox. Used to compute an ETag so polling
    clients can short-circuit with ``304 Not Modified`` when nothing has
    changed.
    """
    qs = Notification.objects.filter(recipient=user, active=True)
    aggregates = qs.aggregate(latest=Max("updated_at"))
    latest = aggregates.get("latest")
    total = qs.count()
    unread = qs.filter(read_at__isnull=True).count()
    return latest, total, unread


def _build_etag(version_tuple, *extras):
    latest, total, unread = version_tuple
    parts = [
        latest.isoformat() if latest else "0",
        str(total),
        str(unread),
    ]
    parts.extend(str(x) for x in extras)
    return sha1("|".join(parts).encode("utf-8")).hexdigest()


def _maybe_304(request, etag):
    """If the client's ``If-None-Match`` matches ``etag``, return a 304
    response (no body). Otherwise return ``None``."""
    if_none_match = (request.headers.get("If-None-Match") or "").strip()
    if if_none_match and if_none_match.strip('"') == etag:
        response = Response(status=status.HTTP_304_NOT_MODIFIED)
        response["ETag"] = f'"{etag}"'
        response["Cache-Control"] = "private, max-age=0, must-revalidate"
        return response
    return None


def _attach_etag(response, etag):
    response["ETag"] = f'"{etag}"'
    response["Cache-Control"] = "private, max-age=0, must-revalidate"
    return response


class InboxViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [NotificationAccessPolicy]
    serializer_class = NotificationSerializer
    pagination_class = NotificationPagination

    def get_queryset(self):
        qs = (
            Notification.objects.filter(recipient=self.request.user, active=True)
            .select_related("campaign", "campaign__created_by")
            .order_by("-created_at")
        )
        if self.request.query_params.get("unread") in ("1", "true", "yes"):
            qs = qs.filter(read_at__isnull=True)
        category = self.request.query_params.get("category")
        if category:
            qs = qs.filter(campaign__category=category)
        return qs

    @action(detail=True, methods=["patch"], url_path="mark-read")
    def mark_read(self, request, pk=None):
        notification = self.get_object()
        serializer = NotificationMarkReadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if serializer.validated_data.get("read", True):
            notification.read_at = timezone.now()
        else:
            notification.read_at = None
        notification.updated_by = request.user
        notification.save(update_fields=["read_at", "updated_at", "updated_by"])
        return Response(NotificationSerializer(notification).data)

    @action(detail=False, methods=["patch"], url_path="mark-all-read")
    def mark_all_read(self, request):
        updated = (
            self.get_queryset()
            .filter(read_at__isnull=True)
            .update(read_at=timezone.now(), updated_by=request.user)
        )
        return Response({"marked": updated})

    @action(detail=False, methods=["get"], url_path="unread-count")
    def unread_count(self, request):
        version_tuple = _inbox_version(request.user)
        etag = _build_etag(version_tuple, "unread-count")
        not_modified = _maybe_304(request, etag)
        if not_modified is not None:
            return not_modified

        _, _, unread = version_tuple
        by_category = (
            Notification.objects.filter(
                recipient=request.user,
                active=True,
                read_at__isnull=True,
            )
            .values("campaign__category")
            .annotate(count=Count("id"))
        )
        summary = {row["campaign__category"]: row["count"] for row in by_category}
        # ``version`` is a stable token that advances whenever ANY inbox
        # field changes (new notification, mark-read, campaign edit). The
        # bell uses it to know when to refresh the dropdown previews even
        # if the unread count itself didn't change.
        inbox_version = _build_etag(version_tuple, "inbox-version")
        return _attach_etag(
            Response(
                {
                    "unread_count": unread,
                    "by_category": summary,
                    "version": inbox_version,
                }
            ),
            etag,
        )

    @action(detail=False, methods=["get"], url_path="summary")
    def summary(self, request):
        version = _inbox_version(request.user)
        etag = _build_etag(version, "summary")
        not_modified = _maybe_304(request, etag)
        if not_modified is not None:
            return not_modified

        _, total, unread = version
        by_category = (
            Notification.objects.filter(
                recipient=request.user,
                active=True,
                read_at__isnull=True,
            )
            .values("campaign__category")
            .annotate(count=Count("id"))
        )
        return _attach_etag(
            Response(
                {
                    "unread_count": unread,
                    "total_count": total,
                    "by_category": {
                        r["campaign__category"]: r["count"] for r in by_category
                    },
                }
            ),
            etag,
        )

    def list(self, request, *args, **kwargs):
        version = _inbox_version(request.user)
        etag = _build_etag(
            version,
            "list",
            request.query_params.get("page", "1"),
            request.query_params.get("page_size", ""),
            request.query_params.get("unread", ""),
            request.query_params.get("category", ""),
        )
        not_modified = _maybe_304(request, etag)
        if not_modified is not None:
            return not_modified

        response = super().list(request, *args, **kwargs)
        return _attach_etag(response, etag)

    # ------------------------------------------------------------------
    # Header banner channel
    # ------------------------------------------------------------------
    @action(detail=False, methods=["get"], url_path="banners")
    def banners(self, request):
        """Return the active banner notifications for the current user.

        A banner is "active" when:
          * its campaign has ``deliver_banner=True`` and is still ``active``;
          * ``banner_starts_at`` is null OR has already passed; and
          * ``banner_ends_at`` is null OR has not yet passed; and
          * the recipient hasn't dismissed it.
        """
        now = timezone.now()
        qs = (
            Notification.objects.filter(
                recipient=request.user,
                active=True,
                banner_dismissed_at__isnull=True,
                campaign__active=True,
                campaign__deliver_banner=True,
            )
            .filter(
                Q(campaign__banner_starts_at__isnull=True)
                | Q(campaign__banner_starts_at__lte=now)
            )
            .filter(
                Q(campaign__banner_ends_at__isnull=True)
                | Q(campaign__banner_ends_at__gt=now)
            )
            .select_related("campaign")
            .order_by("-campaign__created_at")
        )
        data = BannerNotificationSerializer(qs, many=True).data
        return Response({"banners": data})

    @action(detail=True, methods=["post"], url_path="dismiss-banner")
    def dismiss_banner(self, request, pk=None):
        notification = self.get_object()
        if notification.banner_dismissed_at is None:
            notification.banner_dismissed_at = timezone.now()
            notification.updated_by = request.user
            notification.save(
                update_fields=[
                    "banner_dismissed_at",
                    "updated_at",
                    "updated_by",
                ]
            )
        return Response({"id": str(notification.id), "dismissed": True})


class CampaignViewSet(viewsets.ModelViewSet):
    permission_classes = [NotificationAccessPolicy]
    pagination_class = NotificationPagination
    # Admin/manager edits are restricted to safely-editable fields. Audience,
    # channels, recipients, and lifecycle metadata are intentionally excluded
    # — changing them post-send would require re-materializing notifications.
    EDITABLE_FIELDS = (
        "title",
        "body",
        "category",
        "is_pinned",
        "deliver_banner",
        "banner_variant",
        "banner_dismissible",
        "banner_starts_at",
        "banner_ends_at",
    )

    def get_queryset(self):
        qs = NotificationCampaign.objects.select_related("created_by").filter(
            active=True
        )
        category = self.request.query_params.get("category")
        if category:
            qs = qs.filter(category=category)
        q = (self.request.query_params.get("q") or "").strip()
        if q:
            qs = qs.filter(Q(title__icontains=q) | Q(body__icontains=q))
        return qs.order_by("-created_at")

    def get_serializer_class(self):
        if self.action == "create":
            return NotificationCampaignCreateSerializer
        return NotificationCampaignSerializer

    def create(self, request, *args):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        audience = data.get("audience") or {}

        role = (getattr(request.user, "role", "") or "").lower()
        if role == Roles.TEACHER:
            assert_teacher_can_target_audience(request.user, audience)

        campaign = create_and_send_campaign(
            title=data["title"],
            body=data["body"],
            category=data.get("category", NotificationCampaign.Category.ANNOUNCEMENT),
            channels=data.get("channels") or ["in_app"],
            audience=audience,
            source=NotificationCampaign.Source.MANUAL,
            created_by=request.user,
            is_pinned=data.get("is_pinned", False),
            action_url=data.get("action_url", ""),
            banner_variant=data.get(
                "banner_variant", NotificationCampaign.BannerVariant.INFO
            ),
            banner_dismissible=data.get("banner_dismissible", True),
            banner_starts_at=data.get("banner_starts_at"),
            banner_ends_at=data.get("banner_ends_at"),
        )
        return Response(
            NotificationCampaignSerializer(campaign).data,
            status=status.HTTP_201_CREATED,
        )

    def update(self, request, *args, **kwargs):
        return self.partial_update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        campaign = self.get_object()
        # Whitelist editable fields so admins can't accidentally rewrite
        # immutable lifecycle metadata via the API.
        payload = {
            k: v for k, v in request.data.items() if k in self.EDITABLE_FIELDS
        }
        if not payload:
            return Response(NotificationCampaignSerializer(campaign).data)
        serializer = NotificationCampaignSerializer(
            campaign, data=payload, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save(updated_by=request.user)
        # Bump child Notification rows so the inbox ETag advances. Without
        # this, polling clients keep getting 304 Not Modified and never see
        # the edited title/body.
        Notification.objects.filter(campaign=campaign).update(
            updated_at=timezone.now()
        )
        return Response(serializer.data)

    def destroy(self, request, *args, **kwargs):
        campaign = self.get_object()
        # Soft delete: mark inactive and bump notification rows so clients
        # observe the change on next poll.
        if hasattr(campaign, "active"):
            campaign.active = False
            campaign.updated_by = request.user
            campaign.save(update_fields=["active", "updated_at", "updated_by"])
        else:
            campaign.delete()
        Notification.objects.filter(campaign=campaign).update(
            active=False, updated_at=timezone.now()
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class AnnouncementListView(APIView):
    permission_classes = [NotificationAccessPolicy, IsAuthenticated]

    def get(self, request):
        qs = NotificationCampaign.objects.filter(
            status=NotificationCampaign.Status.SENT,
            active=True,
        ).filter(
            Q(is_pinned=True) | Q(category=NotificationCampaign.Category.ANNOUNCEMENT)
        ).order_by("-sent_at")[:10]
        return Response(AnnouncementSerializer(qs, many=True).data)


def _ensure_default_notification_rules():
    from notifications.services.rule_bootstrap import ensure_all_default_notification_rules

    ensure_all_default_notification_rules()


class NotificationRuleViewSet(viewsets.ModelViewSet):
    permission_classes = [NotificationAccessPolicy]
    serializer_class = NotificationRuleSerializer
    queryset = NotificationRule.objects.all().order_by("event_type")
    pagination_class = None

    def list(self, request, *args, **kwargs):
        _ensure_default_notification_rules()
        return super().list(request, *args, **kwargs)


class UserPreferenceView(APIView):
    permission_classes = [NotificationAccessPolicy, IsAuthenticated]

    def get(self, request):
        pref, _ = UserNotificationPreference.objects.get_or_create(
            user_id=request.user.id,
            defaults={"email_enabled": True, "muted_categories": []},
        )
        return Response(UserNotificationPreferenceSerializer(pref).data)

    def patch(self, request):
        pref, _ = UserNotificationPreference.objects.get_or_create(
            user_id=request.user.id,
            defaults={"email_enabled": True, "muted_categories": []},
        )
        serializer = UserNotificationPreferenceSerializer(
            pref, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save(updated_by=request.user)
        return Response(serializer.data)


class TenantNotificationSettingsView(APIView):
    permission_classes = [NotificationAccessPolicy, IsAuthenticated]

    def get(self, request):
        settings_obj = TenantNotificationSettings.get_solo()
        return Response(TenantNotificationSettingsSerializer(settings_obj).data)

    def patch(self, request):
        settings_obj = TenantNotificationSettings.get_solo()
        serializer = TenantNotificationSettingsSerializer(
            settings_obj, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save(updated_by=request.user)
        return Response(serializer.data)
