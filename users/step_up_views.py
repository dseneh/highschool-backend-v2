"""Authenticated email step-up MFA challenge endpoints."""

from django.conf import settings
from django.db import connection, transaction
from django_tenants.utils import get_public_schema_name, schema_context
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from common.audit_utils import log_auth_event
from users.mfa import (
    get_challenge_for_update,
    issue_challenge,
    mask_email,
    verify_code,
)
from users.step_up import (
    ACTION_TO_SETTING,
    is_step_up_required,
    issue_step_up_proof,
    normalize_context,
)


class StepUpMFAStartView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        action = str(request.data.get("action", "")).strip()
        context = normalize_context(request.data.get("context", ""))
        if action not in ACTION_TO_SETTING:
            return Response({"detail": "Unsupported sensitive action."}, status=400)
        if not is_step_up_required(action):
            return Response(
                {"detail": "Step-up verification is not enabled for this action."},
                status=400,
            )
        if not request.user.email:
            return Response(
                {"detail": "A verified email address is required."}, status=403
            )
        tenant_schema = connection.schema_name
        issued = issue_challenge(
            request.user,
            tenant_schema,
            purpose="step_up",
            action=action,
            context=context,
        )
        if issued is None:
            return Response(
                {"detail": "Unable to send a verification code."}, status=503
            )
        _challenge, raw_token = issued
        log_auth_event(
            request,
            request.user,
            "step_up_challenge_issued",
            details={"action": action, "context": context},
        )
        return Response(
            {
                "challenge_token": raw_token,
                "expires_in": int(settings.EMAIL_MFA_CODE_TTL_SECONDS),
                "delivery": {
                    "method": "email",
                    "destination": mask_email(request.user.email),
                },
            },
            status=202,
        )


class StepUpMFAVerifyView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        raw_token = str(request.data.get("challenge_token", ""))
        code = str(request.data.get("code", ""))
        if (
            not raw_token
            or len(raw_token) > 256
            or len(code) != 6
            or not code.isdigit()
        ):
            return Response(
                {"detail": "Invalid or expired verification code."}, status=400
            )
        tenant_schema = connection.schema_name
        with schema_context(get_public_schema_name()), transaction.atomic():
            challenge = get_challenge_for_update(
                raw_token, tenant_schema, purpose="step_up"
            )
            if (
                not challenge
                or challenge.user_id != request.user.pk
                or not verify_code(challenge, code)
            ):
                log_auth_event(request, request.user, "step_up_verification_failed")
                return Response(
                    {"detail": "Invalid or expired verification code."}, status=400
                )
            proof_token = issue_step_up_proof(
                user=request.user,
                tenant_schema=tenant_schema,
                action=challenge.action,
                context=challenge.context,
            )
            action = challenge.action
            context = challenge.context
        log_auth_event(
            request,
            request.user,
            "step_up_verification_success",
            details={"action": action, "context": context},
        )
        return Response(
            {
                "step_up_token": proof_token,
                "action": action,
                "context": context,
                "expires_in": 600,
            }
        )
