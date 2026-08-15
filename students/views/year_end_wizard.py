from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from academics.models import AcademicYear
from students.access_policies import StudentAccessPolicy
from students.services.year_end_wizard import apply_year_end_wizard, build_year_end_wizard_preview
from users.access_policies.access import BaseSchoolAccessPolicy


class YearEndWizardView(APIView):
    permission_classes = [StudentAccessPolicy]

    def _scope(self, request):
        policy = BaseSchoolAccessPolicy()
        if policy.is_role_in(request, self, "post", "admin,registrar"):
            return None
        if not policy.is_role_in(request, self, "post", "teacher"):
            return False
        from staff.models import Staff, TeacherSection

        staff = Staff.objects.filter(user_account_id_number=getattr(request.user, "id_number", "")).first()
        return list(TeacherSection.objects.filter(teacher=staff).values_list("section_id", flat=True)) if staff else []

    def post(self, request):
        allowed_section_ids = self._scope(request)
        if allowed_section_ids is False:
            return Response({"detail": "Only administrators and registrars can process year-end outcomes."}, status=status.HTTP_403_FORBIDDEN)
        academic_year = AcademicYear.objects.filter(id=request.data.get("academic_year")).first()
        if not academic_year:
            return Response({"academic_year": "A valid academic year is required."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            return Response(build_year_end_wizard_preview(academic_year=academic_year, outcomes=request.data.get("outcomes"), grade_level_id=request.data.get("grade_level") or None, section_id=request.data.get("section") or None, allowed_section_ids=allowed_section_ids))
        except Exception as exc:
            from rest_framework.exceptions import ValidationError
            if isinstance(exc, ValidationError):
                raise
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)


class YearEndWizardApplyView(YearEndWizardView):
    def post(self, request):
        allowed_section_ids = self._scope(request)
        if allowed_section_ids is False:
            return Response({"detail": "Only administrators and registrars can process year-end outcomes."}, status=status.HTTP_403_FORBIDDEN)
        academic_year = AcademicYear.objects.filter(id=request.data.get("academic_year")).first()
        if not academic_year:
            return Response({"academic_year": "A valid academic year is required."}, status=status.HTTP_400_BAD_REQUEST)
        return Response(apply_year_end_wizard(academic_year=academic_year, outcomes=request.data.get("outcomes"), consent_acknowledged=request.data.get("consent_acknowledged") is True, grade_level_id=request.data.get("grade_level") or None, section_id=request.data.get("section") or None, allowed_section_ids=allowed_section_ids, actor=request.user))