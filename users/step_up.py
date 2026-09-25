"""Tenant-configurable email step-up MFA for sensitive operations."""

import re
import secrets
from datetime import timedelta

from django.db import connection, transaction
from django.utils import timezone
from django_tenants.utils import get_public_schema_name, schema_context
from rest_framework.exceptions import PermissionDenied

from users.mfa import token_digest


ACTION_TO_SETTING = {
    "payroll_approval": "require_mfa_for_payroll_approval",
    "payment_configuration": "require_mfa_for_payment_configuration",
    "bank_account_changes": "require_mfa_for_bank_account_changes",
    "backup_restore": "require_mfa_for_backup_restore",
    "security_settings": "require_mfa_for_security_settings",
    "admin_role_changes": "require_mfa_for_admin_role_changes",
    "mfa_recovery": "require_mfa_for_mfa_recovery",
}

SENSITIVE_FIELD_POLICIES = {
    "bank_account_changes": frozenset(
        {
            "account_number",
            "account_type",
            "currency",
            "ledger_account",
            "opening_balance",
            "opening_balance_date",
            "status",
        }
    ),
    "payment_configuration": frozenset(
        {
            "transfer_in_account",
            "transfer_out_account",
            "salary_expense_account",
            "salary_advance_repayment_ledger_account",
            "payroll_tax_payable_account",
            "payroll_deductions_payable_account",
            "student_refund_account",
            "default_payroll_bank_account",
            "default_expense_bank_account",
        }
    ),
    "admin_role_changes": frozenset({"is_active", "permissions"}),
}

STEP_UP_TTL_SECONDS = 600


SENSITIVE_REQUEST_PATTERNS = (
    ("POST", re.compile(r"^/api/v1/payroll-v2/runs/([^/]+)/approve/$"), "payroll_approval", 1),
    ("POST", re.compile(r"^/api/v1/restore-requests/([^/]+)/(?:execute|retry)/$"), "backup_restore", 1),
    ("POST", re.compile(r"^/api/v1/accounting/bank-accounts/$"), "bank_account_changes", "new"),
    ("DELETE", re.compile(r"^/api/v1/accounting/bank-accounts/([^/]+)/$"), "bank_account_changes", 1),
    ("POST", re.compile(r"^/api/v1/authorization/roles/$"), "admin_role_changes", "new"),
    ("DELETE", re.compile(r"^/api/v1/authorization/roles/([^/]+)/$"), "admin_role_changes", 1),
    ("POST", re.compile(r"^/api/v1/authorization/roles/([^/]+)/(?:clone|permissions)/$"), "admin_role_changes", 1),
    ("PUT", re.compile(r"^/api/v1/authorization/roles/([^/]+)/permissions/$"), "admin_role_changes", 1),
    ("PUT", re.compile(r"^/api/v1/authorization/users/([^/]+)/role/$"), "admin_role_changes", 1),
    ("POST", re.compile(r"^/api/v1/authorization/users/roles/bulk/$"), "admin_role_changes", "bulk"),
)


def normalize_context(value):
    return str(value or "").strip()[:255]


def comparable_value(value):
    """Normalize model and scalar values before change comparison."""
    if hasattr(value, "pk"):
        return value.pk
    if isinstance(value, dict):
        return tuple(
            sorted((key, comparable_value(item)) for key, item in value.items())
        )
    if isinstance(value, (list, tuple)):
        return tuple(comparable_value(item) for item in value)
    return value


def changed_fields(instance, validated_data, *, fields=None):
    """Return submitted fields whose validated value differs from the instance.

    This helper intentionally works from serializer ``validated_data`` so type
    coercion and relationship resolution have already happened.
    """
    candidates = set(validated_data)
    if fields is not None:
        candidates.intersection_update(fields)
    return {
        field
        for field in candidates
        if comparable_value(
            instance.get(field) if isinstance(instance, dict) else getattr(instance, field, None)
        )
        != comparable_value(validated_data[field])
    }


def enforce_step_up_for_sensitive_changes(
    request,
    *,
    action,
    context,
    instance,
    validated_data,
    sensitive_fields=None,
):
    """Enforce step-up only when a submitted sensitive field truly changes."""
    if sensitive_fields is None:
        sensitive_fields = SENSITIVE_FIELD_POLICIES.get(action, ())
    sensitive_changes = changed_fields(
        instance,
        validated_data,
        fields=sensitive_fields,
    )
    if sensitive_changes:
        enforce_step_up(
            request,
            action=action,
            context=context,
            sensitive_fields=sensitive_changes,
        )
    return sensitive_changes


def is_step_up_required(action):
    from settings.models import SecuritySettings

    field = ACTION_TO_SETTING.get(action)
    if not field:
        raise ValueError(f"Unknown step-up action: {action}")
    if connection.schema_name == get_public_schema_name():
        return False
    policy = SecuritySettings.objects.first()
    return bool(policy and getattr(policy, field, False))


def issue_step_up_proof(*, user, tenant_schema, action, context=""):
    from users.models import StepUpAuthorization

    raw_token = secrets.token_urlsafe(32)
    StepUpAuthorization.objects.create(
        user=user,
        tenant_schema=tenant_schema,
        action=action,
        context=normalize_context(context),
        token_hash=token_digest(raw_token),
        expires_at=timezone.now() + timedelta(seconds=STEP_UP_TTL_SECONDS),
    )
    return raw_token


def enforce_step_up(
    request,
    *,
    action,
    context="",
    required=None,
    sensitive_fields=None,
):
    if required is None:
        required = is_step_up_required(action)
    if not required:
        return
    raw_token = str(request.headers.get("X-Step-Up-Token", ""))
    tenant_schema = connection.schema_name
    # Preserve the tenant before switching to the shared schema in the helper.
    from users.models import StepUpAuthorization
    with schema_context(get_public_schema_name()), transaction.atomic():
        proof = StepUpAuthorization.objects.select_for_update().filter(
            token_hash=token_digest(raw_token),
            user_id=request.user.pk,
            tenant_schema=tenant_schema,
            action=action,
            context=normalize_context(context),
            used_at__isnull=True,
            expires_at__gt=timezone.now(),
        ).first()
        if proof:
            proof.used_at = timezone.now()
            proof.save(update_fields=["used_at"])
            return
    raise PermissionDenied(
        detail={
            "detail": "Fresh email verification is required for this action.",
            "error_code": "STEP_UP_MFA_REQUIRED",
            "step_up_action": action,
            "step_up_context": normalize_context(context),
            "sensitive_fields": sorted(sensitive_fields or ()),
        }
    )


def enforce_authenticated_request_step_up(request, user):
    """Enforce configured step-up MFA immediately after authentication.

    Central enforcement prevents clients from bypassing protection by calling a
    sensitive endpoint without using its normal frontend control.
    """
    method = request.method.upper()
    path = request.path if request.path.endswith("/") else f"{request.path}/"
    for expected_method, pattern, action, context_source in SENSITIVE_REQUEST_PATTERNS:
        if method != expected_method:
            continue
        match = pattern.match(path)
        if not match:
            continue
        context = (
            match.group(context_source)
            if isinstance(context_source, int)
            else context_source or ""
        )
        request.user = user
        enforce_step_up(request, action=action, context=context)
        return
