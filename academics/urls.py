from django.urls import path

from academics.views.grade_level_tuition import GradeLevelTuitionFeesDetailView

from .views import *

urlpatterns = [
    # path(
    #     "workspaces/",
    #     WorkspaceListView.as_view(),
    #     name="list-workspace",
    # ),
    # path(
    #     "workspaces/<str:workspace_id>/",
    #     VerifyWorkspaceView.as_view(),
    #     name="verify-workspace",
    # ),
    path(
        "academic-years/",
        AcademicYearListView.as_view(),
        name="academic-year-list",
    ),
    path(
        "academic-years/current/",
        CurrentAcademicYearView.as_view(),
        name="current-academic-year",
    ),
    path(
        "school-calendar/settings/",
        SchoolCalendarSettingsView.as_view(),
        name="school-calendar-settings",
    ),
    path(
        "school-calendar/events/",
        SchoolCalendarEventListView.as_view(),
        name="school-calendar-event-list",
    ),
    path(
        "school-calendar/events/<str:id>/",
        SchoolCalendarEventDetailView.as_view(),
        name="school-calendar-event-detail",
    ),
    path(
        "academic-years/<str:id>/",
        AcademicYearDetailView.as_view(),
        name="academic-year-detail",
    ),
    # Semester
    path(
        "semesters/",
        SemesterListView.as_view(),
        name="semester-list",
    ),
    path("semesters/<str:id>/", SemesterDetailView.as_view(), name="semester-detail"),
    # Section Schedule
    path(
        "sections/<str:section_id>/class-schedules/",
        SectionScheduleListView.as_view(),
        name="class-schedule-list",
    ),
    path(
        "sections/<str:section_id>/calendar/",
        SectionCalendarProjectionView.as_view(),
        name="section-calendar-projection",
    ),
    path(
        "sections/<str:section_id>/time-slots/",
        SectionTimeSlotListView.as_view(),
        name="section-time-slot-list",
    ),
    path(
        "sections/<str:section_id>/time-slots/copy/",
        SectionTimeSlotCopyView.as_view(),
        name="section-time-slot-copy",
    ),
    path(
        "sections/<str:section_id>/time-slots/generate/",
        SectionTimeSlotGenerateView.as_view(),
        name="section-time-slot-generate",
    ),
    path(
        "section-time-slots/<str:id>/",
        SectionTimeSlotDetailView.as_view(),
        name="section-time-slot-detail",
    ),
    path(
        "class-schedules/<str:id>/",
        SectionScheduleDetailView.as_view(),
        name="class-schedule-detail",
    ),
    path(
        "schedule-projections/teachers/<str:teacher_id>/",
        TeacherScheduleProjectionListView.as_view(),
        name="teacher-schedule-projection-list",
    ),
    path(
        "schedule-projections/gradebooks/<str:gradebook_id>/",
        GradeBookScheduleProjectionListView.as_view(),
        name="gradebook-schedule-projection-list",
    ),
    path(
        "schedule-projections/students/<str:student_id>/",
        StudentScheduleProjectionListView.as_view(),
        name="student-schedule-projection-list",
    ),
    # Section
    path(
        "grade-levels/<str:grade_level_id>/sections/",
        SectionListView.as_view(),
        name="sections-list",
    ),
    path("sections/<str:id>/", SectionDetailView.as_view(), name="sections-detail"),
    # Subject
    path(
        "subjects/",
        SubjectListView.as_view(),
        name="subject-list",
    ),
    path("subjects/<str:id>/", SubjectDetailView.as_view(), name="subject-detail"),
    # Section Subject
    path(
        "sections/<str:section_id>/section-subjects/",
        SectionSubjectListView.as_view(),
        name="sections-subject-list",
    ),
    path(
        "section-subjects/<str:id>/",
        SectionSubjectDetailView.as_view(),
        name="sections-subject-detail",
    ),
    # Period
    path(
        "periods/", PeriodListView.as_view(), name="period-list"
    ),
    path("periods/<str:id>/", PeriodDetailView.as_view(), name="period-detail"),
    # Period Time
    path(
        "periods/<str:period_id>/period-times/",
        PeriodTimeListView.as_view(),
        name="period-time-list",
    ),
    path(
        "period-times/<str:id>/",
        PeriodTimeDetailView.as_view(),
        name="period-time-detail",
    ),
    # Division
    path(
        "divisions/",
        DivisionListView.as_view(),
        name="division-list",
    ),
    path("divisions/<str:id>/", DivisionDetailView.as_view(), name="division-detail"),
    # Grade Level
    path(
        "grade-levels/",
        GradeLevelListView.as_view(),
        name="grade-level-list",
    ),
    path(
        "grade-levels/<str:id>/",
        GradeLevelDetailView.as_view(),
        name="grade-level-detail",
    ),
    # marking_period
    path(
        "marking-periods/",
        MarkingPeriodListAllView.as_view(),
        name="marking_period-list",
    ),
    path(
        "semesters/<str:semester_id>/marking-periods/",
        MarkingPeriodListView.as_view(),
        name="marking_period-list",
    ),
    path(
        "marking-periods/",
        MarkingPeriodListAllView.as_view(),
        name="marking_period-list-all",
    ),
    path(
        "marking-periods/<str:id>/",
        MarkingPeriodDetailView.as_view(),
        name="marking_period-detail",
    ),
    path(
        "grade-levels/<str:id>/tuition/",
        GradeLevelTuitionFeesDetailView.as_view(),
        name="tuition_fee-detail",
    ),
]
