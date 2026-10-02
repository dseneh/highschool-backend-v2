"""Small allowlisted parent responses, separate from school administration serializers."""
from types import SimpleNamespace
from django.conf import settings
from django.db import IntegrityError, DatabaseError, transaction
from rest_framework import serializers
from django.utils import timezone
from django_tenants.utils import schema_context
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from users.models import ParentProfile, ParentStudentLink
from users.parent_portal import (accept_invitation, resolve_link, link_payload, issue_invitation, end_link, parent_communications)


class InvitationThrottle(AnonRateThrottle):
    scope = "parent_invitation_anon"
    rate = "10/hour"


class InvitationUserThrottle(UserRateThrottle):
    scope = "parent_invitation_user"
    rate = "20/hour"


class ParentAPIView(APIView):
    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "private, no-store"
        return response


class InvitationAcceptanceSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=200, min_length=20, trim_whitespace=False)


class InvitationEmailSerializer(InvitationAcceptanceSerializer):
    email = serializers.EmailField()


class InvitationRegistrationSerializer(InvitationEmailSerializer):
    password = serializers.CharField(max_length=128, trim_whitespace=False)
    first_name = serializers.CharField(max_length=100)
    last_name = serializers.CharField(max_length=100)
    gender = serializers.ChoiceField(choices=["male", "female"], allow_blank=True, required=False)
    date_of_birth = serializers.DateField(allow_null=True, required=False)



class ParentAcceptView(ParentAPIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [InvitationUserThrottle]

    def post(self, request):
        serializer = InvitationAcceptanceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        profile = accept_invitation(**serializer.validated_data, user=request.user)
        return Response({"detail": "Invitation accepted. Open your Parent portal.", "id": str(profile.pk)})


class ParentInvitationEmailView(ParentAPIView):
    permission_classes = [AllowAny]
    throttle_classes = [InvitationThrottle, InvitationUserThrottle]

    def post(self, request):
        from users.parent_portal import validate_invitation_email, invitation_staff_details
        from users.models import User
        serializer = InvitationEmailSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        invitation = validate_invitation_email(**serializer.validated_data)
        if User.objects.filter(email__iexact=invitation.email).exists():
            raise ValidationError("An account already exists for this email. Sign in to continue.")
        return Response({"detail": "Email matches. Continue creating your account.",
                         "staff_details": invitation_staff_details(invitation)})


class ParentInvitationRegisterView(ParentAPIView):
    permission_classes = [AllowAny]
    throttle_classes = [InvitationThrottle, InvitationUserThrottle]

    def post(self, request):
        from users.parent_portal import register_invited_parent
        from common.email_service import send_notification_email
        from users.utils import build_frontend_url
        serializer = InvitationRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            user, invitation = register_invited_parent(**serializer.validated_data)
        except IntegrityError:
            raise ValidationError("Unable to create this account. Sign in or contact the school.")
        # The transaction has committed before confirmation delivery; never email passwords.
        sent = False
        if getattr(settings, "PARENT_INVITATIONS_ENABLED", False):
            sent = send_notification_email(user, "Your EzySchool account has been created",
                "Your account is ready. Sign in with your email and password, then return to your school's invitation to accept parent portal access. If you did not create this account, contact your school.",
                school=invitation.tenant, action_url=build_frontend_url(invitation.tenant.schema_name, "/login"))
        return Response({"detail": "Account created. Sign in to accept your invitation.", "confirmation_sent": bool(sent)}, status=201)


def parent_dashboard_snapshot(user, link, guardian, assignment):
    """Resolve each school's Parent role independently; never use the caller's staff grants."""
    from copy import copy
    from authorization.runtime import resolve_authorization_context
    from finance.models import get_student_payment_plan
    with schema_context(link.tenant.schema_name):
        parent_user = copy(user)
        parent_user._active_role_selection = str(assignment.pk)
        context = resolve_authorization_context(parent_user)
        student = guardian.student
        enrollment = student.enrollments.filter(active=True, academic_year__current=True).select_related("academic_year").first()
        tuition = None
        if context.permission_scope("billing.view"):
            tuition = [row for row in get_student_payment_plan(enrollment) if row["balance"] > 0] if enrollment else []
        birthday = student.date_of_birth
        return {
            "birthday": {"month": birthday.month, "day": birthday.day} if birthday else None,
            "tuition": tuition,
            "announcements": parent_communications(user, student) if context.permission_scope("notifications.view") else [],
        }


class ParentSummaryView(ParentAPIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = ParentProfile.objects.filter(user=request.user).first()
        try:
            offset = max(0, int(request.query_params.get("offset", 0)))
        except (TypeError, ValueError):
            raise ValidationError("Invalid offset.")
        # Paginate discovery candidates BEFORE visiting schemas, including stale rows.
        candidates = list(ParentStudentLink.objects.filter(profile=profile, active=True).order_by("pk")[offset:offset+51]) if profile else []
        result = []
        for candidate in candidates[:50]:
            try:
                with transaction.atomic():
                    link, guardian, assignment = resolve_link(request.user, candidate.pk)
                    payload = link_payload(link, guardian, request)
                    payload["dashboard"] = parent_dashboard_snapshot(request.user, link, guardian, assignment)
                    result.append(payload)
            except (NotFound, DatabaseError):
                continue
        return Response({"id": str(profile.pk) if profile else None, "linked_students": result,
                         "next_offset": offset+50 if len(candidates) > 50 else None})


class ParentSelectView(ParentAPIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, link_id):
        link, guardian, assignment = resolve_link(request.user, link_id)
        from users.parent_portal import audit_link
        with schema_context(link.tenant.schema_name):
            audit_link(guardian, request.user, "selected")
        return Response({**link_payload(link, guardian, request), "assignment_id": str(assignment.pk)})


class ParentStudentView(ParentAPIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, link_id):
        link, guardian, _ = resolve_link(request.user, link_id, require_context=True)
        from students.models import Attendance
        from students.authorization import permission_scope
        from grading.models import Grade
        from students.services.balance import annotate_student_balance_totals
        with schema_context(link.tenant.schema_name):
            student = guardian.student
            enrollment = student.enrollments.filter(active=True, academic_year__current=True).select_related("section", "grade_level", "academic_year").first()
            attendance = list(Attendance.objects.filter(enrollment__student=student, active=True).order_by("-date").values("id", "date", "status")[:30]) if permission_scope(request, "attendance.view") else []
            # APPROVED is this application's published grade state; never expose drafts/review notes.
            grades = list(Grade.objects.filter(student=student, active=True, status="approved").order_by("-updated_at").values(
                "id", "assessment__name", "subject__name", "score", "assessment__max_score")[:50])
            from grading.services.grade_access import enforce_grade_access
            grades_restricted = not bool(permission_scope(request, "grades.view"))
            if grades_restricted:
                grades = []
            try:
                enforce_grade_access(student, enrollment.academic_year if enrollment else None)
            except PermissionDenied:
                grades, grades_restricted = [], True
            from students.models.historical_grade import HistoricalGradeRecord
            reports = [] if grades_restricted or not permission_scope(request, "reports.transcript.view") else list(HistoricalGradeRecord.objects.filter(
                student=student, active=True, status="verified").order_by("-academic_year__start_date").values(
                    "id", "academic_year__name", "subject_name", "subject__name", "final_percentage", "final_letter")[:50])
            balance = annotate_student_balance_totals(student.__class__.objects.filter(pk=student.pk),
                academic_year=enrollment.academic_year).first() if enrollment and permission_scope(request, "billing.view") else None
            return Response({**link_payload(link, guardian, request), "details": {"gender": student.gender},
                "enrollment": {"grade_level": enrollment.grade_level.name, "section": enrollment.section.name,
                               "academic_year": enrollment.academic_year.name} if enrollment else None,
                "communications": parent_communications(request.user, student) if permission_scope(request, "notifications.view") else [],
                "attendance": attendance, "grades": grades, "grades_restricted": grades_restricted, "reports": reports,
                "fees": {"billed": balance.billed_total, "paid": balance.paid_total, "balance": balance.balance_total} if balance else None})

    def delete(self, request, link_id):
        link, guardian, _ = resolve_link(request.user, link_id, require_context=True)
        end_link(tenant=link.tenant, guardian_id=guardian.pk, actor=request.user)
        return Response(status=204)


class GuardianPortalView(ParentAPIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [InvitationUserThrottle]

    def get(self, request, guardian_id):
        from students.models import Student, StudentGuardian
        from students.authorization import permission_scope, filter_students_for_permission_scope
        if permission_scope(request, "students.guardians.manage") not in {"all", "assigned"}:
            raise PermissionDenied("School guardian-management permission is required.")
        visible = filter_students_for_permission_scope(Student.objects.all(), request, "students.guardians.manage")
        if not StudentGuardian.objects.filter(pk=guardian_id, student__in=visible).exists():
            raise NotFound()
        profile_ids = StudentGuardian.objects.filter(student__in=visible, active=True, student__active=True,
            portal_state="active", portal_verified_at__isnull=False, portal_approved_at__isnull=False,
            portal_ended_at=None).exclude(parent_profile_id=None).values("parent_profile_id")
        # Only identities already verified and visible inside this school; never search shared contacts.
        profiles = ParentProfile.objects.filter(pk__in=profile_ids, user__is_active=True).select_related("user").order_by("user__last_name", "pk")[:50]
        return Response({"verified_identities": [{"id": str(profile.pk),
            "display_name": f"{profile.user.first_name} {profile.user.last_name}".strip() or profile.user.id_number,
            "email": profile.user.email} for profile in profiles]})

    def post(self, request, guardian_id):
        from students.models import StudentGuardian
        from students.authorization import user_can_access_student_for_permission, permission_scope
        if permission_scope(request, "students.guardians.manage") not in {"all", "assigned"}:
            raise PermissionDenied("School guardian-management permission is required.")
        guardian = StudentGuardian.objects.filter(pk=guardian_id).first()
        if not guardian:
            raise NotFound()
        # Own-scope/student submissions never constitute staff approval.
        if permission_scope(request, "students.guardians.manage") not in {"all", "assigned"} or not user_can_access_student_for_permission(guardian.student, request, "students.guardians.manage"):
            raise PermissionDenied("School guardian-management permission is required.")
        action = request.data.get("action")
        if action == "link_verified":
            from users.parent_portal import attach_approved_relationship
            from uuid import UUID
            try:
                profile_id = UUID(str(request.data.get("profile_id", "")))
                from students.models import Student
                from students.authorization import filter_students_for_permission_scope
                visible = filter_students_for_permission_scope(Student.objects.all(), request, "students.guardians.manage")
                if not StudentGuardian.objects.filter(parent_profile_id=profile_id, student__in=visible, active=True,
                        portal_state="active", portal_verified_at__isnull=False, portal_approved_at__isnull=False).exists():
                    raise ValidationError("Verified identity unavailable.")
                attach_approved_relationship(tenant=request.tenant, guardian_id=guardian.pk, profile_id=profile_id, actor=request.user)
            except (ValueError, ParentProfile.DoesNotExist):
                raise ValidationError("Verified identity unavailable.")
            return Response({"portal_state": "active"})
        if action in {"suspend", "disconnect"}:
            end_link(tenant=request.tenant, guardian_id=guardian.pk, actor=request.user,
                     state="suspended" if action == "suspend" else "disconnected")
            return Response({"portal_state": "suspended" if action == "suspend" else "disconnected"})
        if action == "give_access":
            from users.account_setup import set_guardian_access
            enabled = request.data.get("give_access")
            if not isinstance(enabled, bool):
                raise ValidationError("Choose whether to give access.")
            guardian = set_guardian_access(request.tenant, guardian, request.user, enabled)
            return Response({"give_access": enabled, "portal_state": guardian.portal_state})
        raise ValidationError("Use Give access to approve this relationship. Invitations have been replaced by account setup.")
