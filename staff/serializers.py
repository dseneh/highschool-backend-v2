from rest_framework import serializers
from users.models import User
from academics.models import SectionSubject, Subject, SectionSchedule

from common.serializers import PhotoURLMixin
from .models import (
    Staff,
    Position,
    PositionCategory,
    Department,
    TeacherSection,
    TeacherSubject,
    TeacherSchedule,
)


class DepartmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Department
        fields = [
            "id",
            "name",
            "code",
            "description",
            "active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def to_representation(self, instance):
        response = super().to_representation(instance)
        return response


class PositionCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = PositionCategory
        fields = [
            "id",
            "name",
            "description",
            "active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def to_representation(self, instance):
        response = super().to_representation(instance)
        return response


class PositionSerializer(serializers.ModelSerializer):
    category = serializers.SerializerMethodField()
    department = serializers.SerializerMethodField()

    class Meta:
        model = Position
        fields = [
            "id",
            "title",
            "code",
            "description",
            "category",
            "department",
            "level",
            "employment_type",
            "compensation_type",
            "salary_min",
            "salary_max",
            "teaching_role",
            "active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]
    def get_category(self, obj):
        if obj.category:
            return {
                "id": obj.category.id,
                "name": obj.category.name,
            }
        return None

    def get_department(self, obj):
        if obj.department:
            return {
                "id": obj.department.id,
                "name": obj.department.name,
                "code": obj.department.code,
            }
        return None

    def to_representation(self, instance):
        response = super().to_representation(instance)
        return response


class StaffSerializer(PhotoURLMixin, serializers.ModelSerializer):
    hire_date = serializers.DateField(required=True, allow_null=False)
    id_number = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    # Explicitly define position and primary_department as PrimaryKeyRelatedField
    # This tells the serializer to accept UUIDs and convert them to model instances
    position = serializers.PrimaryKeyRelatedField(
        queryset=Position.objects.all(),
        required=False,
        allow_null=True
    )
    primary_department = serializers.PrimaryKeyRelatedField(
        queryset=Department.objects.all(),
        required=False,
        allow_null=True
    )
    manager = serializers.PrimaryKeyRelatedField(
        queryset=Staff.objects.all(),
        required=False,
        allow_null=True
    )

    class Meta:
        model = Staff
        fields = [
            "id",
            "id_number",
            "first_name",
            "middle_name",
            "last_name",
            "date_of_birth",
            "gender",
            "email",
            "phone_number",
            "address",
            "city",
            "state",
            "postal_code",
            "country",
            "place_of_birth",
            "status",
            "photo",
            "hire_date",
            "position",
            "primary_department",
            "manager",
            "is_teacher",
            "suspension_date",
            "suspension_reason",
            "termination_date",
            "termination_reason",
        ]
        read_only_fields = ["id"]
    
    def validate_manager(self, value):
        """Validate that the manager assignment is valid (no circular dependencies)"""
        if not value:
            return value
        
        # Get the instance being updated (if it exists)
        instance = self.instance
        if not instance:
            # If creating new, we can't validate against self yet
            return value
        
        # Check if manager assignment is valid
        is_valid, error_msg = instance.can_be_manager_of(value)
        if not is_valid:
            raise serializers.ValidationError(error_msg)
        
        return value

    def to_representation(self, instance):
        response = super().to_representation(instance)
        response["full_name"] = instance.get_full_name()

        # Photo URL is automatically handled by PhotoURLMixin

        response["position"] = None

        if instance.position:
            response["position"] = {
                "id": instance.position.id,
                "title": instance.position.title,
                "description": instance.position.description,
            }

        response["primary_department"] = None

        if instance.primary_department:
            response["primary_department"] = {
                "id": instance.primary_department.id,
                "name": instance.primary_department.name,
                "code": instance.primary_department.code,
            }

        # Serialize manager if present
        response["manager"] = None

        if instance.manager:
            response["manager"] = {
                "id": instance.manager.id,
                "id_number": instance.manager.id_number,
                "full_name": instance.manager.get_full_name(),
                "email": instance.manager.email,
            }

        user_account = None
        if instance.user_account_id_number or instance.id_number:
            user_account = User.objects.filter(
                id_number=instance.user_account_id_number or instance.id_number
            ).first()

        response["user_account"] = (
            {
                "id": user_account.id,
                "id_number": user_account.id_number,
                "username": user_account.username,
                "first_name": instance.first_name,
                "last_name": instance.last_name,
                "email": user_account.email,
                "is_active": user_account.is_active,
                "is_staff": user_account.is_staff,
                "role": user_account.role,
                "status": user_account.status,
                "last_login": user_account.last_login,
                "last_password_updated": user_account.last_password_updated,
                "account_type": user_account.account_type,
            }
            if user_account
            else None
        )

        return response


class StaffDetailSerializer(StaffSerializer):
    class Meta(StaffSerializer.Meta):
        fields = StaffSerializer.Meta.fields

    def to_representation(self, instance):
        response = super().to_representation(instance)

        # Add sections assigned to this teacher
        sections = instance.classes.select_related(
            "section", "section__grade_level"
        ).all()
        response["sections"] = [
            {
                "id": ts.section.id,
                "name": ts.section.name,
                "grade_level": (
                    {
                        "id": ts.section.grade_level.id,
                        "name": ts.section.grade_level.name,
                    }
                    if ts.section.grade_level
                    else None
                ),
            }
            for ts in sections
        ]

        # Add subjects assigned to this teacher (section-scoped)
        subjects = instance.subjects.select_related(
            "subject",
            "section_subject",
            "section_subject__section",
            "section_subject__section__grade_level",
            "section_subject__subject",
        ).all()
        response["subjects"] = [
            {
                "id": ts.id,
                "section_subject": (
                    {
                        "id": ts.section_subject.id,
                        "section": {
                            "id": ts.section_subject.section.id,
                            "name": ts.section_subject.section.name,
                            "grade_level": (
                                {
                                    "id": ts.section_subject.section.grade_level.id,
                                    "name": ts.section_subject.section.grade_level.name,
                                }
                                if ts.section_subject.section.grade_level
                                else None
                            ),
                        },
                        "subject": {
                            "id": ts.section_subject.subject.id,
                            "name": ts.section_subject.subject.name,
                        },
                    }
                    if ts.section_subject
                    else None
                ),
                "subject": {
                    "id": ts.subject.id,
                    "name": ts.subject.name,
                }
                if ts.subject
                else None,
            }
            for ts in subjects
        ]

        # Build schedules from assigned section-subject mappings so schedule rows
        # are automatically tied to teacher subject assignments.
        section_subject_ids = list(
            instance.subjects.filter(section_subject__isnull=False, active=True)
            .values_list("section_subject_id", flat=True)
        )
        schedules = SectionSchedule.objects.select_related(
            "section",
            "section__grade_level",
            "period",
            "period_time",
            "subject",
            "subject__subject",
        ).filter(subject_id__in=section_subject_ids, active=True)

        response["schedules"] = [
            {
                "id": sched.id,
                "class_schedule": {
                    "id": sched.id,
                    "section": (
                        {
                            "id": sched.section.id,
                            "name": sched.section.name,
                        }
                        if sched.section
                        else None
                    ),
                    "subject": (
                        {
                            "id": sched.subject.id,
                            "name": sched.subject.subject.name,
                        }
                        if sched.subject
                        else None
                    ),
                    "period": (
                        {
                            "id": sched.period.id,
                            "name": sched.period.name,
                            "period_type": sched.period.period_type,
                        }
                        if sched.period
                        else None
                    ),
                    "period_time": (
                        {
                            "id": sched.period_time.id,
                            "start_time": sched.period_time.start_time,
                            "end_time": sched.period_time.end_time,
                            "day_of_week": sched.period_time.day_of_week,
                        }
                        if sched.period_time
                        else None
                    ),
                    "is_recess": sched.period.period_type == "recess" if sched.period else False,
                },
            }
            for sched in schedules
        ]

        return response


class TeacherSectionSerializer(serializers.ModelSerializer):
    class Meta:
        model = TeacherSection
        fields = [
            "id",
            "teacher",
            "section",
        ]
        read_only_fields = ["id"]

    def to_representation(self, instance):
        response = super().to_representation(instance)
        response["teacher"] = {
            "id": instance.teacher.id,
            "id_number": instance.teacher.id_number,
            "full_name": instance.teacher.get_full_name(),
        }
        if instance.section:
            response["section"] = {
                "id": instance.section.id,
                "name": instance.section.name,
                "grade_level": (
                    {
                        "id": instance.section.grade_level.id,
                        "name": instance.section.grade_level.name,
                    }
                    if instance.section.grade_level
                    else None
                ),
            }
        return response


class TeacherSubjectSerializer(serializers.ModelSerializer):
    subject = serializers.PrimaryKeyRelatedField(
        queryset=Subject.objects.all(),
        required=False,
        allow_null=True,
    )
    section_subject = serializers.PrimaryKeyRelatedField(
        queryset=SectionSubject.objects.all(),
        required=False,
        allow_null=True,
    )

    class Meta:
        model = TeacherSubject
        fields = [
            "id",
            "teacher",
            "subject",
            "section_subject",
        ]
        read_only_fields = ["id"]

    def validate(self, attrs):
        section_subject = attrs.get("section_subject")
        subject = attrs.get("subject")

        if not section_subject and not subject:
            raise serializers.ValidationError(
                {"section_subject": "This field is required."}
            )

        if section_subject:
            attrs["subject"] = section_subject.subject

        return attrs

    def to_representation(self, instance):
        response = super().to_representation(instance)
        response["teacher"] = {
            "id": instance.teacher.id,
            "id_number": instance.teacher.id_number,
            "full_name": instance.teacher.get_full_name(),
        }
        if instance.section_subject:
            response["section_subject"] = {
                "id": instance.section_subject.id,
                "section": {
                    "id": instance.section_subject.section.id,
                    "name": instance.section_subject.section.name,
                    "grade_level": (
                        {
                            "id": instance.section_subject.section.grade_level.id,
                            "name": instance.section_subject.section.grade_level.name,
                        }
                        if instance.section_subject.section.grade_level
                        else None
                    ),
                },
                "subject": {
                    "id": instance.section_subject.subject.id,
                    "name": instance.section_subject.subject.name,
                },
            }
        if instance.subject:
            response["subject"] = {
                "id": instance.subject.id,
                "name": instance.subject.name,
            }
        return response


class TeacherScheduleSerializer(serializers.ModelSerializer):
    class Meta:
        model = TeacherSchedule
        fields = [
            "id",
            "class_schedule",
            "teacher",
        ]
        read_only_fields = ["id"]

    def to_representation(self, instance):
        response = super().to_representation(instance)
        response["teacher"] = {
            "id": instance.teacher.id,
            "id_number": instance.teacher.id_number,
            "full_name": instance.teacher.get_full_name(),
        }
        if instance.class_schedule:
            response["class_schedule"] = {
                "id": instance.class_schedule.id,
                "section": (
                    instance.class_schedule.section.name
                    if instance.class_schedule.section
                    else None
                ),
                "period": (
                    instance.class_schedule.period.name
                    if instance.class_schedule.period
                    else None
                ),
            }
        return response

