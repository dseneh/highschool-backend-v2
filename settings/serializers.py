"""
Serializers for Settings models.

Handles data validation and serialization for Settings API endpoints.
"""

from rest_framework import serializers
from .models import GradingSettings, GradingStyleChoices


class GradingSettingsOut(serializers.ModelSerializer):
    """
    Read-only serializer for GradingSettings.

    Returns grading settings with nested school information and display names.
    """

    school = serializers.SerializerMethodField()
    grading_style_display = serializers.CharField(
        source="get_grading_style_display", read_only=True
    )
    calculation_method_display = serializers.SerializerMethodField()

    class Meta:
        model = GradingSettings
        fields = [
            "id",
            "active",
            "school",
            "grading_style",
            "grading_style_display",
            "single_entry_assessment_name",
            "use_default_templates",
            "auto_calculate_final_grade",
            "default_calculation_method",
            "calculation_method_display",
            "require_grade_approval",
            "require_grade_review",
            "use_letter_grades",
            "display_assessment_on_single_entry",
            "allow_assessment_delete",
            "allow_assessment_create",
            "allow_assessment_edit",
            "allow_teacher_override",
            "lock_grades_after_semester",
            "display_grade_status",
            "cumulative_average_calculation",
            "notes",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_school(self, obj):
        """Return school as nested dictionary with id and name."""
        school = getattr(obj, "school", None)
        if not school:
            return None

        return {
            "id": school.id,
            "name": school.name,
        }

    def get_calculation_method_display(self, obj):
        """Return human-readable calculation method name."""
        methods = {
            "average": "Simple Average",
            "weighted": "Weighted Average",
        }
        return methods.get(
            obj.default_calculation_method, obj.default_calculation_method
        )


class GradingSettingsIn(serializers.ModelSerializer):
    """
    Input serializer for creating/updating GradingSettings.

    Validates input data and enforces business rules.
    """

    class Meta:
        model = GradingSettings
        fields = [
            "grading_style",
            "single_entry_assessment_name",
            "use_default_templates",
            "auto_calculate_final_grade",
            "default_calculation_method",
            "require_grade_approval",
            "use_letter_grades",
            "allow_teacher_override",
            "lock_grades_after_semester",
            "cumulative_average_calculation",
            "notes",
        ]

    def validate(self, data):
        """
        Validate grading settings data.

        Single entry mode automatically disables template usage.
        """
        grading_style = data.get("grading_style")

        # If single entry, ensure we don't use templates
        if grading_style == GradingStyleChoices.SINGLE_ENTRY:
            data["use_default_templates"] = False

        return data
