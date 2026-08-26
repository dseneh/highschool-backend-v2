"""
Views for core models (Tenant management)
"""

import secrets
import re
from datetime import timedelta

from django.conf import settings
from django.db import connection, IntegrityError, transaction
from django.db.models import Q
from django.core.cache import cache
from django.contrib.auth.hashers import make_password
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated, IsAdminUser, AllowAny
from rest_framework.viewsets import ModelViewSet
from rest_framework.exceptions import ValidationError, NotFound
from rest_framework.decorators import (
    api_view,
    permission_classes,
    authentication_classes,
    action,
)
from rest_framework.response import Response
from rest_framework import status, viewsets
from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser, FormParser
from django_tenants.utils import schema_context
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from PIL import Image
from io import BytesIO

from core.models import (
    Domain,
    Tenant,
    SignupRequest,
    TenantOwnerActivationCode,
    GradingBypassOperation,
    TenantCreationJob,
)
from core.services.grading_bypass import (
    build_preview as build_grading_bypass_preview,
    create_bypass_job,
    run_bypass_job,
    build_outcome_summary as build_grading_bypass_outcome_summary,
)
from core.serializers import (
    TenantSerializer,
    CreateTenantSerializer,
    PublicTenantSerializer,
    TenantListSerializer,
    TenantInfoSearchResultSerializer,
    get_signup_request_linked_tenant,
    get_signup_request_owner,
)
from common.utils import update_model_fields
from common.audit_utils import log_tenant_control_change
from common.permissions import IsSuperAdmin
from core.services.tenant_deletion import hard_delete_tenant_workspace
from core.services.tenant_clone import module_metadata, resolve_modules, start_tenant_creation_job
from common.email_service import send_tenant_owner_activation_email
from users.utils import build_activation_url
from students.models import Student
from staff.models import Staff

User = get_user_model()

ACTIVATION_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


class PublicSchoolSearchView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        from core.account_discovery import allow_request, public_school_results, request_ip

        if not allow_request("schools-ip", request_ip(request), limit=60, window=60):
            return Response({"detail": "Too many requests. Please try again shortly."}, status=429)
        query = str(request.query_params.get("query") or "").strip()
        if len(query) < 2:
            return Response({"detail": "Enter at least two characters."}, status=400)
        results = public_school_results(query, str(request.query_params.get("location") or ""))
        return Response({"count": len(results), "results": results})


class AccountDiscoveryStartView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        from core.account_discovery import (
            GENERIC_MESSAGE,
            allow_request,
            create_challenge,
            identifier_digest,
            normalize_identifier,
            request_ip,
        )

        try:
            identifier = normalize_identifier(
                str(request.data.get("identifier") or ""), request.data.get("identifier_type")
            )
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)
        allowed = allow_request("start-ip", request_ip(request), limit=10, window=900)
        allowed = allowed and allow_request(
            "start-identifier", identifier_digest(identifier), limit=3, window=900
        )
        if not allowed:
            return Response({"detail": "Too many requests. Please try again later."}, status=429)
        challenge_id = create_challenge(identifier)
        response = {"message": GENERIC_MESSAGE, "challenge_id": challenge_id, "expires_in": 600}
        return Response(response, status=202)


class AccountDiscoveryVerifyView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        from core.account_discovery import allow_request, request_ip, verify_challenge

        challenge_id = str(request.data.get("challenge_id") or "").strip()
        code = str(request.data.get("code") or "").strip()
        if not challenge_id or not re.fullmatch(r"\d{6}", code):
            return Response({"detail": "The verification code is invalid or has expired."}, status=400)
        if not allow_request("verify-ip", request_ip(request), limit=30, window=900):
            return Response({"detail": "Too many requests. Please try again later."}, status=429)
        verified = verify_challenge(challenge_id, code)
        if not verified:
            return Response({"detail": "The verification code is invalid or has expired."}, status=400)
        discovery_token, accounts = verified
        return Response({"discovery_token": discovery_token, "expires_in": 300, "accounts": accounts})


def _generate_activation_code(length: int = 8) -> str:
    return "".join(secrets.choice(ACTIVATION_CODE_ALPHABET) for _ in range(length))


def validate_tenant_is_in_public_schema():
    """
    Validate that the tenant is in the public schema.
    """
    if connection.schema_name != "public":
        raise ValidationError(
            {"detail": "Tenant operations must be performed in the public schema"}
        )
    return True


@api_view(["GET"])
@permission_classes([AllowAny])
def current_tenant(request):
    """
    Get the current tenant information based on the request schema.
    """
    if connection.schema_name == "public":
        return Response(
            {"detail": "No tenant context found (public schema)"}, status=400
        )

    try:
        tenant = Tenant.objects.get(schema_name=connection.schema_name)
        serializer = PublicTenantSerializer(tenant, context={"request": request})
        return Response(serializer.data)
    except Tenant.DoesNotExist:
        return Response({"detail": "Tenant not found"}, status=404)


class TenantViewSet(ModelViewSet):
    """
    ViewSet for Tenant management.

    Provides standard CRUD operations:
    - list: GET /api/v1/tenants/
    - create: POST /api/v1/tenants/
    - retrieve: GET /api/v1/tenants/{schema_name}/
    - update: PUT /api/v1/tenants/{schema_name}/
    - partial_update: PATCH /api/v1/tenants/{schema_name}/
    - destroy: DELETE /api/v1/tenants/{schema_name}/

    All operations must be performed in the public schema context.
    Only superusers or staff can perform tenant management operations.
    """

    queryset = Tenant.objects.all().order_by("name")
    lookup_field = "schema_name"
    lookup_url_kwarg = "schema_name"
    # Permissions are set dynamically in get_permissions() method

    # Fields allowed to be updated (filters out unwanted fields for performance)
    # NOTE: schema_name, id_number, and id are NOT in this list - they should NEVER be changed after creation
    # Changing schema_name would break tenant data access since django-tenants doesn't rename the PostgreSQL schema
    ALLOWED_UPDATE_FIELDS = [
        "name",
        "short_name",
        "funding_type",
        "school_division",
        "slogan",
        "emis_number",
        "description",
        "date_est",
        "address",
        "city",
        "state",
        "country",
        "postal_code",
        "phone",
        "email",
        "website",
        "status",
        "logo",
        "logo_shape",
        "theme_color",
        "theme_config",
        "active",
        "maintenance_mode",
        "login_access_policy",
        "disabled_access_allow_tenant_admins",
        "disabled_access_allowed_paths",
        "disabled_access_allowed_users",
    ]
    AUDITED_CONTROL_FIELDS = [
        "status",
        "active",
        "maintenance_mode",
        "login_access_policy",
        "disabled_access_allow_tenant_admins",
        "disabled_access_allowed_paths",
        "disabled_access_allowed_users",
    ]

    def _capture_control_state(self, instance):
        return {
            "status": getattr(instance, "status", None),
            "active": getattr(instance, "active", None),
            "maintenance_mode": getattr(instance, "maintenance_mode", None),
            "login_access_policy": getattr(instance, "login_access_policy", None),
            "disabled_access_allow_tenant_admins": getattr(instance, "disabled_access_allow_tenant_admins", None),
            "disabled_access_allowed_paths": getattr(instance, "disabled_access_allowed_paths", None),
            "disabled_access_allowed_users": getattr(instance, "disabled_access_allowed_users", None),
        }

    def _log_control_change_if_needed(self, request, instance, before_state, response):
        if response.status_code < 200 or response.status_code >= 300:
            return response

        if not any(field in request.data for field in self.AUDITED_CONTROL_FIELDS):
            return response

        instance.refresh_from_db()
        after_state = self._capture_control_state(instance)
        log_tenant_control_change(request, request.user, instance, before_state, after_state)
        return response

    def get_permissions(self):
        """
        Allow public access (no authentication) for list and retrieve actions.
        Require authentication and superadmin permissions for create, update, delete.

        Superadmin users can perform any operation in the system.
        """
        if self.action in ["list", "retrieve"]:
            return [AllowAny()]
        return [IsAuthenticated(), IsSuperAdmin()]

    def get_serializer_class(self):
        """
        Use appropriate serializer based on action and authentication status.
        """
        if self.action == "create":
            return CreateTenantSerializer
        elif self.action == "list":
            # Use lightweight list serializer for better performance
            return TenantListSerializer
        elif self.action == "retrieve":
            # Use public serializer for unauthenticated users (public endpoints)
            if not self.request.user.is_authenticated:
                return PublicTenantSerializer
        return TenantSerializer

    def get_queryset(self):
        """
        Ensure we're in the public schema and return appropriate tenants.

        Excludes public tenant always. Deleted tenants are hidden by default
        but authenticated superadmins can opt into seeing them via
        ``?include_deleted=true`` or ``?status=deleted`` so they can manage /
        reactivate soft-deleted workspaces. Unauthenticated public callers
        only ever see active tenants.
        """
        from django_tenants.utils import get_public_schema_name

        if connection.schema_name != "public":
            return Tenant.objects.none()

        public_schema = get_public_schema_name()
        queryset = super().get_queryset().select_related("school_division")

        # Exclude public tenant (always)
        queryset = queryset.exclude(schema_name=public_schema)

        # Decide whether deleted tenants should be visible. We always keep
        # them out for unauthenticated requests; an authenticated superadmin
        # explicitly opting in (via ?include_deleted=true, ?show_deleted=true
        # or ?status=deleted) can see them — useful for the admin tenant
        # list and reactivate flows.
        request = getattr(self, "request", None)
        params = getattr(request, "query_params", {}) if request else {}
        include_deleted_param = str(
            params.get("include_deleted")
            or params.get("show_deleted")
            or ""
        ).strip().lower() in {"1", "true", "yes"}
        status_filter = str(params.get("status") or "").strip().lower()
        wants_deleted = include_deleted_param or status_filter == "deleted"

        user = getattr(request, "user", None) if request else None
        is_authed = bool(user and getattr(user, "is_authenticated", False))

        if not (is_authed and wants_deleted):
            queryset = queryset.exclude(status="deleted")

        # Honor an explicit status filter (e.g. ?status=deleted or
        # ?status=on_hold) for the admin tenant list page.
        if status_filter and status_filter != "all":
            queryset = queryset.filter(status=status_filter)

        # For unauthenticated public endpoints, only show active tenants.
        if (
            self.action in ["list", "retrieve"]
            and not is_authed
        ):
            queryset = queryset.filter(active=True)

        return queryset

    def get_object(self):
        """
        Resolve "admin" or "public" workspace alias to the public tenant on retrieve.

        This allows public lookup endpoints like:
        GET /api/v1/tenants/admin/
        GET /api/v1/tenants/public/
        to return the public schema tenant metadata.
        """
        from django_tenants.utils import get_public_schema_name

        lookup_kwarg = self.lookup_url_kwarg or self.lookup_field
        lookup_value = self.kwargs.get(lookup_kwarg)

        if (
            self.action == "retrieve"
            and isinstance(lookup_value, str)
            and lookup_value.lower() in ["admin", "public"]
        ):
            try:
                obj = Tenant.objects.get(schema_name=get_public_schema_name())
            except Tenant.DoesNotExist:
                raise NotFound("Public tenant not found")

            self.check_object_permissions(self.request, obj)
            return obj

        if self.action == "retrieve" and isinstance(lookup_value, str):
            # Fallback: allow retrieving tenant by domain prefix when host slug
            # differs from schema_name (common in local/dev vanity domains).
            domain_match = (
                Domain.objects.select_related("tenant")
                .filter(domain__istartswith=f"{lookup_value.lower()}.")
                .order_by("-is_primary")
                .first()
            )
            if domain_match and getattr(domain_match, "tenant", None):
                obj = self.get_queryset().filter(pk=domain_match.tenant_id).first()
                if obj:
                    self.check_object_permissions(self.request, obj)
                    return obj

        return super().get_object()

    def perform_create(self, serializer):
        """
        Create tenant - custom logic is handled in CreateTenantSerializer.create().
        """
        # Ensure we're in the public schema
        validate_tenant_is_in_public_schema()
        serializer.save()

    def create(self, request, *args, **kwargs):
        """Queue tenant creation. Default and clone share one background workflow."""
        validate_tenant_is_in_public_schema()
        initialization_source = request.data.get("initialization_source", "default")
        if initialization_source not in {"default", "clone"}:
            raise ValidationError({"initialization_source": "Use 'default' or 'clone'."})
        is_clone = initialization_source == "clone"

        source = None
        selected_modules = []
        if is_clone:
            source_schema = str(request.data.get("source_tenant") or "").strip()
            selected_modules = request.data.get("clone_modules") or []
            if not source_schema:
                raise ValidationError({"source_tenant": "A source tenant is required."})
            if not isinstance(selected_modules, list) or not selected_modules:
                raise ValidationError({"clone_modules": "Select at least one supported module."})
            resolve_modules(selected_modules)

            source = Tenant.objects.filter(
                schema_name=source_schema,
                active=True,
            ).exclude(status=Tenant.STATUS_DELETED).first()
            if source is None:
                raise ValidationError({"source_tenant": "The source tenant does not exist or is not accessible."})

        creation_payload = {
            key: value
            for key, value in request.data.items()
            if key not in {"initialization_source", "source_tenant", "clone_modules"}
        }
        serializer = CreateTenantSerializer(data=creation_payload, context={"request": request})
        serializer.is_valid(raise_exception=True)
        destination_schema = serializer.validated_data.get("schema_name")
        if not destination_schema:
            short_name = serializer.validated_data.get("short_name") or serializer.validated_data["name"][:10]
            destination_schema = "".join(
                character for character in short_name.lower().replace(" ", "_").replace("-", "_")
                if character.isalnum() or character == "_"
            )
            creation_payload["schema_name"] = destination_schema
        if source is not None and source.schema_name == destination_schema:
            raise ValidationError({"schema_name": "Destination must differ from the source tenant."})

        active_statuses = [TenantCreationJob.Status.PENDING, TenantCreationJob.Status.IN_PROGRESS]
        existing_job = TenantCreationJob.objects.filter(
            destination_schema=destination_schema,
            status__in=active_statuses,
        ).first()
        if existing_job:
            return Response(self._creation_job_data(existing_job), status=status.HTTP_202_ACCEPTED)

        try:
            with transaction.atomic():
                job = TenantCreationJob.objects.create(
                    initialization_source=initialization_source,
                    source_tenant=source,
                    source_schema=source.schema_name if source else "",
                    destination_schema=destination_schema,
                    requested_by=request.user,
                    selected_modules=selected_modules,
                    request_payload=creation_payload,
                )
        except IntegrityError:
            job = TenantCreationJob.objects.get(
                destination_schema=destination_schema,
                status__in=active_statuses,
            )
        start_tenant_creation_job(job)
        return Response(self._creation_job_data(job), status=status.HTTP_202_ACCEPTED)

    @staticmethod
    def _creation_job_data(job):
        return {
            "job_id": str(job.pk),
            "initialization_source": job.initialization_source,
            "status": job.status,
            "stage": job.stage,
            "progress_percent": job.progress_percent,
            "failure_detail": job.failure_detail or None,
            "destination_schema": job.destination_schema,
            "tenant_schema": (job.result or {}).get("tenant_schema"),
            "cloned_counts": (job.result or {}).get("cloned_counts"),
        }

    @action(
        detail=False,
        methods=["get"],
        url_path="clone-modules",
        permission_classes=[IsAuthenticated, IsSuperAdmin],
    )
    def clone_modules(self, request):
        validate_tenant_is_in_public_schema()
        return Response({
            "results": module_metadata(),
            "excluded_data": [
                "users and tenant memberships",
                "students and guardians",
                "employees and staff assignments",
                "attendance, grades, and transcripts",
                "payments, journal entries, balances, and transactions",
                "payroll periods, employee compensation, and payroll runs",
                "notification campaigns and user preferences",
            ],
        })

    @action(
        detail=False,
        methods=["get"],
        url_path=r"creation-jobs/(?P<job_id>[^/.]+)",
        permission_classes=[IsAuthenticated, IsSuperAdmin],
    )
    def creation_job_status(self, request, job_id=None):
        validate_tenant_is_in_public_schema()
        job = TenantCreationJob.objects.filter(pk=job_id).first()
        if job is None:
            raise NotFound("Tenant creation job was not found.")
        if job.status == TenantCreationJob.Status.PENDING:
            start_tenant_creation_job(job)
        return Response(self._creation_job_data(job))

    def update(self, request, *args, **kwargs):
        """
        Update tenant using field filtering for performance.
        Only updates fields that are in the request and in allowed_fields list.
        """
        validate_tenant_is_in_public_schema()

        instance = self.get_object()
        before_state = self._capture_control_state(instance)

        data = {key: value for key, value in request.data.items() if key in self.ALLOWED_UPDATE_FIELDS}
        serializer = TenantSerializer(instance, data=data, partial=True, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        response = Response(serializer.data)
        return self._log_control_change_if_needed(request, instance, before_state, response)

    def partial_update(self, request, *args, **kwargs):
        """
        Partially update tenant using field filtering for performance.
        Only updates fields that are in the request and in allowed_fields list.
        """
        validate_tenant_is_in_public_schema()

        instance = self.get_object()
        before_state = self._capture_control_state(instance)

        data = {key: value for key, value in request.data.items() if key in self.ALLOWED_UPDATE_FIELDS}
        serializer = TenantSerializer(instance, data=data, partial=True, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        response = Response(serializer.data)
        return self._log_control_change_if_needed(request, instance, before_state, response)

    def perform_destroy(self, instance):
        """
        Delete tenant - ensure we're in the public schema.

        Default behavior is soft delete: sets status to 'deleted' and active to False.
        If request query includes hard=true, performs a permanent delete by
        dropping the tenant schema and deleting the tenant record.

        A future cron / GC job will hard-delete tenants that have been in the
        deleted state for longer than the retention period. In the meantime
        the tenant can be brought back via the `reactivate` action.
        """
        from django_tenants.utils import get_public_schema_name

        validate_tenant_is_in_public_schema()

        # Prevent public tenant deletion
        if instance.schema_name == get_public_schema_name():
            raise ValidationError({"detail": "Cannot delete public tenant"})

        hard_param = str(self.request.query_params.get("hard", "")).strip().lower()
        hard_delete = hard_param in {"1", "true", "yes"}

        if hard_delete:
            try:
                hard_delete_tenant_workspace(instance)
            except ValueError as exc:
                raise ValidationError({"detail": str(exc)}) from exc
            return

        # Soft delete: Set status to 'deleted' and active to False
        # The save() method will automatically sync active with status
        instance.status = "deleted"
        instance.active = False  # Explicitly set, but save() will sync it anyway
        instance.save(update_fields=["status", "active"])

    @action(
        detail=False,
        methods=["get"],
        url_path="summary",
        permission_classes=[IsAuthenticated, IsSuperAdmin],
    )
    def summary(self, request, *args, **kwargs):
        """Return aggregate tenant + signup pipeline metrics for the admin dashboard."""
        from django_tenants.utils import get_public_schema_name

        validate_tenant_is_in_public_schema()

        public_schema = get_public_schema_name()
        tenant_qs = Tenant.objects.exclude(schema_name=public_schema)
        non_deleted_tenant_qs = tenant_qs.exclude(status="deleted")

        signup_qs = SignupRequest.objects.all()
        recent_cutoff = timezone.now() - timedelta(days=7)

        return Response(
            {
                "tenants": {
                    "total": tenant_qs.count(),
                    "active": non_deleted_tenant_qs.filter(active=True).count(),
                    "inactive": non_deleted_tenant_qs.filter(active=False).count(),
                    "maintenance": non_deleted_tenant_qs.filter(maintenance_mode=True).count(),
                    "deleted": tenant_qs.filter(status="deleted").count(),
                },
                "signup_requests": {
                    "total": signup_qs.count(),
                    "pending": signup_qs.filter(status=SignupRequest.STATUS_PENDING).count(),
                    "contacted": signup_qs.filter(status=SignupRequest.STATUS_CONTACTED).count(),
                    "onboarded": signup_qs.filter(status=SignupRequest.STATUS_ONBOARDED).count(),
                    "declined": signup_qs.filter(status=SignupRequest.STATUS_DECLINED).count(),
                    "recent_7d": signup_qs.filter(submitted_at__gte=recent_cutoff).count(),
                },
            },
            status=status.HTTP_200_OK,
        )

    @action(
        detail=True,
        methods=["post"],
        url_path="reactivate",
        permission_classes=[IsAuthenticated, IsSuperAdmin],
    )
    def reactivate(self, request, *args, **kwargs):
        """Reactivate a soft-deleted (or otherwise non-operational) tenant.

        Endpoint:
        - POST /api/v1/tenants/{schema_name}/reactivate/

        Resets status -> 'active' and active -> True so the workspace can
        be used again. Only available to superadmins. The tenant must
        already exist in the public schema (a hard-deleted tenant cannot
        be recovered via this endpoint).
        """
        from django_tenants.utils import get_public_schema_name

        validate_tenant_is_in_public_schema()

        # We need to be able to fetch deleted tenants too — so query the
        # raw Tenant manager rather than the filtered get_queryset() to
        # locate the instance for reactivation.
        schema_name = kwargs.get(self.lookup_field) or kwargs.get("pk")
        try:
            instance = Tenant.objects.get(**{self.lookup_field: schema_name})
        except Tenant.DoesNotExist:
            return Response(
                {"detail": "Tenant not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if instance.schema_name == get_public_schema_name():
            return Response(
                {"detail": "Public tenant cannot be reactivated."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        before_state = self._capture_control_state(instance)

        instance.status = "active"
        instance.active = True
        instance.save(update_fields=["status", "active"])

        after_state = self._capture_control_state(instance)
        try:
            log_tenant_control_change(
                request, request.user, instance, before_state, after_state
            )
        except Exception:
            # Audit logging must never block the action itself.
            pass

        serializer = TenantSerializer(instance, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(
        detail=True,
        methods=["put", "patch"],
        url_path="logo",
        parser_classes=[MultiPartParser, FormParser],
    )
    def update_logo(self, request, *args, **kwargs):
        """
        Upload/update tenant logo.

        Endpoint:
        - PUT /api/v1/tenants/{schema_name}/logo/
        """
        validate_tenant_is_in_public_schema()

        instance = self.get_object()
        logo_file = request.FILES.get("logo")
        if not logo_file:
            raise ValidationError({"logo": "Logo file is required."})

        # Resize raster images to reduce storage while keeping original format
        if logo_file.content_type != "image/svg+xml":
            max_dimension = 512
            image = Image.open(logo_file)
            image_format = image.format or "PNG"

            if image.mode in ("P", "RGBA") and image_format.upper() == "JPEG":
                image = image.convert("RGB")

            image.thumbnail((max_dimension, max_dimension))

            buffer = BytesIO()
            save_kwargs = {}
            if image_format.upper() == "JPEG":
                save_kwargs = {"quality": 85, "optimize": True}
            elif image_format.upper() == "PNG":
                save_kwargs = {"optimize": True}

            image.save(buffer, format=image_format, **save_kwargs)
            buffer.seek(0)

            content = ContentFile(buffer.read())
            instance.logo.save(logo_file.name, content, save=False)
        else:
            instance.logo = logo_file

        logo_shape = request.data.get("logo_shape")
        if logo_shape:
            instance.logo_shape = logo_shape

        instance.save()

        serializer = TenantSerializer(instance, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(
        detail=True,
        methods=["get"],
        url_path="academic-years",
        permission_classes=[IsAuthenticated, IsSuperAdmin],
    )
    def academic_years(self, request, *args, **kwargs):
        """List academic years for the tenant, ordered most-recent first.

        Endpoint:
        - GET /api/v1/tenants/{schema_name}/academic-years/

        Returns a list of `{ id, name, start_date, end_date, current, status }`
        suitable for populating an academic year selector in the admin UI.
        """
        validate_tenant_is_in_public_schema()
        tenant = self.get_object()

        from academics.models import AcademicYear

        with schema_context(tenant.schema_name):
            rows = list(
                AcademicYear.objects.all().values(
                    "id",
                    "name",
                    "start_date",
                    "end_date",
                    "current",
                    "status",
                )
            )

        return Response({"results": rows}, status=status.HTTP_200_OK)

    @action(
        detail=True,
        methods=["get"],
        url_path="grading-bypass-preview",
        permission_classes=[IsAuthenticated, IsSuperAdmin],
    )
    def grading_bypass_preview(self, request, *args, **kwargs):
        validate_tenant_is_in_public_schema()
        academic_year_id = request.query_params.get("academic_year")
        if not academic_year_id:
            raise ValidationError({"academic_year": "An academic year is required."})
        return Response(build_grading_bypass_preview(
            tenant=self.get_object(),
            academic_year_id=academic_year_id,
            page=request.query_params.get("page", 1),
            page_size=request.query_params.get("page_size", 25),
            search=(request.query_params.get("search") or "").strip(),
            grade_level=(request.query_params.get("grade_level") or "").strip(),
            section=(request.query_params.get("section") or "").strip(),
        ))

    @action(
        detail=True,
        methods=["post"],
        url_path="grading-bypass",
        permission_classes=[IsAuthenticated, IsSuperAdmin],
    )
    def grading_bypass(self, request, *args, **kwargs):
        validate_tenant_is_in_public_schema()
        if request.data.get("consent_acknowledged") is not True:
            raise ValidationError({"consent_acknowledged": "Explicit consent is required before executing a grading bypass."})
        academic_year_id = request.data.get("academic_year")
        if not academic_year_id:
            raise ValidationError({"academic_year": "An academic year is required."})
        operation = create_bypass_job(
            tenant=self.get_object(),
            academic_year_id=academic_year_id,
            actor=request.user,
            payload=request.data,
        )
        return Response({
            "job_id": str(operation.pk),
            "status": operation.status,
            "stage": operation.stage,
            "students_processed": operation.students_processed,
            "total_students": operation.total_students,
            "progress_percent": operation.progress_percent,
        }, status=status.HTTP_202_ACCEPTED)

    @action(
        detail=True,
        methods=["get"],
        url_path="grading-bypass-status/(?P<job_id>[^/.]+)",
        permission_classes=[IsAuthenticated, IsSuperAdmin],
    )
    def grading_bypass_status(self, request, *args, **kwargs):
        validate_tenant_is_in_public_schema()
        operation = GradingBypassOperation.objects.filter(
            pk=kwargs["job_id"], tenant=self.get_object()
        ).first()
        if operation is None:
            raise NotFound("Grading bypass job was not found.")
        if (
            operation.status == operation.Status.IN_PROGRESS
            and operation.stage == "Starting"
            and operation.created_at < timezone.now() - timedelta(minutes=5)
        ):
            operation.status = operation.Status.FAILED
            operation.stage = "Failed"
            operation.failure_detail = (
                "The background worker stopped before processing began. "
                "Retry the bypass operation."
            )
            operation.completed_at = timezone.now()
            operation.save(
                update_fields=["status", "stage", "failure_detail", "completed_at"]
            )
        if operation.status == operation.Status.PENDING:
            import threading

            threading.Thread(
                target=run_bypass_job,
                args=(str(operation.pk),),
                daemon=True,
                name=f"grading-bypass-resume-{operation.pk}",
            ).start()
        return Response({
            "job_id": str(operation.pk),
            "status": operation.status,
            "stage": operation.stage,
            "students_processed": operation.students_processed,
            "total_students": operation.total_students,
            "progress_percent": operation.progress_percent,
            "failure_detail": operation.failure_detail or None,
            "deleted_records": operation.deleted_records if operation.status == operation.Status.COMPLETED else None,
            "financial_adjustments": operation.financial_adjustments if operation.status == operation.Status.COMPLETED else None,
            "year_end_records_updated": operation.year_end_records_updated if operation.status == operation.Status.COMPLETED else None,
        })

    @action(
        detail=True,
        methods=["post"],
        url_path="grading-bypass-outcome-summary",
        permission_classes=[IsAuthenticated, IsSuperAdmin],
    )
    def grading_bypass_outcome_summary(self, request, *args, **kwargs):
        validate_tenant_is_in_public_schema()
        academic_year_id = request.data.get("academic_year")
        if not academic_year_id:
            raise ValidationError({"academic_year": "An academic year is required."})
        return Response(build_grading_bypass_outcome_summary(
            tenant=self.get_object(),
            academic_year_id=academic_year_id,
            year_end_outcomes=request.data.get("year_end_outcomes"),
            default_year_end_outcome=request.data.get("default_year_end_outcome"),
            next_grade_level_overrides=request.data.get("next_grade_level_overrides"),
        ))

    @action(
        detail=True,
        methods=["get"],
        url_path="stats",
        permission_classes=[IsAuthenticated, IsSuperAdmin],
    )
    def stats(self, request, *args, **kwargs):
        """Return aggregate stats for a tenant for the admin tenant detail page.

        Endpoint:
        - GET /api/v1/tenants/{schema_name}/stats/?academic_year=<id>

        If `academic_year` is omitted, the tenant's current academic year is
        used (falling back to the most recent by start_date). Enrollment
        figures are scoped to the chosen academic year; user/staff counts
        are tenant-wide.
        """
        validate_tenant_is_in_public_schema()
        tenant = self.get_object()

        from tenant_users.permissions.models import UserTenantPermissions

        with schema_context(tenant.schema_name):
            from academics.models import AcademicYear
            from staff.models import Staff
            from students.models import Student
            from students.models.enrollment import Enrollment
            from students.models.guardian import StudentGuardian

            academic_year_param = (request.query_params.get("academic_year") or "").strip()
            academic_year = None
            if academic_year_param:
                ay_qs = AcademicYear.objects.all()
                if academic_year_param.isdigit():
                    academic_year = ay_qs.filter(pk=int(academic_year_param)).first()
                if academic_year is None:
                    academic_year = ay_qs.filter(name__iexact=academic_year_param).first()

            if academic_year is None:
                academic_year = AcademicYear.get_current_academic_year() or (
                    AcademicYear.objects.order_by("-start_date").first()
                )

            enrollment_qs = Enrollment.objects.all()
            if academic_year is not None:
                enrollment_qs = enrollment_qs.filter(academic_year=academic_year)

            enrolled_students_count = enrollment_qs.values("student_id").distinct().count()

            total_students = Student.objects.count()
            total_staff = Staff.objects.count()
            total_guardians = StudentGuardian.objects.count()

            # `is_staff` / `is_superuser` are per-tenant flags that live on
            # UserTenantPermissions (inside this tenant schema), not on the
            # public User model — filtering User by them would raise a
            # FieldError because they're properties, not real columns.
            permissions_qs = UserTenantPermissions.objects.all()
            permission_user_ids = list(
                permissions_qs.values_list("profile_id", flat=True).distinct()
            )
            staff_users = permissions_qs.filter(is_staff=True).count()
            superuser_users = permissions_qs.filter(is_superuser=True).count()

        with schema_context("public"):
            User = get_user_model()
            users_qs = User.objects.filter(pk__in=permission_user_ids)
            total_users = users_qs.count()
            active_users = users_qs.filter(is_active=True).count()

        return Response(
            {
                "tenant": {
                    "schema_name": tenant.schema_name,
                    "name": tenant.name,
                    "status": tenant.status,
                    "active": tenant.active,
                },
                "academic_year": {
                    "id": getattr(academic_year, "id", None),
                    "name": getattr(academic_year, "name", None),
                    "start_date": getattr(academic_year, "start_date", None),
                    "end_date": getattr(academic_year, "end_date", None),
                    "current": getattr(academic_year, "current", None),
                } if academic_year is not None else None,
                "students": {
                    "enrolled": enrolled_students_count,
                    "total": total_students,
                },
                "staff": {"total": total_staff},
                "guardians": {"total": total_guardians},
                "users": {
                    "total": total_users,
                    "active": active_users,
                    "staff": staff_users,
                    "superuser": superuser_users,
                },
            },
            status=status.HTTP_200_OK,
        )


@api_view(["GET"])
@authentication_classes([])  # Disable authentication - this is a public endpoint
@permission_classes([AllowAny])
def search_tenant_info(request):
    """
    Search for tenant information by email, phone, username, or id_number.

    Public endpoint - no authentication or tenant header required.
    Searches across User (public schema), Student and Staff (tenant schemas).
    Returns all matching records since email and phone_number are not unique.

    Query Parameters:
    - email: Email address to search for
    - phone: Phone number to search for
    - username: Username to search for
    - id_number: ID number to search for

    At least one parameter is required.

    Returns:
    List of matching records with the following structure:
    {
        "user_type": "user|student|staff",
        "tenant": {tenant info} (schema_name: "admin" for users, specific tenant for students/staff),
        "data": {user/student/staff data}
    }
    """
    return Response(
        {
            "detail": (
                "This endpoint has been retired. Use the verified account-discovery "
                "flow or the public school directory."
            )
        },
        status=status.HTTP_410_GONE,
    )

    # Kept temporarily below for migration history; it is intentionally unreachable.
    from django.db.models import Q
    from django_tenants.utils import get_public_schema_name

    email = request.query_params.get("email")
    phone = request.query_params.get("phone")
    username = request.query_params.get("username")
    id_number = request.query_params.get("id_number")

    # Validate that at least one search parameter is provided
    if not any([email, phone, username, id_number]):
        return Response(
            {
                "error": "At least one search parameter (email, phone, username, or id_number) is required"
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    results = []

    # Ensure we're operating from the public schema context regardless of any tenant header
    with schema_context(get_public_schema_name()):
        # Get public tenant info for user results (for consistency with student/staff structure)
        # Display as "admin" schema for better clarity
        try:
            public_tenant = Tenant.objects.get(schema_name=get_public_schema_name())
            public_tenant_info = {
                "id": str(public_tenant.id),
                "schema_name": "admin",  # Display as "admin" instead of "public" for clarity
                "name": public_tenant.name,
                "short_name": public_tenant.short_name,
                "id_number": getattr(public_tenant, "id_number", None),
                "phone": getattr(public_tenant, "phone", None),
                "email": getattr(public_tenant, "email", None),
                "website": getattr(public_tenant, "website", None),
                "address": getattr(public_tenant, "address", None),
                "city": getattr(public_tenant, "city", None),
                "state": getattr(public_tenant, "state", None),
                "country": getattr(public_tenant, "country", None),
                "postal_code": getattr(public_tenant, "postal_code", None),
                "status": getattr(public_tenant, "status", None),
                "active": getattr(public_tenant, "active", None),
                "logo": public_tenant.logo.url if getattr(public_tenant, "logo", None) else None,
            }
        except Tenant.DoesNotExist:
            public_tenant_info = {
                "id": None,
                "schema_name": "admin",  # Display as "admin" for user-facing consistency
                "name": "Admin",
                "short_name": "Admin",
                "id_number": None,
                "phone": None,
                "email": None,
                "website": None,
                "address": None,
                "city": None,
                "state": None,
                "country": None,
                "postal_code": None,
                "status": "active",
                "active": True,
                "logo": None,
            }

        # Get all active tenants (optimized query)
        tenants = (
            Tenant.objects.exclude(schema_name=get_public_schema_name())
            .filter(active=True)
            .exclude(status="deleted", active=False)
            .only(
                "id",
                "id_number",
                "schema_name",
                "name",
                "short_name",
                "phone",
                "email",
                "website",
                "address",
                "city",
                "state",
                "country",
                "postal_code",
                "status",
                "active",
                "logo",
            )
        )

        # Search in User model (public schema) - Users don't have phone field
        if email or username or id_number:
            # Build Q object for OR conditions
            user_filters = Q()
            if email:
                user_filters |= Q(email__iexact=email)
            if username:
                user_filters |= Q(username__iexact=username)
            if id_number:
                user_filters |= Q(id_number=id_number)

            # Apply filters and select only needed fields
            users = User.objects.filter(user_filters).only(
                "id",
                "id_number",
                "email",
                "first_name",
                "last_name",
                "username",
                "account_type",
                "is_active",
            )

            from users.tenant_access import is_global_superadmin

            for user in users:
                tenant_infos = []
                is_platform_superadmin = is_global_superadmin(user)

                if is_platform_superadmin:
                    tenant_infos.append(public_tenant_info)

                if is_platform_superadmin:
                    for tenant in tenants:
                        tenant_infos.append(
                            {
                                "id": str(tenant.id),
                                "schema_name": tenant.schema_name,
                                "name": tenant.name,
                                "short_name": tenant.short_name,
                                "id_number": getattr(tenant, "id_number", None),
                                "phone": getattr(tenant, "phone", None),
                                "email": getattr(tenant, "email", None),
                                "website": getattr(tenant, "website", None),
                                "address": getattr(tenant, "address", None),
                                "city": getattr(tenant, "city", None),
                                "state": getattr(tenant, "state", None),
                                "country": getattr(tenant, "country", None),
                                "postal_code": getattr(tenant, "postal_code", None),
                                "status": getattr(tenant, "status", None),
                                "active": getattr(tenant, "active", None),
                                "logo": tenant.logo.url if getattr(tenant, "logo", None) else None,
                            }
                        )
                else:
                    # Include tenant workspaces where this user has tenant permissions.
                    try:
                        from tenant_users.permissions.models import UserTenantPermissions

                        for tenant in tenants:
                            with schema_context(tenant.schema_name):
                                if UserTenantPermissions.objects.filter(
                                    profile_id=user.id
                                ).exists():
                                    tenant_infos.append(
                                        {
                                            "id": str(tenant.id),
                                            "schema_name": tenant.schema_name,
                                            "name": tenant.name,
                                            "short_name": tenant.short_name,
                                            "id_number": getattr(tenant, "id_number", None),
                                            "phone": getattr(tenant, "phone", None),
                                            "email": getattr(tenant, "email", None),
                                            "website": getattr(tenant, "website", None),
                                            "address": getattr(tenant, "address", None),
                                            "city": getattr(tenant, "city", None),
                                            "state": getattr(tenant, "state", None),
                                            "country": getattr(tenant, "country", None),
                                            "postal_code": getattr(tenant, "postal_code", None),
                                            "status": getattr(tenant, "status", None),
                                            "active": getattr(tenant, "active", None),
                                            "logo": tenant.logo.url if getattr(tenant, "logo", None) else None,
                                        }
                                    )
                    except Exception:
                        if not tenant_infos:
                            tenant_infos.append(public_tenant_info)

                if not tenant_infos:
                    tenant_infos.append(public_tenant_info)

                for tenant_info in tenant_infos:
                    results.append(
                        {
                            "user_type": "user",
                            "tenant": tenant_info,
                            "data": {
                                "id": str(user.id),
                                "id_number": user.id_number,
                                "email": user.email,
                                "first_name": user.first_name,
                                "last_name": user.last_name,
                                "full_name": user.get_full_name(),
                                "username": user.username,
                                "account_type": user.account_type,
                                "is_active": user.is_active,
                            },
                        }
                    )

        # Search in each tenant's schema
        for tenant in tenants:
            with schema_context(tenant.schema_name):
                tenant_info = {
                    "id": str(tenant.id),
                    "schema_name": tenant.schema_name,
                    "name": tenant.name,
                    "short_name": tenant.short_name,
                    "id_number": getattr(tenant, "id_number", None),
                    "phone": getattr(tenant, "phone", None),
                    "email": getattr(tenant, "email", None),
                    "website": getattr(tenant, "website", None),
                    "address": getattr(tenant, "address", None),
                    "city": getattr(tenant, "city", None),
                    "state": getattr(tenant, "state", None),
                    "country": getattr(tenant, "country", None),
                    "postal_code": getattr(tenant, "postal_code", None),
                    "status": getattr(tenant, "status", None),
                    "active": getattr(tenant, "active", None),
                    "logo": tenant.logo.url if getattr(tenant, "logo", None) else None,
                }

                # Build Q object for Student/Staff filters (supports OR logic)
                filters = Q()
                if email:
                    filters |= Q(email__iexact=email)
                if phone:
                    filters |= Q(phone_number__icontains=phone)
                if id_number:
                    filters |= Q(id_number=id_number)

                # Search Students with optimized query
                students = (
                    Student.objects.filter(filters)
                    .select_related("grade_level")
                    .only(
                        "id",
                        "id_number",
                        "email",
                        "phone_number",
                        "first_name",
                        "middle_name",
                        "last_name",
                        "gender",
                        "status",
                        "grade_level",
                    )
                )

                for student in students:
                    results.append(
                        {
                            "user_type": "student",
                            "tenant": tenant_info,
                            "data": {
                                "id": str(student.id),
                                "id_number": student.id_number,
                                "email": student.email,
                                "phone_number": student.phone_number,
                                "first_name": student.first_name,
                                "middle_name": student.middle_name,
                                "last_name": student.last_name,
                                "full_name": student.get_full_name(),
                                "gender": student.gender,
                                "status": student.status,
                                "grade_level": student.grade_level.name
                                if student.grade_level
                                else None,
                            },
                        }
                    )

                # Search Staff with optimized query
                staff_members = (
                    Staff.objects.filter(filters)
                    .select_related("position")
                    .only(
                        "id",
                        "id_number",
                        "email",
                        "phone_number",
                        "first_name",
                        "middle_name",
                        "last_name",
                        "gender",
                        "status",
                        "position",
                        "is_teacher",
                    )
                )

                for staff_member in staff_members:
                    results.append(
                        {
                            "user_type": "staff",
                            "tenant": tenant_info,
                            "data": {
                                "id": str(staff_member.id),
                                "id_number": staff_member.id_number,
                                "email": staff_member.email,
                                "phone_number": staff_member.phone_number,
                                "first_name": staff_member.first_name,
                                "middle_name": staff_member.middle_name,
                                "last_name": staff_member.last_name,
                                "full_name": staff_member.get_full_name(),
                                "gender": staff_member.gender,
                                "status": staff_member.status,
                                "position": staff_member.position.title
                                if staff_member.position
                                else None,
                                "is_teacher": staff_member.is_teacher,
                            },
                        }
                    )

    # Deduplicate results by (id_number + workspace)
    # Priority: student > staff > user (prefer actual records over user accounts)
    # This ensures parents using shared emails see unique workspace entries
    unique_results = {}
    priority_order = {"student": 3, "staff": 2, "user": 1}

    for result in results:
        result_id_number = result["data"].get("id_number")
        result_workspace = result.get("tenant", {}).get("schema_name")
        result_user_type = result["user_type"]

        # Skip if no id_number (shouldn't happen, but be safe)
        if not result_id_number or not result_workspace:
            continue

        unique_key = f"{result_id_number}:{result_workspace}"

        # If this id_number hasn't been seen, add it
        if unique_key not in unique_results:
            unique_results[unique_key] = result
        else:
            # If already seen, keep the one with higher priority
            existing_priority = priority_order.get(
                unique_results[unique_key]["user_type"], 0
            )
            current_priority = priority_order.get(result_user_type, 0)

            if current_priority > existing_priority:
                unique_results[unique_key] = result

    # Convert unique results back to list
    deduplicated_results = list(unique_results.values())

    # Serialize the deduplicated results
    serializer = TenantInfoSearchResultSerializer(deduplicated_results, many=True)

    return Response(
        {
            "count": len(deduplicated_results),
            "total_matches": len(results),  # Original count before deduplication
            "search_params": {
                "email": email,
                "phone": phone,
                "username": username,
                "id_number": id_number,
            },
            "results": serializer.data,
        },
        status=status.HTTP_200_OK,
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def invalidate_cache(request):
    """
    Invalidate cache entries for a specific data type.

    Expected payload:
    {
        "data_type": "theme|branding|organization|schools|all"
    }
    """
    data_type = request.data.get("data_type", "all")

    # Define cache key patterns for different data types
    cache_patterns = {
        "theme": "theme_*",
        "branding": "branding_*",
        "organization": "org_*",
        "schools": "school_*",
        "all": "*",
    }

    pattern = cache_patterns.get(data_type, "all")

    if pattern == "*":
        # Clear all cache
        cache.clear()
        message = "All cache cleared"
    else:
        # For now, just clear all cache (locmem doesn't support pattern-based deletion)
        # In production with Redis, you could use pattern-based deletion
        cache.clear()
        message = f"Cache cleared for data_type: {data_type}"

    return Response(
        {"status": "success", "message": message, "data_type": data_type},
        status=status.HTTP_200_OK,
    )


# ---------------------------------------------------------------------------
# Signup requests (public create + superadmin management)
# ---------------------------------------------------------------------------

class SignupRequestViewSet(viewsets.ModelViewSet):
    """
    POST /api/v1/signup-requests/ — public marketing form (no auth)
    GET/PATCH /api/v1/signup-requests/{id}/ — superadmin CRM
    GET /api/v1/signup-requests/pending-count/ — pending badge count
    """

    queryset = SignupRequest.objects.all().order_by("-submitted_at")
    lookup_field = "pk"
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        validate_tenant_is_in_public_schema()
        qs = super().get_queryset()
        status_filter = self.request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        search = (self.request.query_params.get("search") or "").strip()
        if search:
            qs = qs.filter(
                Q(school_name__icontains=search)
                | Q(email__icontains=search)
                | Q(first_name__icontains=search)
                | Q(last_name__icontains=search)
            )
        return qs

    def get_serializer_class(self):
        from core.serializers import SignupRequestAdminSerializer, SignupRequestCreateSerializer

        if self.action in ("list", "retrieve", "partial_update"):
            return SignupRequestAdminSerializer
        return SignupRequestCreateSerializer

    def get_permissions(self):
        if self.action == "create":
            return [AllowAny()]
        return [IsAuthenticated(), IsSuperAdmin()]

    def get_authenticators(self):
        if getattr(self, "action", None) == "create":
            return []
        return super().get_authenticators()

    def create(self, request, *args, **kwargs):
        from core.serializers import SignupRequestCreateSerializer
        from common.email_service import (
            send_signup_request_admin_notification_email,
            send_signup_request_confirmation_email,
        )

        serializer = SignupRequestCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        instance = serializer.save()

        try:
            send_signup_request_confirmation_email(instance)
            send_signup_request_admin_notification_email(instance)
        except Exception:
            pass

        return Response(
            {"detail": "Request submitted successfully.", "id": instance.pk},
            status=status.HTTP_201_CREATED,
        )

    @action(detail=False, methods=["get"], url_path="pending-count")
    def pending_count(self, request):
        validate_tenant_is_in_public_schema()
        count = SignupRequest.objects.filter(status=SignupRequest.STATUS_PENDING).count()
        return Response({"count": count})

    @action(detail=True, methods=["post"], url_path="send-owner-activation")
    def send_owner_activation(self, request, pk=None):
        validate_tenant_is_in_public_schema()
        signup_request = self.get_object()
        tenant = get_signup_request_linked_tenant(signup_request)
        if not tenant:
            return Response({"detail": "Workspace has not been created yet."}, status=status.HTTP_400_BAD_REQUEST)

        owner = get_signup_request_owner(tenant, signup_request)
        if not owner or not owner.email:
            return Response({"detail": "No tenant owner email is available for this workspace."}, status=status.HTTP_400_BAD_REQUEST)

        now = timezone.now()
        TenantOwnerActivationCode.objects.filter(
            tenant=tenant,
            user=owner,
            purpose=TenantOwnerActivationCode.PURPOSE_TENANT_OWNER_ACTIVATION,
            used_at__isnull=True,
        ).update(used_at=now)

        code = _generate_activation_code()
        expires_at = now + timedelta(hours=max(1, int(getattr(settings, "TENANT_OWNER_ACTIVATION_CODE_HOURS", 24))))

        activation_code = TenantOwnerActivationCode.objects.create(
            tenant=tenant,
            user=owner,
            signup_request=signup_request,
            issued_by=request.user if getattr(request.user, "is_authenticated", False) else None,
            code_hash=make_password(code),
            delivered_to=owner.email,
            expires_at=expires_at,
        )

        activate_url = build_activation_url(tenant.schema_name)
        sent = send_tenant_owner_activation_email(
            user=owner,
            tenant=tenant,
            activation_code=code,
            activate_url=activate_url,
        )
        if not sent:
            activation_code.delete()
            return Response({"detail": "Workspace email could not be sent."}, status=status.HTTP_502_BAD_GATEWAY)

        if signup_request.status == SignupRequest.STATUS_PENDING:
            signup_request.status = SignupRequest.STATUS_CONTACTED
            signup_request.save(update_fields=["status"])

        return Response(
            {
                "detail": "Owner activation email sent successfully.",
                "owner_email": owner.email,
                "workspace": tenant.schema_name,
                "expires_at": expires_at,
            }
        )


class ContactInquiryView(APIView):
    """
    POST /api/v1/contact-inquiries/ — public marketing contact form (no auth).
    Sends notification + receipt emails; does not persist to the database.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        from core.serializers import ContactInquirySerializer
        from common.email_service import send_contact_inquiry_emails

        validate_tenant_is_in_public_schema()
        serializer = ContactInquirySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            send_contact_inquiry_emails(
                name=data["name"],
                email=data["email"],
                school_name=data.get("school_name") or "",
                topic=data["topic"],
                message=data["message"],
            )
        except Exception:
            pass

        return Response({"detail": "Message sent successfully."}, status=status.HTTP_201_CREATED)
