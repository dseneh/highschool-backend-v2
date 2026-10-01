"""Explicit read-only adapter for shared student pages in the Parent role.

Unlisted school endpoints remain denied. Every student route is checked against
verified guardians in the current schema before the existing view is invoked.
"""
from uuid import UUID
from django.db.models import Q
from rest_framework.exceptions import NotFound

# (module, class): (student identifier kwarg, required permission)
STUDENT_READS = {
    ("reports.views.students", "StudentIndividualReportView"): ("student_id", "students.view"),
    ("students.views.student", "StudentDetailView"): ("id", "students.view"),
    ("students.views.student_bill", "StudentEnrollmentBillListView"): ("student_id", "billing.view"),
    ("students.views.student_bill", "StudentBillingPDFView"): ("student_id", "billing.view"),
    ("students.views.attendance", "AttendanceListView"): ("student_id", "attendance.view"),
    ("students.views.contact", "StudentContactListView"): ("student_id", "students.contacts.view"),
    ("students.views.guardian", "StudentGuardianListView"): ("student_id", "students.guardians.view"),
    ("students.views.enrollment", "EnrollmentListView"): ("student_id", "students.view"),
    ("students.views.discipline", "StudentDisciplinaryActionByStudentListCreateView"): ("student_id", "students.discipline.view"),
    ("students.views.historical_grade", "StudentGradeHistoryView"): ("student_id", "grades.view"),
    ("students.views.historical_grade", "HistoricalGradeRecordListView"): ("student_id", "grades.view"),
    ("grading.views.final_grades", "StudentFinalGradeView"): ("student_id", "grades.view"),
    ("grading.views.final_grades", "StudentFinalGradesView"): ("student_id", "grades.view"),
    ("grading.views.final_grades", "StudentReportCardPDFView"): ("student_id", "reports.transcript.view"),
    ("academics.views.schedule_projection", "StudentScheduleProjectionListView"): ("student_id", "academics.schedule.view"),
    ("finance.views.transaction", "TransactionViewSet"): ("student_id", "billing.view"),
}
REFERENCE_READS = {
    ("academics.views.academic_year", "AcademicYearListView"),
    ("academics.views.academic_year", "AcademicYearDetailView"),
    ("academics.views.academic_year", "CurrentAcademicYearView"),
    ("academics.views.marking_period", "MarkingPeriodDetailView"),
    ("academics.views.marking_period", "MarkingPeriodListView"),
    ("academics.views.marking_period", "MarkingPeriodListAllView"),
    ("academics.views.semester", "SemesterListView"),
}


def parent_student_read_allowed(request, view):
    from students.authorization import permission_scope
    from users.parent_portal import verified_guardians
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        return False
    key = (view.__class__.__module__, view.__class__.__name__)
    if key in REFERENCE_READS:
        return bool(permission_scope(request, "academics.view"))
    if key == ("academics.views.section_time_slot", "SectionTimeSlotListView"):
        return bool(permission_scope(request, "academics.schedule.view") and verified_guardians(request.user).filter(
            student__enrollments__section_id=view.kwargs.get("section_id"),
            student__enrollments__active=True, student__enrollments__academic_year__current=True).exists())
    if key not in STUDENT_READS:
        return False
    if key[0] == "reports.views.students" and request.query_params.get("report_type") != "bio":
        return False
    argument, permission = STUDENT_READS[key]
    if not permission_scope(request, permission):
        return False
    if key[0] == "finance.views.transaction" and getattr(view, "action", None) != "student_transactions":
        return False
    if key[0] == "grading.views.final_grades" and request.query_params.get("status", "approved") != "approved":
        return False
    identifier = str(view.kwargs.get(argument) or "")
    if not identifier:
        return False
    match = Q(student__id_number=identifier) | Q(student__prev_id_number=identifier)
    try:
        match |= Q(student_id=UUID(identifier))
    except ValueError:
        pass
    if not verified_guardians(request.user).filter(match).exists():
        raise NotFound("Student does not exist.")
    return True
