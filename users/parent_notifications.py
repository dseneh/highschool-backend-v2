"""Global parent inbox for relationship notices, independent of selected student."""
from hashlib import sha256
from django.utils import timezone
from django_tenants.utils import schema_context
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.pagination import PageNumberPagination
from users.parent_workspace import parent_identity
from students.contact_notifications import EVENT


class ParentNotificationPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class ParentNotificationsView(APIView):
    permission_classes = [IsAuthenticated]

    def schools(self, request):
        if not parent_identity(request.user):
            raise PermissionDenied("Set up your parent account first.")
        from core.models import Tenant
        # An informational contact notice may predate school membership/portal approval.
        return Tenant.objects.filter(active=True, status="active", maintenance_mode=False, restoration_in_progress=False).exclude(schema_name="public")

    def inbox(self, request):
        from notifications.models import Notification
        return Notification.objects.filter(recipient=request.user, active=True,
            campaign__active=True, campaign__audience__event=EVENT).select_related("campaign")

    def serialize(self, item, school):
        from notifications.serializers import NotificationSerializer
        data = dict(NotificationSerializer(item).data)
        data["id"] = f"{school.pk}:{item.pk}"
        data["school"] = {"id": str(school.pk), "name": school.name}
        return data

    def get(self, request, action=""):
        if action == "banners":
            self.schools(request)
            return Response({"banners": []})
        if action not in {"", "summary", "unread-count"}:
            raise NotFound()
        rows = []
        for school in self.schools(request).iterator():
            with schema_context(school.schema_name):
                rows.extend(self.serialize(item, school) for item in self.inbox(request))
        rows.sort(key=lambda row: (row["created_at"], row["id"]), reverse=True)
        unread = sum(not row["is_read"] for row in rows)
        if action:
            version = sha256(str([(row["id"], row["read_at"]) for row in rows]).encode()).hexdigest()
            return Response({"unread_count": unread, "total_count": len(rows), "by_category": {"system": unread}, "version": version}, headers={"Cache-Control": "no-store"})
        if request.query_params.get("unread") in {"true", "1", "yes"}:
            rows = [row for row in rows if not row["is_read"]]
        category = request.query_params.get("category")
        if category:
            rows = [row for row in rows if row["category"] == category]
        paginator = ParentNotificationPagination()
        result = paginator.get_paginated_response(paginator.paginate_queryset(rows, request))
        result["Cache-Control"] = "no-store"
        return result

    def patch(self, request, action=""):
        schools = self.schools(request)
        if action == "mark-all-read":
            marked = 0
            for school in schools.iterator():
                with schema_context(school.schema_name):
                    marked += self.inbox(request).filter(read_at__isnull=True).update(read_at=timezone.now(), updated_at=timezone.now())
            return Response({"marked": marked})
        from uuid import UUID
        try:
            key, operation = action.split("/")
            school_id, item_id = map(UUID, key.split(":"))
            if operation != "mark-read":
                raise ValueError()
        except (ValueError, TypeError):
            raise NotFound()
        school = schools.filter(pk=school_id).first()
        if not school:
            raise NotFound()
        read = request.data.get("read", True)
        if not isinstance(read, bool):
            raise ValidationError({"read": "Choose true or false."})
        with schema_context(school.schema_name):
            item = self.inbox(request).filter(pk=item_id).first()
            if not item:
                raise NotFound()
            item.read_at = timezone.now() if read else None
            item.save(update_fields=["read_at", "updated_at"])
            return Response(self.serialize(item, school))
