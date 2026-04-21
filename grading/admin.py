from django.contrib import admin
from .models import (
    GradeLetter, AssessmentType, GradeBook, 
    Assessment, Grade, HonorCategory
)


@admin.register(GradeLetter)
class GradeLetterAdmin(admin.ModelAdmin):
    list_display = ['letter',  'min_percentage', 'max_percentage', 'order', 'active']
    list_filter = [ 'active']
    search_fields = ['letter', 'school__name']
    ordering = [ 'order', '-max_percentage']
    
    fieldsets = (
        (None, {
            'fields': ( 'letter', 'min_percentage', 'max_percentage', 'order', 'active')
        }),
    )


@admin.register(HonorCategory)
class HonorCategoryAdmin(admin.ModelAdmin):
    list_display = ['label', 'min_average', 'max_average', 'order', 'active']
    list_filter = ['active']
    search_fields = ['label']
    ordering = ['order', '-max_average']

    fieldsets = (
        (None, {
            'fields': ('label', 'min_average', 'max_average', 'color', 'icon', 'order', 'active')
        }),
    )


@admin.register(AssessmentType)
class AssessmentTypeAdmin(admin.ModelAdmin):
    list_display = ['name',  'active', 'created_at']
    list_filter = [ 'active']
    search_fields = ['name', 'school__name']
    ordering = [ 'name']


@admin.register(GradeBook)
class GradeBookAdmin(admin.ModelAdmin):
    list_display = ['name', 'section_subject', 'calculation_method', 'academic_year', 'active']
    list_filter = ['calculation_method', 'academic_year', 'active']
    search_fields = ['name', 'section_subject__section__name']
    ordering = ['academic_year', 'name']


@admin.register(Assessment)
class AssessmentsAdmin(admin.ModelAdmin):
    list_display = ['name', 'gradebook', 'assessment_type', 'max_score', 'weight', 'is_calculated', 'due_date']
    list_filter = ['gradebook', 'assessment_type', 'is_calculated']
    search_fields = ['name', 'gradebook__name']
    ordering = ['gradebook', 'due_date', 'name']


@admin.register(Grade)
class GradeAdmin(admin.ModelAdmin):
    list_display = ['assessment', 'student', 'score', 'status', 'created_at']
    list_filter = ['status', 'assessment__gradebook']
    search_fields = ['student__first_name', 'student__last_name', 'assessment__name']
    ordering = ['assessment', 'student']
