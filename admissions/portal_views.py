import hashlib
import logging

import magic
from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .authentication import ApplicantSessionAuthentication
from .emails import send_application_verification_email
from .enums import ApplicationStatus
from .models import (
    AdmissionApplication,
    ApplicationDocument,
    ApplicationInformationRequest,
    ApplicationMessage,
    ApplicationStatusHistory,
)
from .security import issue_email_verification, issue_portal_session, verify_email_code
from .serializers import (
    ApplicantVerificationSerializer,
    ApplicantAccessRequestSerializer,
    ApplicationDocumentSerializer,
    ApplicationDocumentRequirementSerializer,
    ApplicationDocumentUploadSerializer,
    ApplicationMessageSerializer,
    InformationRequestSerializer,
    PortalApplicationSerializer,
    PublicApplicationStartSerializer,
    ReturningApplicationStartSerializer,
)
from .services import (
    APPLICANT_UPLOAD_STATUSES,
    applicable_document_requirements,
    application_submission_errors,
    transition_application,
)


logger = logging.getLogger(__name__)


def _send_verification_safely(application, code):
    try:
        send_application_verification_email(application=application, code=code)
    except Exception:
        logger.exception("Unable to send applicant verification email", extra={"application_id": str(application.id)})


class PublicApplicationStartView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "admissions_start"

    @transaction.atomic
    def post(self, request):
        serializer = PublicApplicationStartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        application = serializer.save()
        ApplicationStatusHistory.objects.create(
            application=application,
            from_status="",
            to_status=ApplicationStatus.DRAFT,
            reason="Application started",
        )
        challenge, code = issue_email_verification(application=application)
        transaction.on_commit(lambda: _send_verification_safely(application, code))
        return Response(
            {"challenge_id": challenge.id, "verification_required": True},
            status=status.HTTP_202_ACCEPTED,
        )


class ApplicantVerificationView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "admissions_start"

    def post(self, request):
        serializer = ApplicantVerificationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            application = verify_email_code(**serializer.validated_data)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        _token, raw_token = issue_portal_session(application=application)
        return Response({
            "request_id": application.request_id,
            "session_token": raw_token,
            "expires_in": 24 * 60 * 60,
        })


class ApplicantAccessRequestView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "admissions_start"

    def post(self, request):
        serializer = ApplicantAccessRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        application = AdmissionApplication.objects.filter(
            request_id__iexact=values["request_id"].strip(),
            applicant_email__iexact=values["email"].strip(),
        ).first()
        if application is not None:
            _challenge, code = issue_email_verification(application=application)
            transaction.on_commit(lambda: _send_verification_safely(application, code))
        return Response(
            {"detail": "If the request details match, a verification code will be sent."},
            status=status.HTTP_202_ACCEPTED,
        )


class ReturningApplicationStartView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request):
        serializer = ReturningApplicationStartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        requested_student_id = serializer.validated_data.get("student_id")
        eligible_students = []
        own_student = request.user.get_student()
        if own_student is not None:
            eligible_students.append(own_student)
        children = request.user.get_children()
        if children is not None:
            eligible_students.extend(children)

        unique_students = {student.pk: student for student in eligible_students}
        if requested_student_id:
            student = unique_students.get(requested_student_id)
        elif len(unique_students) == 1:
            student = next(iter(unique_students.values()))
        else:
            student = None
        if student is None:
            return Response(
                {"student_id": ["Select a student associated with this account."]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        cycle = serializer.validated_data["cycle"]
        duplicate = AdmissionApplication.objects.filter(
            cycle=cycle,
            returning_student=student,
        ).exclude(
            status__in={
                ApplicationStatus.REJECTED,
                ApplicationStatus.WITHDRAWN,
                ApplicationStatus.CANCELLED,
            }
        ).first()
        if duplicate is not None:
            return Response(
                {"detail": "A registration already exists for this student and cycle.", "request_id": duplicate.request_id},
                status=status.HTTP_409_CONFLICT,
            )

        applicant_name = " ".join(
            part for part in (request.user.first_name, request.user.last_name) if part
        ).strip() or student.get_full_name()
        application = AdmissionApplication.objects.create(
            cycle=cycle,
            application_type="returning_registration",
            returning_student=student,
            requested_grade_level=serializer.validated_data["requested_grade_level"],
            applicant_name=applicant_name,
            applicant_email=request.user.email or student.email or "",
            applicant_phone=student.phone_number or "",
            student_profile={
                "first_name": student.first_name,
                "middle_name": student.middle_name or "",
                "last_name": student.last_name,
                "date_of_birth": student.date_of_birth.isoformat() if student.date_of_birth else None,
                "gender": student.gender,
            },
            created_by=request.user,
            updated_by=request.user,
        )
        ApplicationStatusHistory.objects.create(
            application=application,
            from_status="",
            to_status=ApplicationStatus.DRAFT,
            reason="Returning registration started by authenticated account",
            created_by=request.user,
            updated_by=request.user,
        )
        _token, raw_token = issue_portal_session(application=application)
        return Response(
            {
                "request_id": application.request_id,
                "session_token": raw_token,
                "expires_in": 24 * 60 * 60,
            },
            status=status.HTTP_201_CREATED,
        )


class ApplicantPortalMixin:
    authentication_classes = [ApplicantSessionAuthentication]
    permission_classes = [IsAuthenticated]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "admissions_public"

    def get_application(self, request_id):
        application = self.request.user.application
        if application.request_id != request_id:
            return None
        return application


class ApplicantApplicationView(ApplicantPortalMixin, APIView):
    def get(self, request, request_id):
        application = self.get_application(request_id)
        if application is None:
            return Response({"detail": "Application not found."}, status=404)
        return Response(PortalApplicationSerializer(application).data)

    def patch(self, request, request_id):
        application = self.get_application(request_id)
        if application is None:
            return Response({"detail": "Application not found."}, status=404)
        try:
            requested_version = int(request.data.get("version"))
        except (TypeError, ValueError):
            requested_version = None
        if requested_version != application.version:
            return Response({"detail": "Application changed. Refresh and try again.", "error_code": "VERSION_CONFLICT"}, status=409)
        serializer = PortalApplicationSerializer(application, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        application.version += 1
        application.save(update_fields=["version", "updated_at"])
        return Response(PortalApplicationSerializer(application).data)


class ApplicantSubmitView(ApplicantPortalMixin, APIView):
    def post(self, request, request_id):
        application = self.get_application(request_id)
        if application is None:
            return Response({"detail": "Application not found."}, status=404)
        try:
            version = int(request.data.get("version"))
        except (TypeError, ValueError):
            version = None
        if version != application.version:
            return Response({"detail": "Application changed. Refresh and try again.", "error_code": "VERSION_CONFLICT"}, status=409)
        submission_errors = application_submission_errors(application)
        if submission_errors:
            return Response({"detail": "Application is incomplete.", "errors": submission_errors}, status=400)
        application = transition_application(application=application, to_status=ApplicationStatus.SUBMITTED)
        return Response(PortalApplicationSerializer(application).data)


class ApplicantMessageListCreateView(ApplicantPortalMixin, APIView):
    def get(self, request, request_id):
        application = self.get_application(request_id)
        if application is None:
            return Response({"detail": "Application not found."}, status=404)
        application.messages.filter(author_type=ApplicationMessage.AuthorType.SCHOOL, applicant_read_at__isnull=True).update(applicant_read_at=timezone.now())
        return Response(ApplicationMessageSerializer(application.messages.all(), many=True).data)

    def post(self, request, request_id):
        application = self.get_application(request_id)
        if application is None:
            return Response({"detail": "Application not found."}, status=404)
        serializer = ApplicationMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        message = serializer.save(application=application, author_type=ApplicationMessage.AuthorType.APPLICANT)
        return Response(ApplicationMessageSerializer(message).data, status=201)


class ApplicantInformationRequestListView(ApplicantPortalMixin, APIView):
    def get(self, request, request_id):
        application = self.get_application(request_id)
        if application is None:
            return Response({"detail": "Application not found."}, status=404)
        return Response(InformationRequestSerializer(application.information_requests.all(), many=True).data)


class ApplicantInformationResponseView(ApplicantPortalMixin, APIView):
    @transaction.atomic
    def post(self, request, request_id, information_request_id):
        application = self.get_application(request_id)
        if application is None:
            return Response({"detail": "Application not found."}, status=404)
        item = ApplicationInformationRequest.objects.select_for_update().filter(pk=information_request_id, application=application, status=ApplicationInformationRequest.Status.OPEN).first()
        if item is None:
            return Response({"detail": "Open information request not found."}, status=404)
        serializer = ApplicationMessageSerializer(data={"body": request.data.get("body", "")})
        serializer.is_valid(raise_exception=True)
        serializer.save(application=application, author_type=ApplicationMessage.AuthorType.APPLICANT)
        item.status = ApplicationInformationRequest.Status.RESPONDED
        item.save(update_fields=["status", "updated_at"])
        if application.status == ApplicationStatus.INFORMATION_REQUESTED:
            transition_application(application=application, to_status=ApplicationStatus.INFORMATION_RECEIVED)
        return Response(InformationRequestSerializer(item).data)


class ApplicantDocumentListCreateView(ApplicantPortalMixin, APIView):
    parser_classes = [MultiPartParser, FormParser]

    def get(self, request, request_id):
        application = self.get_application(request_id)
        if application is None:
            return Response({"detail": "Application not found."}, status=404)
        return Response(ApplicationDocumentSerializer(application.documents.select_related("requirement"), many=True).data)

    def post(self, request, request_id):
        application = self.get_application(request_id)
        if application is None:
            return Response({"detail": "Application not found."}, status=404)
        if application.status not in APPLICANT_UPLOAD_STATUSES:
            return Response(
                {"detail": "Documents cannot be uploaded at this stage."},
                status=status.HTTP_409_CONFLICT,
            )
        serializer = ApplicationDocumentUploadSerializer(data=request.data, context={"application": application})
        serializer.is_valid(raise_exception=True)
        upload = serializer.validated_data["file"]
        sample = upload.read(4096)
        upload.seek(0)
        detected_mime = magic.from_buffer(sample, mime=True)
        allowed_mimes = {"application/pdf", "image/png", "image/jpeg"}
        if detected_mime not in allowed_mimes:
            return Response({"file": ["The uploaded content does not match an allowed file type."]}, status=400)
        digest = hashlib.sha256()
        for chunk in upload.chunks():
            digest.update(chunk)
        upload.seek(0)
        document = ApplicationDocument.objects.create(
            application=application,
            requirement=serializer.validated_data["requirement"],
            file=upload,
            original_name=upload.name,
            mime_type=detected_mime,
            size_bytes=upload.size,
            checksum_sha256=digest.hexdigest(),
        )
        return Response(ApplicationDocumentSerializer(document).data, status=201)


class ApplicantDocumentRequirementListView(ApplicantPortalMixin, APIView):
    def get(self, request, request_id):
        application = self.get_application(request_id)
        if application is None:
            return Response({"detail": "Application not found."}, status=404)
        requirements = applicable_document_requirements(application)
        return Response(
            ApplicationDocumentRequirementSerializer(requirements, many=True).data
        )


class ApplicantDocumentDownloadView(ApplicantPortalMixin, APIView):
    def get(self, request, request_id, document_id):
        application = self.get_application(request_id)
        if application is None:
            return Response({"detail": "Application not found."}, status=404)
        document = application.documents.filter(pk=document_id).first()
        if document is None:
            return Response({"detail": "Document not found."}, status=404)
        if document.scan_status != ApplicationDocument.ScanStatus.CLEAN:
            return Response({"detail": "Document is not available until its security scan is complete."}, status=423)
        return Response({"url": document.file.storage.url(document.file.name, expire=300), "expires_in": 300})
