from django.urls import path

from students.views.student import StudentImportView, StudentWithdrawView, StudentReinstateView
from students.views.distributions import (
    get_grade_level_distribution,
    get_payment_status_distribution,
    get_attendance_distribution,
    get_section_distribution,
    get_payment_summary,
    get_top_students_by_grade,
)

from .views import AttendanceDetailView  # StudentEnrollmentBillDetailView,
from .views import (
    AttendanceListView,
    AttendanceSectionRosterView,
    BillRecreationPreviewView,
    BillRecreationView,
    BillRecreationStatusView,
    BillSummaryMetadataView,
    BillSummaryQuickStatsView,
    EnrollmentDetailView,
    EnrollmentListView,
    # GradeBookDetailView,  # Removed - use grading app
    # GradeBookListView,  # Removed - use grading app
    # GradeBookStatusView,  # Removed - use grading app
    # SectionGradeBookByMarkingPeriodView,  # Removed - use grading app
    StudentBillSummaryView,
    StudentBillSummaryDownloadView,
    StudentBillingPDFView,
    StudentConcessionDetailView,
    StudentConcessionListCreateView,
    StudentConcessionStatsView,
    StudentContactListView,
    StudentContactDetailView,
    StudentDetailView,
    StudentEnrollmentBillListView,
    StudentGuardianListView,
    StudentGuardianDetailView,
    StudentSummaryView,
    # StudentGradesView,  # Removed - use grading app
    StudentListView,
)

urlpatterns = [
    path(
        "students/",
        StudentListView.as_view(),
        name="student_list",
    ),
    path(
        "students/summary/",
        StudentSummaryView.as_view(),
        name="student_summary",
    ),
    path("students/<str:id>/", StudentDetailView.as_view(), name="student_detail"),
    path(
        "students/<str:id>/withdraw/",
        StudentWithdrawView.as_view(),
        name="student_withdraw",
    ),
    path(
        "students/<str:id>/reinstate/",
        StudentReinstateView.as_view(),
        name="student_reinstate",
    ),
    path(
        "students/<str:student_id>/enrollments/",
        EnrollmentListView.as_view(),
        name="student_enrollment_list",
    ),
    path(
        "enrollments/<str:id>/",
        EnrollmentDetailView.as_view(),
        name="student_enrollment_detail",
    ),
    path(
        "students/<str:student_id>/attendance/",
        AttendanceListView.as_view(),
        name="student_attendance_list",
    ),
    path(
        "attendance/<str:id>/",
        AttendanceDetailView.as_view(),
        name="student_attendance_detail",
    ),
    path(
        "sections/<str:section_id>/attendance/",
        AttendanceSectionRosterView.as_view(),
        name="section_attendance_roster",
    ),
    # OLD GRADEBOOK ENDPOINT - Migrated to grading app
    # path(
    #     "students/<str:student_id>/gradebooks/",
    #     StudentGradesView.as_view(),
    #     name="student_grades",
    # ),
    # Student bill endpoints
    path(
        "students/<str:student_id>/bills/",
        StudentEnrollmentBillListView.as_view(),
        name="student_bills",
    ),
    path(
        "students/<str:student_id>/bills/download-pdf/",
        StudentBillingPDFView.as_view(),
        name="student_billing_pdf",
    ),
    path(
        "concessions/<str:academic_year_id>/stats/",
        StudentConcessionStatsView.as_view(),
        name="student_concession_stats",
    ),
    path(
        "concessions/academic-years/<str:academic_year_id>/",
        StudentConcessionListCreateView.as_view(),
        name="student_concession_list_create",
    ),
    path(
        "concessions/<str:id>/",
        StudentConcessionDetailView.as_view(),
        name="student_concession_detail",
    ),
    # Bill recreation endpoints
    path(
        "students/bills/recreate/",
        BillRecreationView.as_view(),
        name="bill_recreation",
    ),
    path(
        "students/bills/recreate/preview/",
        BillRecreationPreviewView.as_view(),
        name="bill_recreation_preview",
    ),
    path(
        "students/bills/recreate/status/<str:task_id>/",
        BillRecreationStatusView.as_view(),
        name="bill_recreation_status",
    ),
    # Bill summary endpoints
    path(
        "bill-summary/",
        StudentBillSummaryView.as_view(),
        name="student_bill_summary",
    ),
    path(
        "bill-summary/download/",
        StudentBillSummaryDownloadView.as_view(),
        name="student_bill_summary_download",
    ),
    path(
        "bill-summary/metadata/",
        BillSummaryMetadataView.as_view(),
        name="bill_summary_metadata",
    ),
    path(
        "bill-summary/quick-stats/",
        BillSummaryQuickStatsView.as_view(),
        name="bill_summary_quick_stats",
    ),
    # path("enrollments/<str:enrollment_id>/bills/", StudentEnrollmentBillListView.as_view(), name="enrollment_bills"),
    # path("bills/<str:pk>/", StudentEnrollmentBillDetailView.as_view(), name="bill_detail"),
    # path("enrollments/<str:enrollment_id>/gradebooks/", GradeBookListView.as_view(), name="student_grade_book_list"),
    # path("enrollments/<str:enrollment_id>/marking-periods/<str:marking_period_id>/gradebooks/", GradeBookByMarkingPeriodView.as_view(), name="student_grade_book_by_marking_period"),
    # path("enrollments/<str:enrollment_id>/subjects/<str:subject_id>/gradebooks/", GradeBookBySubjectView.as_view(), name="student_grade_book_by_subject"),
    
    # OLD GRADEBOOK ENDPOINTS - Migrated to grading app
    # path(
    #     "gradebooks/<str:id>/",
    #     GradeBookDetailView.as_view(),
    #     name="student_grade_book_detail",
    # ),
    # path(
    #     "gradebooks/<str:id>/status/",
    #     GradeBookStatusView.as_view(),
    #     name="student_grade_book_status",
    # ),
    # path(
    #     "sections/<str:section_id>/gradebooks/",
    #     SectionGradeBookByMarkingPeriodView.as_view(),
    #     name="class_gradebook_by_marking_period",
    # ),
    # path(
    #     "academic-years/<str:academic_year_id>/marking-periods/<str:marking_period_id>/sections/<str:section_id>/subjects/<str:subject_id>/gradebooks/",
    #     SectionGradeBookByMarkingPeriodView.as_view(),
    #     name="class_gradebook_by_marking_period",
    # ),
    path(
        "grade-levels/<str:grade_level_id>/student-uploads/",
        StudentImportView.as_view(),
        name="student_import",
    ),
    # Student contacts
    path(
        "students/<str:student_id>/contacts/",
        StudentContactListView.as_view(),
        name="student_contact_list",
    ),
    path(
        "contacts/<str:id>/",
        StudentContactDetailView.as_view(),
        name="student_contact_detail",
    ),
    # Student guardians
    path(
        "students/<str:student_id>/guardians/",
        StudentGuardianListView.as_view(),
        name="student_guardian_list",
    ),
    path(
        "guardians/<str:id>/",
        StudentGuardianDetailView.as_view(),
        name="student_guardian_detail",
    ),
    # path(
    #     "academic-years/<str:academic_year_id>/sections/<str:section_id>/subjects/<str:subject_id>/gradebooks/",
    #     StudentGradeTableView.as_view(),
    #     name="student_grade_table",
    # ),
    # path(
    #     "academic-years/<str:academic_year_id>/students/<str:student_id>/gradebooks/",
    #     StudentGradesBySubjectView.as_view(),
    #     name="student_grades_by_subject",
    # ),
    # path(
    #     "student-grade-table/",
    #     StudentGradeTableView.as_view(),
    #     name="student_grade_table",
    # ),
    
    # Dashboard distribution endpoints
    path(
        "students/distributions/grade-level/",
        get_grade_level_distribution,
        name="grade_level_distribution",
    ),
    path(
        "students/distributions/payment-status/",
        get_payment_status_distribution,
        name="payment_status_distribution",
    ),
    path(
        "students/distributions/attendance/",
        get_attendance_distribution,
        name="attendance_distribution",
    ),
    path(
        "students/distributions/sections/",
        get_section_distribution,
        name="section_distribution",
    ),
    path(
        "students/distributions/payment-summary/",
        get_payment_summary,
        name="payment_summary",
    ),
    path(
        "students/distributions/top-students/",
        get_top_students_by_grade,
        name="top_students_by_grade",
    ),
]
