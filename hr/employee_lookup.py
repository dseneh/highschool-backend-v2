"""Read-only, permission-scoped employee prefilling across schools."""
from copy import copy

from django.db import connection
from django_tenants.utils import get_public_schema_name, get_tenant_model, schema_context
from rest_framework import serializers
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from authorization.multiple_roles import selected_assignment
from authorization.runtime import resolve_authorization_context
from users.tenant_access import is_global_superadmin
from .models import Employee


# Never serialize the employee model wholesale: payroll, IDs, roles, and account
# references belong to the source school and must not be copied into a new one.
PROFILE_FIELDS = (
    "first_name", "middle_name", "last_name", "email", "phone_number",
    "date_of_birth", "gender", "place_of_birth", "address", "city", "state",
    "postal_code", "country",
)


class EmployeeLookupInput(serializers.Serializer):
    tenant_id = serializers.UUIDField()
    email = serializers.EmailField(max_length=254)


def candidate_tenants(user):
    current = connection.schema_name
    with schema_context(get_public_schema_name()):
        tenants = get_tenant_model().objects.filter(active=True, status="active", maintenance_mode=False)
        if not is_global_superadmin(user):
            tenants = tenants.filter(pk__in=user.tenants.values_list("pk", flat=True))
        return list(tenants.exclude(schema_name__in=[current, get_public_schema_name()]).order_by("name"))


def can_read_source(user, tenant):
    # One source role (its default assignment), never a union of role grants.
    # Do not carry the destination's assignment UUID into the source schema.
    actor = copy(user)
    platform = is_global_superadmin(user)
    actor.is_platform_superuser = platform
    actor._active_role_selection = "platform" if platform else None
    with schema_context(tenant.schema_name):
        if not platform:
            assignment = selected_assignment(actor)
            if not assignment:
                return False
            actor._active_role_selection = str(assignment.pk)
        return resolve_authorization_context(actor).permission_scope("employees.view") == "all"


def available_sources(user):
    return [{"id": str(tenant.pk), "name": tenant.name}
            for tenant in candidate_tenants(user) if can_read_source(user, tenant)]


def lookup_profile(user, data):
    serializer = EmployeeLookupInput(data=data)
    serializer.is_valid(raise_exception=True)
    values = serializer.validated_data
    tenant = next((item for item in candidate_tenants(user) if item.pk == values["tenant_id"]), None)
    if tenant is None or not can_read_source(user, tenant):
        raise PermissionDenied("You do not have access to employee records in this school.")
    with schema_context(tenant.schema_name):
        matches = list(Employee.objects.filter(email__iexact=values["email"].strip()).values(*PROFILE_FIELDS)[:2])
    if not matches:
        raise NotFound("No employee with this email was found in the selected school.")
    if len(matches) != 1:
        raise ValidationError({"detail": "Multiple employee records use this email. Ask the source school to resolve them."})
    return {"school": {"id": str(tenant.pk), "name": tenant.name}, "employee": matches[0]}
