"""
Admin configuration for Settings models
"""

from django.contrib import admin
from .models import GradingSettings


@admin.register(GradingSettings)
class GradingSettingsAdmin(admin.ModelAdmin):
    """Admin for GradingSettings"""
    
    list_display = [
        'grading_style',
        'use_default_templates',
        'default_calculation_method',
        'use_letter_grades',
        'active',
        'updated_at',
    ]
    
    list_filter = [
        'grading_style',
        'use_default_templates',
        'default_calculation_method',
        'use_letter_grades',
        'active',
    ]
    
    search_fields = [
        'notes',
    ]
    
    fieldsets = (
        ('Grading Mode', {
            'fields': (
                'grading_style',
                'single_entry_assessment_name',
            ),
            'description': 'Choose between single-entry (final grades only) or multiple-entry (assessments) mode.'
        }),
        ('Multiple Entry Settings', {
            'fields': (
                'use_default_templates',
                'auto_calculate_final_grade',
                'default_calculation_method',
            ),
            'description': 'Settings for multiple-entry grading mode.'
        }),
        ('Grade Display', {
            'fields': (
                'use_letter_grades',
                'require_grade_approval',
            )
        }),
        ('Permissions', {
            'fields': (
                'allow_teacher_override',
                'lock_grades_after_semester',
            )
        }),
        ('Notes', {
            'fields': ('notes',),
            'classes': ('collapse',)
        }),
    )
    
    readonly_fields = ['created_at', 'updated_at', 'created_by', 'updated_by']
    
    def save_model(self, request, obj, form, change):
        """Auto-set created_by and updated_by"""
        if not change:
            obj.created_by = request.user
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)
