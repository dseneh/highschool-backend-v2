"""Identity-aware scoping for the existing UserViewSet.

The base viewset retains CRUD/actions. This subclass only owns visibility rules
while the legacy account_type=global behavior is being retired.
"""

from django.db import connection
from django.db.models import Q
from django_tenants.utils import get_public_schema_name, schema_context

from common.status import UserAccountScope
from users.models import User
from users.viewsets import UserViewSet


class ScopedUserViewSet(UserViewSet):
    def _apply_user_filters(self, queryset):
        queryset = super()._apply_user_filters(queryset)
        scopes = self.request.query_params.getlist("account_scope")
        if scopes:
            queryset = queryset.filter(account_scope__in=scopes)
        return queryset

    def _tenant_users_queryset(self, schema_name: str):
        """Return users relevant to one tenant without exposing platform-only operators.

        A platform user who is also a real Staff/Student/Parent profile in this
        tenant remains visible as that tenant persona. A platform operator who
        merely has administrative tenant access stays hidden from normal tenant
        users; platform superadmins can see assigned operators.
        """
        from tenant_users.permissions.models import UserTenantPermissions

        request_user = getattr(getattr(self, "request", None), "user", None)
        request_user_id = getattr(request_user, "pk", None)
        request_user_is_superadmin = bool(
            getattr(request_user, "is_platform_superuser", False)
        )

        with schema_context(schema_name):
            permission_user_ids = set(
                UserTenantPermissions.objects.values_list("profile_id", flat=True).distinct()
            )
            linked_user_id_numbers = self._get_linked_user_id_numbers()

        public_schema = get_public_schema_name()
        with schema_context(public_schema):
            assigned_filter = Q(id__in=list(permission_user_ids))
            linked_profile_filter = Q(id_number__in=list(linked_user_id_numbers))
            tenant_identity_filter = Q(account_scope=UserAccountScope.TENANT.value)

            if request_user_is_superadmin:
                # Super Admin may see platform/global users only when they are
                # actually assigned to this tenant, plus all linked personas.
                visibility_filter = assigned_filter | linked_profile_filter | Q(pk=request_user_id)
            else:
                # Linked tenant personas remain visible even when the same
                # identity also has platform access. Administrative platform
                # users with no school profile are otherwise hidden.
                visibility_filter = (
                    linked_profile_filter
                    | (assigned_filter & tenant_identity_filter)
                    | Q(pk=request_user_id)
                )

            return User.objects.filter(visibility_filter).distinct()

    def get_queryset(self):
        if self.action == "current":
            return User.objects.none()

        public_schema = get_public_schema_name()
        if connection.schema_name != public_schema:
            try:
                return self._apply_user_filters(
                    self._tenant_users_queryset(connection.schema_name)
                )
            except Exception:
                return User.objects.none()

        tenant_filter = (self.request.query_params.get("tenant") or "").strip()
        if tenant_filter:
            from core.models import Tenant

            if not Tenant.objects.filter(schema_name=tenant_filter).exists():
                return User.objects.none()
            try:
                return self._apply_user_filters(self._tenant_users_queryset(tenant_filter))
            except Exception:
                return User.objects.none()

        # Public/admin users are determined by access, not persona. Include:
        # - explicit platform-capable identities,
        # - platform superadmins,
        # - unassigned/orphan identities for administrative cleanup.
        with schema_context(public_schema):
            tenant_member_ids = list(
                User.tenants.through.objects.values_list("user_id", flat=True).distinct()
            )
            queryset = User.objects.filter(
                Q(account_scope__in=[
                    UserAccountScope.PLATFORM.value,
                    UserAccountScope.PLATFORM_AND_TENANT.value,
                ])
                | Q(is_platform_superuser=True)
                | ~Q(pk__in=tenant_member_ids)
            ).distinct()
            return self._apply_user_filters(queryset)
