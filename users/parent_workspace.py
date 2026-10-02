"""Global parent workspace identity and strict request scope."""
from django_tenants.utils import get_public_schema_name
from rest_framework.exceptions import PermissionDenied


def is_parent_workspace(request):
    return getattr(request, "META", {}).get("HTTP_X_TENANT", "").lower() == "parent" or getattr(request, "META", {}).get("HTTP_X_PARENT_WORKSPACE") == "1"


def parent_identity(user):
    from users.models import ParentProfile
    return bool(user and user.is_active and user.status == "active" and ParentProfile.objects.filter(user=user).exists())


def bind_parent_request(request, user):
    """Parent-only tokens may never fall back to employee or platform permissions."""
    path = request.path.rstrip("/")
    own_path = f"/api/v1/auth/users/{user.id_number}"
    if path == own_path and request.method not in {"GET", "HEAD", "OPTIONS"}:
        if request.method not in {"PUT", "PATCH"}:
            raise PermissionDenied("This action is unavailable in the Parent workspace.")
        if set(request.data) - {"username", "first_name", "last_name", "email", "photo"}:
            raise PermissionDenied("Only personal profile fields can be changed here.")
        if "email" in request.data and str(request.data["email"]).strip().lower() != user.email.strip().lower():
            raise PermissionDenied("Contact your school to update your verified email.")
    tenant = getattr(request, "tenant", None)
    if not tenant or tenant.schema_name == get_public_schema_name():
        path = request.path.rstrip("/")
        import re
        own_path = f"/api/v1/auth/users/{user.id_number}"
        allowed = path in {own_path, f"{own_path}/password/change"} or bool(re.fullmatch(r"/api/v1/auth/parent/(?:links/[a-f0-9-]+/select|context/[a-f0-9-]+)", path)) or path in {
            "/api/v1/auth/users/current", "/api/v1/auth/parent/summary",
            "/api/v1/auth/parent/workspace", "/api/v1/auth/parent/roles", "/api/v1/auth/logout",
            "/api/v1/sso/bootstrap", "/api/v1/sso/authorize", "/api/v1/sso/logout", "/api/v1/sso/session",
        } or path.startswith("/api/v1/auth/account-setup/") or path == "/api/v1/auth/parent/notifications" or path.startswith("/api/v1/auth/parent/notifications/")
        if not allowed:
            raise PermissionDenied("Choose a linked student's school for this action.")
        request.META["HTTP_X_ROLE_ASSIGNMENT"] = "parent-workspace-no-platform-access"
    else:
        from users.parent_portal import parent_assignment
        assignment = parent_assignment(user)
        if not assignment:
            raise PermissionDenied("No active Parent role in this school.")
        request.META["HTTP_X_ROLE_ASSIGNMENT"] = str(assignment.pk)

from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response


class ParentWorkspaceView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not parent_identity(request.user):
            raise PermissionDenied("Set up your parent account first.")
        user = request.user
        from users.models import ParentSchoolRegistration, ParentStudentLink
        from core.models import Tenant
        from django.db.models import Q
        registered = ParentSchoolRegistration.objects.filter(profile__user=user).values_list("tenant_id", flat=True)
        linked = ParentStudentLink.objects.filter(profile__user=user, active=True).values_list("tenant_id", flat=True)
        schools = list(Tenant.objects.filter(Q(pk__in=registered) | Q(pk__in=linked), active=True, status="active").values("schema_name", "name"))
        return Response({"id": str(user.pk), "id_number": user.id_number,
            "schools": schools, "photo": request.build_absolute_uri(user.photo.url) if user.photo else None, "email": user.email, "first_name": user.first_name, "last_name": user.last_name,
            "account_type": user.account_type, "is_platform_superuser": False,
            "rbac_role": {"id": "parent", "name": "Parent", "system_key": "parent"},
            "role_context_restricted": True, "workspace": "parent"})


class ParentWorkspaceContextView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, link_id):
        from users.parent_portal import resolve_link
        from users.parent_portal import link_payload
        link, guardian, assignment = resolve_link(request.user, link_id)
        return Response({**link_payload(link, guardian, request), "assignment_id": str(assignment.pk)})


class ParentWorkspaceRolesView(APIView):
    """Discovery only: school sessions must validate any subsequent role switch."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not parent_identity(request.user):
            raise PermissionDenied("Set up your parent account first.")
        from django_tenants.utils import schema_context
        from authorization.models import TenantRoleAssignment
        from authorization.multiple_roles import assignment_role
        assignments = []
        for school in request.user.tenants.filter(active=True, status="active").exclude(schema_name=get_public_schema_name()).order_by("name"):
            with schema_context(school.schema_name):
                for assignment in TenantRoleAssignment.objects.filter(
                    membership__user=request.user, membership__is_active=True, is_active=True,
                ).select_related("role"):
                    role = assignment_role(assignment)
                    if role is None or not role.is_active:
                        continue
                    assignments.append({
                        "id": str(assignment.pk), "is_active": True,
                        "role": {"id": str(role.pk), "name": role.name, "system_key": role.system_key},
                        "school": {"schema_name": school.schema_name, "name": school.name},
                    })
        return Response({"assignments": assignments, "active_assignment_id": None,
                         "can_use_platform_context": bool(getattr(request.user, "is_platform_superuser", False)), "platform_context_active": False})
