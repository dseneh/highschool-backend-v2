from django.db import transaction
from django.core.cache import cache
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.exceptions import NotFound, ValidationError, Throttled
from users.models import SchoolUserAccess
from users.school_access import require_manager, approve_access, send_setup_instructions


class SchoolUserAccessView(APIView):
    permission_classes = [IsAuthenticated]

    def record(self, request, access_id, *, lock=False):
        require_manager(request.user, request.tenant)
        query = SchoolUserAccess.objects.filter(pk=access_id, tenant=request.tenant).exclude(status="accepted")
        record = (query.select_for_update() if lock else query).first()
        if not record:
            raise NotFound()
        return record

    def get(self, request):
        require_manager(request.user, request.tenant)
        return Response({"results": list(SchoolUserAccess.objects.filter(tenant=request.tenant).exclude(status="accepted").order_by("-created_at").values("id", "email", "first_name", "last_name", "role_id", "role_name", "status", "created_at", "instructions_sent_at", "instructions_failed"))})

    def patch(self, request, access_id):
        with transaction.atomic():
            record = self.record(request, access_id, lock=True)
            if record.status != "pending":
                raise ValidationError("Revoked approvals cannot be edited. Create a new approval instead.")
            record = approve_access(request.tenant, request.user, request.data, existing_record=record)
        sent = send_setup_instructions(record)
        return Response({"id": str(record.pk), "instructions_sent": sent})

    def post(self, request, access_id):
        with transaction.atomic():
            record = self.record(request, access_id, lock=True)
            if record.status != "pending":
                raise ValidationError("This approval is no longer pending.")
            action = request.data.get("action")
            if action == "revoke":
                record.status = "revoked"
                record.save(update_fields=["status"])
                self.audit(request, record, "revoked")
                return Response(status=204)
            if action != "resend":
                raise ValidationError("Choose revoke or resend.")
            if not cache.add(f"school-access-instructions:{record.pk}", True, timeout=60):
                raise Throttled(wait=60, detail="Wait one minute before sending instructions again.")
        sent = send_setup_instructions(record)
        return Response({"instructions_sent": sent})

    @transaction.atomic
    def delete(self, request, access_id):
        record = self.record(request, access_id, lock=True)
        self.audit(request, record, "deleted")
        record.delete()
        return Response(status=204)

    @staticmethod
    def audit(request, record, action):
        from authorization.models import AuthorizationAuditLog
        AuthorizationAuditLog.objects.create(actor=request.user, action=f"school_access.{action}", target_type="school_access", target_id=str(record.pk), after={"email": record.email, "role_id": str(record.role_id)})
