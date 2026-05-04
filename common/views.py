from django.contrib.contenttypes.models import ContentType
from django_filters import rest_framework as django_filters
from rest_framework import viewsets
from rest_framework.filters import SearchFilter
from rest_framework.pagination import PageNumberPagination

from auditlog.models import LogEntry

from common.access_policies import AuditLogAccessPolicy
from common.serializers import AuditLogSerializer


ADMIN_AUDIT_APP_LABELS = {
    "admin",
    "auth",
    "contenttypes",
    "core",
    "sessions",
    "users",
}


class AuditLogPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 100


class ContentTypeNameFilter(django_filters.CharFilter):
    """Accept 'app_label.model' and resolve to content_type_id."""

    def filter(self, qs, value):
        if not value:
            return qs
        parts = value.split(".")
        if len(parts) != 2:
            return qs.none()
        app_label, model = parts
        try:
            ct = ContentType.objects.get(app_label=app_label, model=model)
        except ContentType.DoesNotExist:
            return qs.none()
        return qs.filter(content_type_id=ct.pk)


class AuditLogFilter(django_filters.FilterSet):
    content_type = django_filters.NumberFilter(field_name="content_type_id")
    content_type_name = ContentTypeNameFilter()
    object_id = django_filters.CharFilter(field_name="object_id")
    actor = django_filters.UUIDFilter(field_name="actor_id")
    action = django_filters.NumberFilter(field_name="action")
    timestamp_after = django_filters.IsoDateTimeFilter(
        field_name="timestamp", lookup_expr="gte"
    )
    timestamp_before = django_filters.IsoDateTimeFilter(
        field_name="timestamp", lookup_expr="lte"
    )

    class Meta:
        model = LogEntry
        fields = ["content_type", "content_type_name", "object_id", "actor", "action"]


class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only ViewSet for audit log entries."""

    permission_classes = [AuditLogAccessPolicy]
    serializer_class = AuditLogSerializer
    pagination_class = AuditLogPagination
    filter_backends = [django_filters.DjangoFilterBackend, SearchFilter]
    filterset_class = AuditLogFilter
    search_fields = ["object_repr", "actor__email"]

    def get_queryset(self):
        queryset = (
            LogEntry.objects.select_related("content_type", "actor")
            .order_by("-timestamp")
        )

        scope = str(self.request.query_params.get("scope") or "").strip().lower()
        if scope == "admin":
            queryset = queryset.filter(content_type__app_label__in=ADMIN_AUDIT_APP_LABELS)
        elif scope == "tenant":
            tenant = getattr(self.request, "tenant", None)
            schema_name = str(getattr(tenant, "schema_name", "")).lower()
            if schema_name in {"public", "admin"}:
                queryset = queryset.exclude(content_type__app_label__in=ADMIN_AUDIT_APP_LABELS)

        return queryset
