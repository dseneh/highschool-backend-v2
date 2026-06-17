"""Official transcript access and PDF generation API."""

from __future__ import annotations

from django.db import connection
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from grading.access_policies import GradebookAccessPolicy
from grading.models import TranscriptAccessRequest
from grading.services.transcript_access import (
    approve_or_grant_access,
    build_access_status,
    can_download_transcript,
    create_student_request,
    delete_transcript_request,
    deny_request,
    list_transcript_requests,
    update_transcript_request_status,
)
from grading.tasks.transcript_worker import start_official_transcript_background_task
from reports.tasks import TaskManager
from students.models import Student
from students.services.student_lookup import get_student_by_identifier


def _get_student(student_id: str) -> Student:
    return get_student_by_identifier(student_id)


class OfficialTranscriptAccessStatusView(APIView):
    """GET /grading/students/{student_id}/transcript/access/"""

    permission_classes = [IsAuthenticated]

    def get(self, request, student_id):
        try:
            student = _get_student(student_id)
        except Student.DoesNotExist:
            return Response({"detail": "Student does not exist."}, status=404)

        status_payload = build_access_status(request.user, student)
        if not status_payload["is_admin_viewer"] and not status_payload["is_student_owner"]:
            return Response({"detail": "Not authorized to view transcript access."}, status=403)

        return Response(status_payload)


class OfficialTranscriptRequestView(APIView):
    """POST /grading/students/{student_id}/transcript/request/"""

    permission_classes = [IsAuthenticated]

    def post(self, request, student_id):
        try:
            student = _get_student(student_id)
        except Student.DoesNotExist:
            return Response({"detail": "Student does not exist."}, status=404)

        try:
            access = create_student_request(
                request.user,
                student,
                student_note=(request.data.get("student_note") or "").strip(),
            )
        except PermissionError as exc:
            return Response({"detail": str(exc)}, status=403)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)

        return Response(
            {
                "id": str(access.id),
                "status": access.status,
                "message": "Transcript request submitted. You will be notified when it is reviewed.",
            },
            status=status.HTTP_201_CREATED,
        )


class OfficialTranscriptGrantView(APIView):
    """POST /grading/students/{student_id}/transcript/grant/"""

    permission_classes = [GradebookAccessPolicy]

    def post(self, request, student_id):
        try:
            student = _get_student(student_id)
        except Student.DoesNotExist:
            return Response({"detail": "Student does not exist."}, status=404)

        allow_download = bool(request.data.get("allow_download", False))
        send_email = bool(request.data.get("send_email", False))
        download_days = request.data.get("download_days")
        admin_note = (request.data.get("admin_note") or "").strip()

        try:
            if download_days is not None:
                download_days = max(int(download_days), 1)
        except (TypeError, ValueError):
            return Response({"detail": "download_days must be a positive integer."}, status=400)

        try:
            access = approve_or_grant_access(
                student=student,
                reviewer=request.user,
                allow_download=allow_download,
                send_email=send_email,
                download_days=download_days,
                admin_note=admin_note,
                source=TranscriptAccessRequest.Source.ADMIN_GRANT,
            )
        except PermissionError as exc:
            return Response({"detail": str(exc)}, status=403)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)

        return Response(
            {
                "id": str(access.id),
                "status": access.status,
                "allow_download": access.allow_download,
                "send_email": access.send_email,
                "download_expires_at": access.download_expires_at,
                "message": "Transcript access granted.",
            },
            status=status.HTTP_201_CREATED,
        )


class OfficialTranscriptRequestReviewView(APIView):
    """
    POST /grading/students/{student_id}/transcript/requests/{request_id}/approve/
    POST /grading/students/{student_id}/transcript/requests/{request_id}/deny/
    """

    permission_classes = [GradebookAccessPolicy]

    def post(self, request, student_id, request_id, action):
        try:
            student = _get_student(student_id)
        except Student.DoesNotExist:
            return Response({"detail": "Student does not exist."}, status=404)

        try:
            access = TranscriptAccessRequest.objects.get(id=request_id, student=student)
        except TranscriptAccessRequest.DoesNotExist:
            return Response({"detail": "Transcript request not found."}, status=404)

        if action == "deny":
            try:
                access = deny_request(
                    access,
                    request.user,
                    admin_note=(request.data.get("admin_note") or "").strip(),
                )
            except (PermissionError, ValueError) as exc:
                return Response({"detail": str(exc)}, status=400)
            return Response({"id": str(access.id), "status": access.status})

        if action != "approve":
            return Response({"detail": "Invalid action."}, status=400)

        allow_download = bool(request.data.get("allow_download", True))
        send_email = bool(request.data.get("send_email", False))
        download_days = request.data.get("download_days")
        admin_note = (request.data.get("admin_note") or "").strip()

        try:
            if download_days is not None:
                download_days = max(int(download_days), 1)
        except (TypeError, ValueError):
            return Response({"detail": "download_days must be a positive integer."}, status=400)

        try:
            access = approve_or_grant_access(
                student=student,
                reviewer=request.user,
                allow_download=allow_download,
                send_email=send_email,
                download_days=download_days,
                admin_note=admin_note,
                source=access.source,
                access_request=access,
            )
        except (PermissionError, ValueError) as exc:
            return Response({"detail": str(exc)}, status=400)

        return Response(
            {
                "id": str(access.id),
                "status": access.status,
                "allow_download": access.allow_download,
                "send_email": access.send_email,
                "download_expires_at": access.download_expires_at,
            }
        )


class OfficialTranscriptRequestDetailView(APIView):
    """
    PATCH /grading/students/{student_id}/transcript/requests/{request_id}/
    DELETE /grading/students/{student_id}/transcript/requests/{request_id}/
    """

    permission_classes = [GradebookAccessPolicy]

    def _get_access(self, student_id: str, request_id: str):
        try:
            student = _get_student(student_id)
        except Student.DoesNotExist:
            return None, Response({"detail": "Student does not exist."}, status=404)

        try:
            access = TranscriptAccessRequest.objects.get(id=request_id, student=student)
        except TranscriptAccessRequest.DoesNotExist:
            return None, Response({"detail": "Transcript request not found."}, status=404)

        return access, None

    def patch(self, request, student_id, request_id):
        access, error_response = self._get_access(student_id, request_id)
        if error_response is not None:
            return error_response

        status_value = (request.data.get("status") or "").strip().lower()
        if not status_value:
            return Response({"detail": "status is required."}, status=400)

        admin_note = request.data.get("admin_note")
        if admin_note is not None:
            admin_note = str(admin_note).strip()

        try:
            access = update_transcript_request_status(
                access,
                request.user,
                status=status_value,
                admin_note=admin_note,
            )
        except PermissionError as exc:
            return Response({"detail": str(exc)}, status=403)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=400)

        return Response({"id": str(access.id), "status": access.status})

    def delete(self, request, student_id, request_id):
        access, error_response = self._get_access(student_id, request_id)
        if error_response is not None:
            return error_response

        try:
            delete_transcript_request(access, request.user)
        except PermissionError as exc:
            return Response({"detail": str(exc)}, status=403)

        return Response(status=status.HTTP_204_NO_CONTENT)


class OfficialTranscriptRequestListView(APIView):
    """GET /grading/transcript-requests/"""

    permission_classes = [GradebookAccessPolicy]

    def get(self, request):
        status_filter = (request.query_params.get("status") or "").strip() or None
        student_id = (request.query_params.get("student_id") or "").strip() or None
        results = list_transcript_requests(status=status_filter, student_id=student_id)
        return Response({"results": results, "count": len(results)})


class OfficialTranscriptGenerateView(APIView):
    """
    Queue official transcript PDF generation for a student.

    POST /grading/students/{student_id}/transcript/generate/
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, student_id):
        try:
            student = _get_student(student_id)
        except Student.DoesNotExist:
            return Response({"detail": "Student does not exist."}, status=404)

        allowed, reason = can_download_transcript(request.user, student)
        if not allowed:
            return Response(
                {
                    "detail": (
                        "You are not authorized to download this transcript. "
                        "Submit a request or contact the school office."
                    ),
                    "access_reason": reason,
                },
                status=403,
            )

        cache_key = TaskManager.generate_cache_key(
            {
                "type": "official_transcript_pdf",
                "student_id": str(student.id),
                "user_id": str(getattr(request.user, "id", "")),
            }
        )

        task_id = TaskManager.create_task(
            task_type="official_transcript_pdf",
            query_params={
                "student_id": str(student.id),
                "cache_key": cache_key,
            },
            user_id=getattr(request.user, "id", 0) or 0,
            estimated_count=1,
        )

        start_official_transcript_background_task(
            task_id,
            student_id=str(student.id),
            cache_key=cache_key,
            schema_name=getattr(request.tenant, "schema_name", None)
            or getattr(connection, "schema_name", None),
        )

        return Response(
            {
                "task_id": task_id,
                "status": "pending",
                "processing_mode": "background",
                "message": "Official transcript is being generated.",
                "check_status_url": f"/api/v1/reports/export-status/{task_id}/",
            },
            status=status.HTTP_202_ACCEPTED,
        )
