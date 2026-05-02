from django.contrib import admin

from .models import (
    AcademicYear,
    Division,
    GradeLevel,
    GradeLevelTuitionFee,
    MarkingPeriod,
    Period,
    PeriodTime,
    Section,
    SectionSchedule,
    SectionSubject,
    Semester,
    Subject,
)


# @admin.register(School)
# class SchoolAdmin(admin.ModelAdmin):
#     list_display = [
#         "id_number",
#         "name",
#         "workspace",
#         "school_type",
#         "status",
#         "address",
#     ]
#     search_fields = ["name", "workspace", "id_number"]
#     list_filter = ["school_type", "status", "country"]
#     readonly_fields = ["created_at", "updated_at"]


@admin.register(AcademicYear)
class AcademicYearAdmin(admin.ModelAdmin):
    list_display = ["name", "start_date", "end_date", "status"]
    search_fields = ["name"]
    list_filter = ["status", ]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(Semester)
class SemesterAdmin(admin.ModelAdmin):
    list_display = ["name", "academic_year", "start_date", "end_date"]
    search_fields = ["name"]
    list_filter = ["academic_year"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(MarkingPeriod)
class MarkingPeriodAdmin(admin.ModelAdmin):
    list_display = ["name", "semester", "start_date", "end_date"]
    search_fields = ["name"]
    list_filter = ["semester"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(Division)
class DivisionAdmin(admin.ModelAdmin):
    list_display = ["name", "description"]
    search_fields = ["name"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(GradeLevel)
class GradeLevelAdmin(admin.ModelAdmin):
    list_display = ["name", "level", "division"]
    search_fields = ["name"]
    list_filter = ["division", "level"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(GradeLevelTuitionFee)
class GradeLevelTuitionFeeAdmin(admin.ModelAdmin):
    list_display = ["grade_level", "amount"]
    search_fields = ["grade_level__name"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(Section)
class SectionAdmin(admin.ModelAdmin):
    list_display = ["name", "grade_level", "max_capacity"]
    search_fields = ["name"]
    list_filter = ["grade_level"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ["name", "code"]
    search_fields = ["name", "code"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(SectionSubject)
class SectionSubjectAdmin(admin.ModelAdmin):
    list_display = ["section", "subject"]
    search_fields = ["section__name", "subject__name"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(Period)
class PeriodAdmin(admin.ModelAdmin):
    list_display = ["name"]
    search_fields = ["name"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(PeriodTime)
class PeriodTimeAdmin(admin.ModelAdmin):
    list_display = ["period", "day_of_week", "start_time", "end_time"]
    search_fields = ["period__name"]
    list_filter = ["day_of_week"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(SectionSchedule)
class SectionScheduleAdmin(admin.ModelAdmin):
    list_display = ["section", "subject", "period_time"]
    search_fields = ["section__name", "subject__name"]
    list_filter = ["section__grade_level"]
    readonly_fields = ["created_at", "updated_at"]
