from django.contrib import admin

from .models import (
    Department,
    Staff,
    Position,
    PositionCategory,
    TeacherSchedule,
    TeacherSection,
    TeacherSubject,
)


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "active"]
    search_fields = ["name", "code"]
    list_filter = ["active"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(PositionCategory)
class PositionCategoryAdmin(admin.ModelAdmin):
    list_display = ["name", "active"]
    search_fields = ["name"]
    list_filter = ["active"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(Position)
class PositionAdmin(admin.ModelAdmin):
    list_display = [
        "title",
        "category",
        "department",
        "teaching_role",
        "active",
    ]
    search_fields = ["title", "code", "description"]
    list_filter = [
        "category",
        "department",
        "teaching_role",
        "employment_type",
        "active",
    ]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(Staff)
class StaffAdmin(admin.ModelAdmin):
    list_display = [
        "id_number",
        "first_name",
        "last_name",
        "email",
        "current_position_display",
        "primary_department",
        "status",
    ]
    search_fields = ["id_number", "first_name", "last_name", "email"]
    list_filter = ["primary_department", "status", "gender"]
    readonly_fields = ["created_at", "updated_at", "id_number"]

    def current_position_display(self, obj):
        position = obj.current_position
        return position.title if position else "-"

    current_position_display.short_description = "Current Position"


@admin.register(TeacherSection)
class TeacherSectionAdmin(admin.ModelAdmin):
    list_display = ["teacher", "section"]
    search_fields = ["teacher__first_name", "teacher__last_name", "section__name"]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(TeacherSubject)
class TeacherSubjectAdmin(admin.ModelAdmin):
    list_display = ["teacher", "section_subject", "subject"]
    search_fields = [
        "teacher__first_name",
        "teacher__last_name",
        "subject__name",
        "section_subject__section__name",
    ]
    readonly_fields = ["created_at", "updated_at"]


@admin.register(TeacherSchedule)
class TeacherScheduleAdmin(admin.ModelAdmin):
    list_display = ["teacher", "class_schedule"]
    search_fields = ["teacher__first_name", "teacher__last_name"]
    list_filter = []
    readonly_fields = ["created_at", "updated_at"]

