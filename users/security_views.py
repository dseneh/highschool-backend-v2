"""Global session-revocation endpoint."""

from django.db import transaction
from django.db.models import F
from django.utils import timezone
from django_tenants.utils import get_public_schema_name, schema_context
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from users.models import CentralAuthSession, RefreshTokenFamily, TenantSession, User


def _revoke_server_sessions(user_id, *, reason_time=None):
    now = reason_time or timezone.now()
    CentralAuthSession.objects.filter(user_id=user_id, revoked_at__isnull=True).update(revoked_at=now)
    TenantSession.objects.filter(user_id=user_id, revoked_at__isnull=True).update(revoked_at=now)
    RefreshTokenFamily.objects.filter(user_id=user_id, revoked_at__isnull=True).update(revoked_at=now)


class RevokeAllSessionsView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request):
        now = timezone.now()
        with schema_context(get_public_schema_name()):
            User.objects.filter(pk=request.user.pk).update(security_version=F("security_version") + 1)
            _revoke_server_sessions(request.user.pk, reason_time=now)
        return Response({"detail": "All sessions have been revoked. Sign in again on each device."})
