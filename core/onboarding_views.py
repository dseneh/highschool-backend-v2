"""
Onboarding API views.

Endpoints:
  GET  /api/v1/tenants/{schema_name}/onboarding/
       Returns current onboarding plan, step metadata, and completion status.

  PATCH /api/v1/tenants/{schema_name}/onboarding/
       Save a single step payload (partial update). Transitions status to in_progress.

  POST /api/v1/tenants/{schema_name}/onboarding/apply/
       Execute the full provisioning plan and transition status to active on success.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from django.db import connection
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework import status

from core.models import Tenant
from common.permissions import IsAdminOrSuperAdmin
from defaults.services import build_initial_plan, apply_onboarding_plan, get_completion_status, sync_plan_with_latest_template

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


def _get_tenant(schema_name: str) -> Tenant | None:
    try:
        return Tenant.objects.get(schema_name=schema_name)
    except Tenant.DoesNotExist:
        return None


# ---------------------------------------------------------------------------
# Permission helper: allow tenant admins or platform superadmins
# ---------------------------------------------------------------------------

class OnboardingPermission:
    """Allow if user is superadmin OR if user has admin role in the tenant."""

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if getattr(user, "is_superuser", False):
            return True
        role = str(getattr(user, "role", "") or "").lower()
        return role in ("admin", "superadmin")


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_onboarding(request: Request, schema_name: str) -> Response:
    """
    Return the onboarding plan for this tenant workspace, generating a starter
    plan on first access if none exists yet.
    """
    tenant = _get_tenant(schema_name)
    if not tenant:
        return Response({"detail": "Tenant not found."}, status=status.HTTP_404_NOT_FOUND)

    plan = tenant.onboarding_plan
    if not plan:
        # Generate and persist the initial plan
        plan = build_initial_plan(tenant)
        tenant.onboarding_plan = plan
        if not tenant.onboarding_started_at:
            tenant.onboarding_started_at = datetime.now(tz=timezone.utc)
        tenant.save(update_fields=["onboarding_plan", "onboarding_started_at"])
    else:
        plan, changed = sync_plan_with_latest_template(tenant, plan)
        if changed:
            tenant.onboarding_plan = plan
            tenant.save(update_fields=["onboarding_plan"])

    completion = get_completion_status(plan)

    return Response(
        {
            "status": tenant.status,
            "onboarding_started_at": tenant.onboarding_started_at,
            "onboarding_completed_at": tenant.onboarding_completed_at,
            "plan": plan,
            "completion": completion,
        }
    )


@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def save_onboarding_step(request: Request, schema_name: str) -> Response:
    """
    Save/update a single step payload.

    Request body:
        {
            "step_key": "academic_calendar",
            "payload": { ... },
            "mark_completed": true   // optional; defaults to true
        }
    """
    tenant = _get_tenant(schema_name)
    if not tenant:
        return Response({"detail": "Tenant not found."}, status=status.HTTP_404_NOT_FOUND)

    step_key = request.data.get("step_key")
    payload = request.data.get("payload", {})
    mark_completed = request.data.get("mark_completed", True)

    if not step_key:
        return Response({"detail": "step_key is required."}, status=status.HTTP_400_BAD_REQUEST)

    plan = tenant.onboarding_plan or {}

    # Initialise plan if empty
    if not plan:
        plan = build_initial_plan(tenant)
    else:
        plan, changed = sync_plan_with_latest_template(tenant, plan)
        if changed:
            tenant.onboarding_plan = plan

    # Ensure steps dict exists
    if "steps" not in plan:
        plan["steps"] = {}

    # Update the step entry
    step_entry = plan["steps"].get(step_key, {"status": "pending", "payload": {}, "apply_result": None})
    step_entry["payload"] = payload
    step_entry["saved_at"] = _now_iso()
    if mark_completed:
        step_entry["status"] = "completed"
    else:
        step_entry["status"] = "in_progress"
    plan["steps"][step_key] = step_entry

    # Advance current_step pointer to the next pending step
    step_order = plan.get("step_order", list(plan["steps"].keys()))
    try:
        step_idx = step_order.index(step_key)
        next_pending = next(
            (k for k in step_order[step_idx + 1:] if plan["steps"].get(k, {}).get("status") != "completed"),
            None,
        )
        if next_pending:
            plan["current_step"] = next_pending
    except (ValueError, StopIteration):
        pass

    tenant.onboarding_plan = plan

    # Transition tenant status to in_progress on first save
    fields_to_save = ["onboarding_plan"]
    if tenant.status == Tenant.STATUS_PENDING:
        tenant.status = Tenant.STATUS_IN_PROGRESS
        if not tenant.onboarding_started_at:
            tenant.onboarding_started_at = datetime.now(tz=timezone.utc)
        fields_to_save += ["status", "onboarding_started_at"]

    tenant.save(update_fields=fields_to_save)

    return Response(
        {
            "step_key": step_key,
            "step_status": step_entry["status"],
            "current_step": plan.get("current_step"),
            "completion": get_completion_status(plan),
        }
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def apply_onboarding(request: Request, schema_name: str) -> Response:
    """
    Execute the saved onboarding plan to provision the workspace.

    On success transitions tenant.status to 'active'.
    On failure returns a 422 with step-level error details.
    """
    tenant = _get_tenant(schema_name)
    if not tenant:
        return Response({"detail": "Tenant not found."}, status=status.HTTP_404_NOT_FOUND)

    # Permission check
    user = request.user
    if not user.is_superuser:
        role = str(getattr(user, "role", "") or "").lower()
        if role not in ("admin", "superadmin"):
            return Response({"detail": "You don't have permission to provision this workspace."}, status=status.HTTP_403_FORBIDDEN)

    plan = tenant.onboarding_plan
    if not plan:
        return Response({"detail": "No onboarding plan found. Start onboarding first."}, status=status.HTTP_400_BAD_REQUEST)

    plan, changed = sync_plan_with_latest_template(tenant, plan)
    if changed:
        tenant.onboarding_plan = plan
        tenant.save(update_fields=["onboarding_plan"])

    # Validate required steps are completed
    completion = get_completion_status(plan)
    if not completion["required_done"]:
        missing = [
            k for k in plan.get("required_steps", [])
            if plan.get("steps", {}).get(k, {}).get("status") != "completed"
        ]
        return Response(
            {
                "detail": "Cannot provision workspace — required onboarding steps are incomplete.",
                "missing_steps": missing,
                "completion": completion,
            },
            status=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    # Execute provisioning
    result = apply_onboarding_plan(tenant, user, plan)

    # Persist apply result back to plan
    plan["apply_result"] = result
    plan["completed_at"] = _now_iso()
    tenant.onboarding_plan = plan
    fields_to_save = ["onboarding_plan"]

    if result.get("success"):
        tenant.status = Tenant.STATUS_ACTIVE
        tenant.active = True
        tenant.onboarding_completed_at = datetime.now(tz=timezone.utc)
        fields_to_save += ["status", "active", "onboarding_completed_at"]
        tenant.save(update_fields=fields_to_save)

        return Response(
            {
                "success": True,
                "workspace_status": tenant.status,
                "onboarding_completed_at": tenant.onboarding_completed_at,
                "apply_result": result,
            }
        )
    else:
        tenant.save(update_fields=["onboarding_plan"])
        return Response(
            {
                "success": False,
                "detail": "Workspace provisioning failed. See apply_result for details.",
                "apply_result": result,
            },
            status=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def reset_onboarding(request: Request, schema_name: str) -> Response:
    """
    Admin-only: reset a tenant's onboarding plan so it can restart from scratch.
    Only allowed for superadmins.
    """
    if not request.user.is_superuser:
        return Response({"detail": "Only platform superadmins can reset onboarding."}, status=status.HTTP_403_FORBIDDEN)

    tenant = _get_tenant(schema_name)
    if not tenant:
        return Response({"detail": "Tenant not found."}, status=status.HTTP_404_NOT_FOUND)

    plan = build_initial_plan(tenant)
    tenant.onboarding_plan = plan
    tenant.status = Tenant.STATUS_PENDING
    tenant.onboarding_started_at = None
    tenant.onboarding_completed_at = None
    tenant.save(update_fields=["onboarding_plan", "status", "onboarding_started_at", "onboarding_completed_at"])

    return Response({"success": True, "detail": "Onboarding plan reset.", "status": tenant.status})
