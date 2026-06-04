from datetime import datetime

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from students.access_policies import StudentAccessPolicy
from students.services.enrollment_lifecycle import EnrollmentLifecycleError
from students.services.enrollment_lifecycle_bulk import (
    VALID_BULK_ACTIONS,
    apply_bulk,
    list_promoted_students,
    preview_bulk,
    undo_promotions,
)
from students.services.promotion_rules import get_promotion_rules
from users.access_policies.access import BaseSchoolAccessPolicy


class EnrollmentLifecycleBulkAccessPolicy(StudentAccessPolicy):
    """Bulk lifecycle endpoints (registrar/admin enforced in view)."""


def _require_registrar_or_admin(request, view) -> Response | None:
    policy = BaseSchoolAccessPolicy()
    if policy.is_role_in(request, view, "post", "admin,registrar"):
        return None
    return Response(
        {
            "detail": "Only administrators and registrars can run bulk enrollment lifecycle actions."
        },
        status=status.HTTP_403_FORBIDDEN,
    )


def _parse_optional_date(value, field_name: str):
    if value is None or value == "":
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError as exc:
        raise EnrollmentLifecycleError(
            f"{field_name} must be YYYY-MM-DD."
        ) from exc


def _parse_body(request) -> dict:
    data = request.data if isinstance(request.data, dict) else {}
    selection = data.get("selection") or {}
    if not isinstance(selection, dict):
        selection = {}
    return {
        "action": (data.get("action") or "").strip(),
        "outcome": (data.get("outcome") or "").strip() or None,
        "selection_mode": (selection.get("mode") or "ids").strip(),
        "student_ids": selection.get("student_ids") or [],
        "grade_level": (selection.get("grade_level") or "").strip() or None,
        "section": (selection.get("section") or "").strip() or None,
        "search": (selection.get("search") or "").strip() or None,
        "expected_eligible_count": data.get("expected_eligible_count"),
        "confirm_phrase": data.get("confirm_phrase"),
        "graduation_date": data.get("graduation_date"),
        "transfer_date": data.get("transfer_date"),
        "transfer_reason": data.get("transfer_reason"),
    }


class EnrollmentLifecycleRulesView(APIView):
    """GET /students/enrollment-lifecycle/rules/"""

    permission_classes = [EnrollmentLifecycleBulkAccessPolicy]

    def get(self, request):
        policy = BaseSchoolAccessPolicy()
        if not policy.is_role_in(request, self, "get", "admin,registrar"):
            return Response(
                {"detail": "Only administrators and registrars can view promotion rules."},
                status=status.HTTP_403_FORBIDDEN,
            )
        return Response(get_promotion_rules(), status=status.HTTP_200_OK)


class EnrollmentLifecycleBulkPreviewView(APIView):
    """
    POST /students/enrollment-lifecycle/preview/
    Preview who is eligible for a bulk lifecycle action.
    """

    permission_classes = [EnrollmentLifecycleBulkAccessPolicy]

    def post(self, request):
        denied = _require_registrar_or_admin(request, self)
        if denied:
            return denied

        try:
            body = _parse_body(request)
            action = body["action"]
            if action not in VALID_BULK_ACTIONS:
                return Response(
                    {
                        "detail": "action must be one of: "
                        + ", ".join(sorted(VALID_BULK_ACTIONS))
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if body["selection_mode"] not in ("ids", "filters"):
                return Response(
                    {"detail": "selection.mode must be 'ids' or 'filters'."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            result = preview_bulk(
                action=action,
                selection_mode=body["selection_mode"],
                student_ids=body["student_ids"],
                grade_level=body["grade_level"],
                section=body["section"],
                search=body["search"],
                outcome=body["outcome"],
            )
            return Response(result, status=status.HTTP_200_OK)
        except EnrollmentLifecycleError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


class EnrollmentLifecycleBulkApplyView(APIView):
    """
    POST /students/enrollment-lifecycle/apply/
    Apply a bulk lifecycle action after preview.
    """

    permission_classes = [EnrollmentLifecycleBulkAccessPolicy]

    def post(self, request):
        denied = _require_registrar_or_admin(request, self)
        if denied:
            return denied

        try:
            body = _parse_body(request)
            action = body["action"]
            if action not in VALID_BULK_ACTIONS:
                return Response(
                    {
                        "detail": "action must be one of: "
                        + ", ".join(sorted(VALID_BULK_ACTIONS))
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            expected = body["expected_eligible_count"]
            if expected is None:
                return Response(
                    {"detail": "expected_eligible_count is required."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            try:
                expected_int = int(expected)
            except (TypeError, ValueError) as exc:
                raise EnrollmentLifecycleError(
                    "expected_eligible_count must be an integer."
                ) from exc

            graduation_date = _parse_optional_date(
                body.get("graduation_date"), "graduation_date"
            )
            transfer_date = _parse_optional_date(
                body.get("transfer_date"), "transfer_date"
            )

            result = apply_bulk(
                action=action,
                selection_mode=body["selection_mode"],
                student_ids=body["student_ids"],
                grade_level=body["grade_level"],
                section=body["section"],
                search=body["search"],
                outcome=body["outcome"],
                expected_eligible_count=expected_int,
                confirm_phrase=body.get("confirm_phrase") or "",
                graduation_date=graduation_date,
                transfer_date=transfer_date,
                transfer_reason=body.get("transfer_reason"),
            )
            return Response(result, status=status.HTTP_200_OK)
        except EnrollmentLifecycleError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


class EnrollmentLifecyclePromotedListView(APIView):
    """
    GET /students/enrollment-lifecycle/promoted/?grade_level=&section=
    Students in the class who completed year-end with outcome=promoted.
    """

    permission_classes = [EnrollmentLifecycleBulkAccessPolicy]

    def get(self, request):
        denied = _require_registrar_or_admin(request, self)
        if denied:
            return denied

        grade_level = (request.query_params.get("grade_level") or "").strip()
        section = (request.query_params.get("section") or "").strip()
        try:
            result = list_promoted_students(
                grade_level=grade_level,
                section=section,
            )
            return Response(result, status=status.HTTP_200_OK)
        except EnrollmentLifecycleError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


class EnrollmentLifecycleUndoView(APIView):
    """
    POST /students/enrollment-lifecycle/undo/
    Body: { student_ids: string[] }
    """

    permission_classes = [EnrollmentLifecycleBulkAccessPolicy]

    def post(self, request):
        denied = _require_registrar_or_admin(request, self)
        if denied:
            return denied

        data = request.data if isinstance(request.data, dict) else {}
        student_ids = data.get("student_ids") or []
        if not isinstance(student_ids, list):
            return Response(
                {"detail": "student_ids must be a list."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            result = undo_promotions(student_ids=student_ids)
            return Response(result, status=status.HTTP_200_OK)
        except EnrollmentLifecycleError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
