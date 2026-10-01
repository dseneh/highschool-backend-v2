from django.db import transaction, IntegrityError
from django.utils import timezone
from rest_framework import serializers
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.settings import api_settings
from rest_framework.exceptions import ValidationError, PermissionDenied, NotFound
from users.parent_views import ParentAPIView, InvitationThrottle, InvitationUserThrottle
from users.account_setup import begin_setup, verify_setup, complete_setup, has_email_proof, activate_guardian, set_guardian_access
from users.parent_portal import school_available
from users.models import ParentLinkRequest


class SetupStartSerializer(serializers.Serializer):
    account_type = serializers.ChoiceField(choices=["staff", "student", "parent"])
    email = serializers.EmailField()


class SetupVerifySerializer(serializers.Serializer):
    challenge_id = serializers.UUIDField()
    code = serializers.RegexField(r"^\d{6}$")


class SetupCompleteSerializer(serializers.Serializer):
    terms_accepted = serializers.BooleanField(required=False)
    challenge_id = serializers.UUIDField()
    proof = serializers.CharField(min_length=20, max_length=200)
    password = serializers.CharField(max_length=128, required=False, default="", trim_whitespace=False)
    first_name = serializers.CharField(max_length=100)
    middle_name = serializers.CharField(max_length=100, required=False, allow_blank=True)
    last_name = serializers.CharField(max_length=100)
    gender = serializers.ChoiceField(choices=["male", "female"], allow_blank=True, required=False)
    date_of_birth = serializers.DateField(required=False, allow_null=True)
    phone_number = serializers.CharField(max_length=20, required=False, allow_blank=True)
    address = serializers.CharField(max_length=500, required=False, allow_blank=True)


class AccountSetupView(ParentAPIView):
    permission_classes = [AllowAny]
    throttle_classes = api_settings.DEFAULT_THROTTLE_CLASSES

    def post(self, request, action):
        tenant = request.tenant
        from users.parent_workspace import is_parent_workspace
        global_parent = is_parent_workspace(request)
        if not global_parent and not school_available(tenant):
            raise ValidationError("Open account setup from your school's login page.")
        from users import global_parent_setup
        start = global_parent_setup.begin if global_parent else begin_setup
        verify = global_parent_setup.verify if global_parent else verify_setup
        complete = global_parent_setup.complete if global_parent else complete_setup
        serializer_class = {"start": SetupStartSerializer, "verify": SetupVerifySerializer, "complete": SetupCompleteSerializer}.get(action)
        if not serializer_class:
            raise NotFound()
        serializer = serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if action == "start":
            challenge = start(tenant, data["account_type"], data["email"])
            return Response({"challenge_id": str(challenge.pk), "detail": "Check your email for the verification code."})
        if action == "verify":
            return Response(verify(tenant, **data))
        challenge_id, proof, password = data.pop("challenge_id"), data.pop("proof"), data.pop("password")
        try:
            user, created = complete(tenant, challenge_id, proof, data, password, request.user)
        except IntegrityError:
            raise ValidationError("An account or school record changed. Sign in or start setup again.")
        if created:
            from common.email_service import send_notification_email
            send_notification_email(user, "Your EzySchool account is ready", "Your account has been created. Sign in using your email and password.", school=tenant)
        return Response({"detail": "Account setup complete. Sign in to continue."}, status=201 if created else 200)


def visible_students(request):
    from students.models import Student
    from students.authorization import permission_scope, filter_students_for_permission_scope
    if permission_scope(request, "students.guardians.manage") not in {"all", "assigned"}:
        raise PermissionDenied("School guardian-management permission is required.")
    return filter_students_for_permission_scope(Student.objects.all(), request, "students.guardians.manage")


class ContactPortalAccessView(ParentAPIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, contact_id):
        from students.models import StudentContact, StudentGuardian
        contact = StudentContact.objects.select_for_update().filter(pk=contact_id, student__in=visible_students(request), active=True, relationship__in=["parent", "guardian"]).first()
        if not contact:
            raise NotFound()
        enabled = request.data.get("give_access")
        if not isinstance(enabled, bool):
            raise ValidationError("Choose whether to give access.")
        guardian = StudentGuardian.objects.filter(pk=contact.portal_guardian_id, student=contact.student).first() if contact.portal_guardian_id else None
        if not guardian and enabled:
            guardian = StudentGuardian.objects.create(student=contact.student, first_name=contact.first_name,
                last_name=contact.last_name, email=contact.email, phone_number=contact.phone_number,
                address=contact.address, relationship="legal_guardian" if contact.relationship == "guardian" else "other",
                created_by=request.user)
            contact.portal_guardian_id = guardian.pk
            contact.save(update_fields=["portal_guardian_id"])
        if guardian:
            if (guardian.email or "").strip().lower() != (contact.email or "").strip().lower():
                raise ValidationError("This contact's guardian email has changed. Manage access from the guardian record after school review.")
            guardian = set_guardian_access(request.tenant, guardian, request.user, enabled)
        return Response({"give_access": enabled, "portal_state": guardian.portal_state if guardian else "unverified"})


class LinkStudentSerializer(serializers.Serializer):
    student_id_number = serializers.CharField(max_length=50)
    first_name = serializers.CharField(max_length=100)
    middle_name = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    last_name = serializers.CharField(max_length=100)
    gender = serializers.ChoiceField(choices=["male", "female"], required=False, allow_blank=True, default="")
    relationship = serializers.CharField(max_length=20, required=False, allow_blank=True, default="other")


def normalize(value):
    return " ".join(str(value or "").split()).casefold()


class ParentLinkRequestsView(ParentAPIView):
    permission_classes = [IsAuthenticated]
    throttle_classes = [InvitationUserThrottle]

    def get(self, request):
        rows = ParentLinkRequest.objects.filter(tenant=request.tenant, user=request.user).order_by("-created_at")[:50]
        return Response([{"id": str(r.pk), "status": r.status, "created_at": r.created_at} for r in rows])

    @transaction.atomic
    def post(self, request):
        from students.models import Student, StudentGuardian
        if not school_available(request.tenant) or not request.user.tenants.filter(pk=request.tenant.pk).exists() or not has_email_proof(request.user):
            raise PermissionDenied("Verify your email using Set up account at this school before linking a student.")
        serializer = LinkStudentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        data["relationship"] = data["relationship"] or "other"
        if data["relationship"] not in dict(StudentGuardian.RELATIONSHIP_CHOICES):
            raise ValidationError("Choose a valid relationship.")
        student = Student.objects.filter(id_number=data["student_id_number"], active=True).exclude(status="deleted").first()
        if (not student or normalize(student.first_name) != normalize(data["first_name"])
                or normalize(student.last_name) != normalize(data["last_name"])
                or (data["middle_name"] and normalize(student.middle_name) != normalize(data["middle_name"]))
                or (data["gender"] and student.gender != data["gender"])):
            raise ValidationError("The supplied student details could not be confirmed. Check them with the school.")
        # Serialize requests by user, and only auto-link an explicitly approved relationship.
        from users.models import User
        User.objects.select_for_update().get(pk=request.user.pk)
        guardians = StudentGuardian.objects.select_for_update().filter(student=student, active=True, email__iexact=request.user.email, give_access=True)
        linked = any([activate_guardian(g, request.user, request.tenant) for g in guardians])
        if linked:
            return Response({"status": "linked", "detail": "Student linked. Refresh your Parent portal to select them."})
        row, _ = ParentLinkRequest.objects.get_or_create(tenant=request.tenant, user=request.user, student_id=student.pk, status="pending", defaults={"relationship": data["relationship"]})
        return Response({"id": str(row.pk), "status": row.status, "detail": "Your request is awaiting school approval. No student access has been granted."}, status=202)


class ReviewParentRequestsView(ParentAPIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, student_id):
        if not visible_students(request).filter(pk=student_id).exists():
            raise NotFound()
        rows = ParentLinkRequest.objects.filter(tenant=request.tenant, student_id=student_id, status="pending").select_related("user").order_by("created_at")[:100]
        return Response([{"id": str(r.pk), "name": f"{r.user.first_name} {r.user.last_name}", "email": r.user.email, "relationship": r.relationship} for r in rows])

    @transaction.atomic
    def post(self, request, student_id):
        from students.models import StudentGuardian
        if not visible_students(request).filter(pk=student_id, active=True).exclude(status="deleted").exists():
            raise NotFound()
        class ReviewSerializer(serializers.Serializer):
            request_id = serializers.UUIDField()
            approve = serializers.BooleanField()
        serializer = ReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        row = ParentLinkRequest.objects.select_for_update().filter(pk=serializer.validated_data["request_id"], tenant=request.tenant, student_id=student_id, status="pending").select_related("user").first()
        if not row:
            raise NotFound()
        if row.user_id == request.user.pk:
            raise PermissionDenied("Another authorized staff member must review your request.")
        if serializer.validated_data["approve"]:
            if not row.user.is_active or not has_email_proof(row.user):
                raise ValidationError("The parent must verify their current email before approval.")
            matches = list(StudentGuardian.objects.select_for_update().filter(student_id=student_id, email__iexact=row.user.email, active=True)[:2])
            if len(matches) > 1:
                raise ValidationError("Resolve duplicate guardian records before approving this request.")
            guardian = matches[0] if matches else StudentGuardian.objects.create(student_id=student_id, first_name=row.user.first_name, last_name=row.user.last_name,
                email=row.user.email, relationship=row.relationship, created_by=request.user)
            set_guardian_access(request.tenant, guardian, request.user, True)
            row.status = "approved"
        else:
            row.status = "rejected"
        row.reviewed_by, row.reviewed_at = request.user, timezone.now()
        row.save(update_fields=["status", "reviewed_by", "reviewed_at"])
        return Response({"status": row.status})


class RetiredInvitationView(ParentAPIView):
    permission_classes = [AllowAny]

    def post(self, request):
        return Response({"detail": "Invitations have been replaced. Use Set up account on your school's login page."}, status=410)
