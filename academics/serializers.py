from datetime import date

from business.core.adapters.supporting_adapter import section_subject_has_grades
from core.models import Tenant
from finance.models import Currency
from django.contrib.auth import get_user_model
from django.db.models import Q
from rest_framework import serializers

from students.models.enrollment import Enrollment

from academics.models import (
    AcademicYear,
    Division,
    GradeBookScheduleProjection,
    GradeLevel,
    GradeLevelTuitionFee,
    MarkingPeriod,
    Period,
    PeriodTime,
    Section,
    SchoolCalendarEvent,
    SchoolCalendarSettings,
    SectionSchedule,
    StudentScheduleProjection,
    SectionTimeSlot,
    SectionSubject,
    Semester,
    Subject,
)
from staff.models import TeacherSchedule, TeacherSubject


class SchoolSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tenant
        fields = [
            "id",
            "name",
            "short_name",
            "id_number",
            "school_type",
            "funding_type",
            "slogan",
            "emis_number",
            "description",
            "workspace",
            "redirect_url",
            "date_est",
            "phone",
            "email",
            "website",
            "status",
            "address",
            "city",
            "state",
            "country",
            "postal_code",
            "logo",
            "logo_shape",
            "theme_color",
            "meta",
        ]

    def to_representation(self, instance: Tenant):
        response = super().to_representation(instance)
        response["full_address"] = instance.full_address()
        response["address_info"] = {
            "address": instance.address,
            "city": instance.city,
            "state": instance.state,
            "country": instance.country,
            "postal_code": instance.postal_code,
        }
        # if logo is none, return the default /images/logo.png with full URL
        request = self.context.get("request")
        if request and instance.logo:
            response["logo"] = request.build_absolute_uri(instance.logo.url)
        elif request and not instance.logo:
            response["logo"] = request.build_absolute_uri(
                "/media/images/default-logo.png"
            )
        return response


class WorkspaceSerializer(serializers.Serializer):
    """
    Dedicated serializer for workspace responses.
    Handles both admin workspace and tenant workspaces with a unified interface.
    
    Usage:
        # For admin workspace
        WorkspaceSerializer.get_admin_workspace()
        
        # For multiple schools
        WorkspaceSerializer(schools, many=True, context={'request': request}).data
    """
    
    id = serializers.CharField()
    name = serializers.CharField()
    short_name = serializers.CharField()
    workspace = serializers.CharField()
    workspace_id = serializers.CharField()
    id_number = serializers.CharField()
    type = serializers.CharField()
    logo = serializers.CharField(required=False, allow_null=True)
    
    def to_representation(self, instance):
        """
        Convert Tenant instance to workspace response format
        """
        if isinstance(instance, dict):
            return instance
        
        request = self.context.get('request')
        
        logo_url = None
        if instance.logo:
            logo_url = request.build_absolute_uri(instance.logo.url) if request else instance.logo.url
        elif request:
            logo_url = request.build_absolute_uri('/media/images/default-logo.png')
        
        return {
            'id': str(instance.id),
            'name': instance.name,
            'short_name': instance.short_name,
            'workspace': instance.workspace,
            'workspace_id': instance.workspace,
            'id_number': instance.id_number,
            'type': 'school',
            'logo': logo_url,
        }
    
    @staticmethod
    def get_admin_workspace():
        """
        Returns the admin workspace response
        """
        return {
            'id': 'admin',
            'name': 'Admin Panel',
            'short_name': 'Admin',
            'workspace': 'admin',
            'workspace_id': 'admin',
            'id_number': 'ADMIN',
            'type': 'admin',
            'logo': None,
        }
    
    @staticmethod
    def get_all_workspaces(schools_queryset=None, request=None):
        """
        Returns all workspaces (admin + all schools)
        
        Args:
            schools_queryset: QuerySet of schools (default: all schools)
            request: Request object for building absolute URLs
            
        Returns:
            list: List of workspace dictionaries
        """
        
        # Start with admin workspace
        workspaces = [WorkspaceSerializer.get_admin_workspace()]
        
        serializer = WorkspaceSerializer(
            schools_queryset,
            many=True,
            context={'request': request}
        )
        workspaces.extend(serializer.data)
        
        return workspaces


class SchoolUserListSerializer(serializers.ModelSerializer):
    # first_name = serializers.SerializerMethodField()
    # last_name = serializers.SerializerMethodField()
    # photo = serializers.SerializerMethodField()

    class Meta:
        model = get_user_model()
        fields = [
            "id",
            "id_number",
            "username",
            "email",
            "first_name",
            "last_name",
            "is_active",
            "is_staff",
            "is_superuser",
            "role",
            "status",
            "last_login",
            "last_password_updated",
            "photo",
            "date_joined",
        ]

    def to_representation(self, instance):
        response = super().to_representation(instance)
        request = self.context.get("request")

        response["first_name"] = (
            instance.student_account.first_name or instance.first_name
        )
        response["last_name"] = instance.student_account.last_name or instance.last_name
        response["gender"] = instance.student_account.gender or instance.gender

        # Build full URL for photo
        if instance.student_account and instance.student_account.photo:
            photo_url = instance.student_account.photo.url
            if request:
                response["photo"] = request.build_absolute_uri(photo_url)
            else:
                response["photo"] = photo_url
        elif instance.photo:
            photo_url = instance.photo.url
            if request:
                response["photo"] = request.build_absolute_uri(photo_url)
            else:
                response["photo"] = photo_url
        else:
            response["photo"] = None

        return response


class AcademicYearSerializer(serializers.ModelSerializer):
    class Meta:
        model = AcademicYear
        fields = [
            "id",
            "name",
            "start_date",
            "end_date",
            "current",
            "status",
        ]
        read_only_fields = ["id"]

    def to_representation(self, instance: AcademicYear):
        response = super().to_representation(instance)

        today = date.today()
        f = (
            Q(start_date__gte=instance.start_date) & Q(end_date__lte=instance.end_date)
        ) | Q(start_date__lte=today) & Q(end_date__gte=today)
        semesters = instance.semesters.filter(f)
        semester_serializer = SemesterSerializer(semesters, many=True, context=self.context)
        response["semesters"] = semester_serializer.data

        # Calculate duration in days
        total_days = (instance.end_date - instance.start_date).days + 1  # +1 to include end date
        days_elapsed = (today - instance.start_date).days
        days_elapsed = max(0, min(days_elapsed, total_days))  # Clamp between 0 and total_days
        completion_percentage = int((days_elapsed / total_days * 100)) if total_days > 0 else 0

        response["duration"] = {
            "total_days": total_days,
            "days_elapsed": days_elapsed,
            "completion_percentage": completion_percentage,
        }

        # Include stats if requested
        include_stats = self.context.get('include_stats', False)
        if include_stats:
            from django.db.models import Count, Q as DjangoQ
            from students.models import Enrollment
            from academics.models import Section, GradeLevel, MarkingPeriod
            
            response["stats"] = {
                "total_semesters": instance.semesters.count(),
                "total_marking_periods": MarkingPeriod.objects.filter(
                    semester__academic_year=instance
                ).count(),
                "total_sections": Section.objects.filter(
                    enrollments__academic_year=instance
                ).distinct().count(),
                "total_grade_levels": GradeLevel.objects.filter(
                    enrollments__academic_year=instance
                ).distinct().count(),
                "total_students": Enrollment.objects.filter(
                    academic_year=instance,
                    status__in=["active", "enrolled"]
                ).count(),
                "total_active_sections": Section.objects.filter(
                    enrollments__academic_year=instance,
                    active=True
                ).distinct().count(),
            }

        return response


class SemesterSerializer(serializers.ModelSerializer):
    class Meta:
        model = Semester
        fields = [
            "id",
            "name",
            "start_date",
            "end_date",
            # "current",
        ]

    def to_representation(self, instance: Semester):
        response = super().to_representation(instance)
        # Set 'is_current' to True if today is between start_date and end_date
        today = date.today()
        response["is_current"] = False
        if instance.start_date and instance.end_date:
            if instance.start_date <= today <= instance.end_date:
                response["is_current"] = True
        
        response["academic_year"] = (
            {
                "id": instance.academic_year.id,
                "name": instance.academic_year.name,
                "start_date": instance.academic_year.start_date,
                "end_date": instance.academic_year.end_date,
            }
            if instance.academic_year
            else None
        )
        
        # Include marking periods (pass context to skip semester field)
        marking_periods = instance.marking_periods.all().order_by('start_date')
        mp_context = {**self.context, 'skip_semester': True}
        response["marking_periods"] = MarkingPeriodSerializer(marking_periods, many=True, context=mp_context).data
        
        return response


class MarkingPeriodSerializer(serializers.ModelSerializer):
    class Meta:
        model = MarkingPeriod
        fields = [
            "id",
            "name",
            "short_name",
            "start_date",
            "end_date",
            "active"
            # "semester",
            # "current",
        ]

    def to_representation(self, instance):
        response = super().to_representation(instance)
        
        # Only include semester field if not being called from SemesterSerializer
        skip_semester = self.context.get('skip_semester', False)
        if not skip_semester and instance.semester:
            response["semester"] = {
                "id": instance.semester.id,
                "name": instance.semester.name,
                "start_date": instance.semester.start_date,
                "end_date": instance.semester.end_date,
            }
        
        # add a 'is_current' field if the current date is within the marking period dates
        today = date.today()
        response["is_current"] = instance.start_date <= today <= instance.end_date
        return response


class DivisionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Division
        fields = [
            "id",
            "name",
            "description",
        ]

    def to_representation(self, instance):
        response = super().to_representation(instance)
        return response


class GradeLevelSerializer(serializers.ModelSerializer):
    class Meta:
        model = GradeLevel
        fields = [
            "id",
            "name",
            "level",
            # "tuition_fee",
            "description",
            "division",
            "short_name",
            "active",
        ]

    def to_representation(self, instance):
        response = super().to_representation(instance)
        response["division"] = {
            "id": instance.division.id,
            "name": instance.division.name,
            "description": instance.division.description,
        }
        # Use prefetched currencies (already loaded in view)
        currency = Currency.objects.first()
        response["currency"] = {
            "id": currency.id,
            "name": currency.name,
            "symbol": currency.symbol,
        }
        # Use prefetched filtered_sections if available (set by view Prefetch), else fallback
        sections = getattr(instance, 'filtered_sections', None)
        if sections is None:
            sections = instance.sections.filter(active=True)
        
        serializers = SectionSerializer(sections, many=True)
        response["sections"] = [
            {
                "id": section["id"],
                "name": section["name"],
                "students": section["students"],
                "section_class": section.get("section_class")
            }
            for section in serializers.data
        ]
        # Use prefetched tuition_fees (already loaded in view)
        fees = instance.tuition_fees.all()
        response["tuition_fees"] = [
            {
                "id": fee.id,
                "fee_type": fee.targeted_student_type,
                "amount": fee.amount,
            }
            for fee in fees
        ]
        response["fees"] = response["tuition_fees"]
            
        response["status"] = "active" if instance.active else "disabled"
        return response


class GradeLevelTuitionFeeSerializer(serializers.ModelSerializer):
    class Meta:
        model = GradeLevelTuitionFee
        fields = [
            "id",
            "grade_level",
            "targeted_student_type",
            "amount",
        ]


class SectionSubjectSerializer(serializers.ModelSerializer):
    can_delete = serializers.SerializerMethodField()
    
    class Meta:
        model = SectionSubject
        fields = [
            "id",
            "section",
            "subject",
            "active",
            "can_delete",
        ]

    def get_can_delete(self, obj):
        """
        Determine if this section subject can be deleted.
        Returns False if it has grades entered, True otherwise.
        """
        from business.core.adapters import section_subject_has_grades
        return not section_subject_has_grades(obj)

    def to_representation(self, instance):
        response = super().to_representation(instance)
        response["section"] = {
            "id": instance.section.id,
            "name": instance.section.name,
        }
        response["grade_level"] = {
            "id": instance.section.grade_level.id,
            "name": instance.section.grade_level.name,
            "level": instance.section.grade_level.level,
        }
        response["subject"] = {
            "id": instance.subject.id,
            "name": instance.subject.name,
        }
        return response


class SectionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Section
        fields = [
            "id",
            "name",
            "description",
            "grade_level",
            "active",
            # "tuition_fee",
        ]

    def to_representation(self, instance):
        # Import here to avoid circular imports
        from finance.serializers import SectionFeeSerializer

        # count the number of students in the section for the current academic year
        count_students = Enrollment.objects.filter(
            section=instance, academic_year__current=True
        ).count()
        response = super().to_representation(instance)
        response["students"] = count_students
        response["grade_level"] = {
            "id": str(instance.grade_level.id),
            "name": instance.grade_level.name,
            "short_name": instance.grade_level.short_name,
            "level": instance.grade_level.level,
            "active": instance.grade_level.active,
        }
        response["section_class"] = instance.section_class

        subjects = instance.section_subjects.select_related("subject").all()
        response["subjects"] = [
            {
                "id": str(ss.id),  # section_subject ID
                "section": {
                    "id": str(instance.id),
                    "name": instance.name,
                },
                "subject": {
                    "id": str(ss.subject.id),
                    "name": ss.subject.name,
                },
                "grade_level": {
                    "id": str(instance.grade_level.id),
                    "name": instance.grade_level.name,
                    "level": instance.grade_level.level,
                },
                "active": ss.active,
                "can_delete": not section_subject_has_grades(ss),
            }
            for ss in subjects
        ]

        fees = instance.section_fees.select_related("general_fee")
        fee_serializers = SectionFeeSerializer(fees, many=True).data
        response["fees"] = []

        if fee_serializers:
            response["fees"] = [
                {
                    "id": fee["id"],
                    "name": fee["general_fee"]["name"],
                    "amount": fee["amount"],
                    "active": fee["active"],
                    "status": fee["status"],
                    "section": fee["section"],
                    "general_fee": fee["general_fee"],
                    "student_target": fee["general_fee"]["student_target"],
                }
                for fee in fee_serializers
            ]

        return response


class SubjectSerializer(serializers.ModelSerializer):
    # Computed fields for deletion logic
    can_delete = serializers.SerializerMethodField()
    can_force_delete = serializers.SerializerMethodField()
    must_deactivate = serializers.SerializerMethodField()
    has_grades = serializers.SerializerMethodField()
    has_scored_grades = serializers.SerializerMethodField()
    
    class Meta:
        model = Subject
        fields = [
            "id",
            "name",
            "code",
            "description",
            "active",
            "can_delete",
            "can_force_delete",
            "must_deactivate",
            "has_grades",
            "has_scored_grades",
        ]

    def get_has_grades(self, obj):
        """Check if any grades or gradebooks exist for this subject"""
        from grading.models import Grade, GradeBook
        has_gradebooks = GradeBook.objects.filter(subject=obj).exists()
        has_grade_records = Grade.objects.filter(subject=obj).exists()
        return has_gradebooks or has_grade_records
    
    def get_has_scored_grades(self, obj):
        """Check if any grades with scores exist for this subject"""
        from grading.models import Grade
        return Grade.objects.filter(subject=obj, score__isnull=False).exists()
    
    def get_can_delete(self, obj):
        """True if subject can be deleted without any issues (no grades/gradebooks exist)"""
        return not self.get_has_grades(obj)
    
    def get_can_force_delete(self, obj):
        """True if subject has grades/gradebooks but no scores (can delete with force=true)"""
        has_grades = self.get_has_grades(obj)
        has_scored_grades = self.get_has_scored_grades(obj)
        return has_grades and not has_scored_grades
    
    def get_must_deactivate(self, obj):
        """True if subject has grades with scores (must deactivate, cannot delete)"""
        return self.get_has_scored_grades(obj)

    def to_representation(self, instance):
        response = super().to_representation(instance)
        response["status"] = "active" if instance.active else "disabled"
        return response


class PeriodSerializer(serializers.ModelSerializer):
    class Meta:
        model = Period
        fields = [
            "id",
            "name",
            "description",
            "period_type",
        ]

    def to_representation(self, instance):
        response = super().to_representation(instance)
        return response


class SchoolCalendarSettingsSerializer(serializers.ModelSerializer):
    operating_day_labels = serializers.SerializerMethodField()
    school_year_start_date = serializers.SerializerMethodField()
    school_year_end_date = serializers.SerializerMethodField()

    class Meta:
        model = SchoolCalendarSettings
        fields = [
            "id",
            "operating_days",
            "operating_day_labels",
            "timezone",
            "school_year_start_date",
            "school_year_end_date",
            "active",
        ]

    def get_operating_day_labels(self, obj):
        labels = dict(SchoolCalendarSettings.DAY_OF_WEEK_CHOICES)
        return [labels[day] for day in obj.operating_days]

    def get_school_year_start_date(self, _obj):
        current_year = AcademicYear.get_current_academic_year()
        return current_year.start_date if current_year else None

    def get_school_year_end_date(self, _obj):
        current_year = AcademicYear.get_current_academic_year()
        return current_year.end_date if current_year else None


class SchoolCalendarEventSerializer(serializers.ModelSerializer):
    sections = serializers.PrimaryKeyRelatedField(
        queryset=Section.objects.all(),
        many=True,
        required=False,
    )
    section_details = serializers.SerializerMethodField()

    class Meta:
        model = SchoolCalendarEvent
        fields = [
            "id",
            "name",
            "description",
            "event_type",
            "recurrence_type",
            "start_date",
            "end_date",
            "all_day",
            "applies_to_all_sections",
            "sections",
            "section_details",
            "active",
        ]

    def validate(self, attrs):
        applies_to_all_sections = attrs.get(
            "applies_to_all_sections",
            self.instance.applies_to_all_sections if self.instance else True,
        )
        sections = attrs.get("sections")

        if not applies_to_all_sections and sections is not None and len(sections) == 0:
            raise serializers.ValidationError(
                {"sections": "Choose at least one section or mark event as applying to all sections."}
            )

        start_date = attrs.get("start_date") or (self.instance.start_date if self.instance else None)
        end_date = attrs.get("end_date") or (self.instance.end_date if self.instance else None)

        current_year = AcademicYear.get_current_academic_year()
        if current_year and start_date and end_date:
            if start_date < current_year.start_date:
                raise serializers.ValidationError(
                    {"start_date": "Start date cannot be before the current school year start date."}
                )

            if end_date > current_year.end_date:
                raise serializers.ValidationError(
                    {"end_date": "End date cannot be after the current school year end date."}
                )

        return attrs

    def get_section_details(self, obj):
        return [{"id": section.id, "name": section.name} for section in obj.sections.all()]

    def create(self, validated_data):
        sections = validated_data.pop("sections", [])
        event = super().create(validated_data)
        if not event.applies_to_all_sections:
            event.sections.set(sections)
        event.rebuild_occurrences()
        return event

    def update(self, instance, validated_data):
        sections = validated_data.pop("sections", None)
        event = super().update(instance, validated_data)
        if event.applies_to_all_sections:
            event.sections.clear()
        elif sections is not None:
            event.sections.set(sections)
        event.rebuild_occurrences()
        return event


class PeriodTimeSerializer(serializers.ModelSerializer):
    class Meta:
        model = PeriodTime
        fields = [
            "id",
            "start_time",
            "end_time",
            "day_of_week",
            "period",
        ]


class SectionTimeSlotSerializer(serializers.ModelSerializer):
    class Meta:
        model = SectionTimeSlot
        fields = [
            "id",
            "section",
            "period",
            "day_of_week",
            "start_time",
            "end_time",
            "sort_order",
            "active",
        ]

    def validate(self, attrs):
        instance = self.instance

        section = attrs.get("section") or (instance.section if instance else None)
        start_time = attrs.get("start_time") or (instance.start_time if instance else None)
        end_time = attrs.get("end_time") or (instance.end_time if instance else None)
        day_of_week = attrs.get("day_of_week") or (instance.day_of_week if instance else None)

        if not section or not start_time or not end_time or not day_of_week:
            return attrs

        settings = SchoolCalendarSettings.get_solo()
        if settings.operating_days and day_of_week not in settings.operating_days:
            raise serializers.ValidationError(
                {
                    "day_of_week": (
                        "Selected day is not configured as an operating school day."
                    )
                }
            )

        if start_time >= end_time:
            raise serializers.ValidationError(
                {"start_time": "Start time must be earlier than end time."}
            )

        overlap_exists = (
            SectionTimeSlot.objects.filter(
                section=section,
                day_of_week=day_of_week,
                active=True,
                start_time__lt=end_time,
                end_time__gt=start_time,
            )
            .exclude(id=instance.id if instance else None)
            .exists()
        )
        if overlap_exists:
            raise serializers.ValidationError(
                {
                    "start_time": (
                        "This section already has an overlapping time slot for the selected day."
                    )
                }
            )

        return attrs

    def to_representation(self, instance):
        response = super().to_representation(instance)
        response["period"] = {
            "id": instance.period.id,
            "name": instance.period.name,
            "period_type": instance.period.period_type,
        }
        response["section"] = {
            "id": instance.section.id,
            "name": instance.section.name,
        }
        response["is_recess"] = instance.period.period_type == Period.PeriodType.RECESS
        return response


class SectionScheduleSerializer(serializers.ModelSerializer):
    subject = serializers.PrimaryKeyRelatedField(
        queryset=SectionSubject.objects.all(),
        required=False,
        allow_null=True,
    )

    class Meta:
        model = SectionSchedule
        fields = [
            "id",
            "section",
            "section_time_slot",
            "period_time",
            "period",
            "subject",
        ]

    @staticmethod
    def _extract_time_window(section_time_slot, period_time):
        if section_time_slot is not None:
            return (
                section_time_slot.day_of_week,
                section_time_slot.start_time,
                section_time_slot.end_time,
            )
        if period_time is not None:
            return (
                period_time.day_of_week,
                period_time.start_time,
                period_time.end_time,
            )
        return (None, None, None)

    def validate(self, attrs):
        instance = self.instance

        section = attrs.get("section") or (instance.section if instance else None)
        period = attrs.get("period") or (instance.period if instance else None)
        section_time_slot = attrs.get("section_time_slot") or (
            instance.section_time_slot if instance else None
        )
        period_time = attrs.get("period_time") or (instance.period_time if instance else None)
        subject = attrs.get("subject") if "subject" in attrs else (instance.subject if instance else None)

        if not section or not period:
            return attrs

        if section_time_slot is None and period_time is None:
            raise serializers.ValidationError(
                {"section_time_slot": "A section time slot is required."}
            )

        if section_time_slot is not None:
            if section_time_slot.section_id != section.id:
                raise serializers.ValidationError(
                    {
                        "section_time_slot": (
                            "Selected section time slot does not belong to the selected section."
                        )
                    }
                )
            if section_time_slot.period_id != period.id:
                raise serializers.ValidationError(
                    {
                        "section_time_slot": (
                            "Selected section time slot does not belong to the selected period."
                        )
                    }
                )
        elif period_time is not None and period_time.period_id != period.id:
            raise serializers.ValidationError(
                {"period_time": "The selected PeriodTime does not belong to the selected Period."}
            )

        is_recess = period.period_type == Period.PeriodType.RECESS

        if is_recess:
            if subject is not None:
                raise serializers.ValidationError(
                    {"subject": "Recess periods cannot have a subject assignment."}
                )
            return attrs

        if subject is None:
            raise serializers.ValidationError(
                {"subject": "A subject assignment is required for class periods."}
            )

        if subject.section_id != section.id:
            raise serializers.ValidationError(
                {"subject": "Selected section subject does not belong to the selected section."}
            )

        teacher_assignments = TeacherSubject.objects.filter(
            section_subject=subject,
            active=True,
        ).select_related("teacher")

        if section_time_slot is not None:
            section_slot_conflict = (
                SectionSchedule.objects.filter(
                    section=section,
                    section_time_slot=section_time_slot,
                    active=True,
                )
                .exclude(id=instance.id if instance else None)
                .exists()
            )
        else:
            section_slot_conflict = (
                SectionSchedule.objects.filter(
                    section=section,
                    period_time=period_time,
                    active=True,
                )
                .exclude(id=instance.id if instance else None)
                .exists()
            )
        if section_slot_conflict:
            raise serializers.ValidationError(
                {
                    "section_time_slot": (
                        "This section already has a schedule entry for this section time slot."
                    )
                }
            )

        target_day, target_start, target_end = self._extract_time_window(
            section_time_slot,
            period_time,
        )

        for assignment in teacher_assignments:
            conflicts = (
                SectionSchedule.objects.filter(
                    subject__staff_teachers__teacher=assignment.teacher,
                    active=True,
                )
                .exclude(id=instance.id if instance else None)
                .select_related("section", "section_time_slot", "period_time")
            )

            for conflict in conflicts:
                conflict_day, conflict_start, conflict_end = self._extract_time_window(
                    conflict.section_time_slot,
                    conflict.period_time,
                )
                if conflict_day != target_day:
                    continue
                if not (target_start < conflict_end and target_end > conflict_start):
                    continue

                raise serializers.ValidationError(
                    {
                        "section_time_slot": (
                            f"Teacher {assignment.teacher.get_full_name()} is already scheduled "
                            f"for {conflict.section.name} during overlapping time."
                        )
                    }
                )

        return attrs

    def to_representation(self, instance):
        response = super().to_representation(instance)
        response["section"] = {
            "id": instance.section.id,
            "name": instance.section.name,
        }
        response["subject"] = (
            {
                "id": instance.subject.id,
                "name": instance.subject.subject.name,
            }
            if instance.subject
            else None
        )
        response["teacher"] = None
        if instance.subject:
            teacher_assignment = (
                instance.subject.staff_teachers.select_related("teacher").filter(active=True).first()
            )
            if teacher_assignment:
                response["teacher"] = {
                    "id": teacher_assignment.teacher.id,
                    "id_number": teacher_assignment.teacher.id_number,
                    "full_name": teacher_assignment.teacher.get_full_name(),
                }
        response["period"] = {
            "id": instance.period.id,
            "name": instance.period.name,
            "period_type": instance.period.period_type,
        }
        resolved_day = None
        resolved_start = None
        resolved_end = None

        if instance.section_time_slot:
            resolved_day = instance.section_time_slot.day_of_week
            resolved_start = instance.section_time_slot.start_time
            resolved_end = instance.section_time_slot.end_time
        elif instance.period_time:
            resolved_day = instance.period_time.day_of_week
            resolved_start = instance.period_time.start_time
            resolved_end = instance.period_time.end_time

        response["section_time_slot"] = (
            {
                "id": instance.section_time_slot.id,
                "day_of_week": instance.section_time_slot.day_of_week,
                "start_time": instance.section_time_slot.start_time,
                "end_time": instance.section_time_slot.end_time,
                "sort_order": instance.section_time_slot.sort_order,
            }
            if instance.section_time_slot
            else None
        )
        response["period_time"] = {
            "id": instance.period_time.id if instance.period_time else None,
            "start_time": resolved_start,
            "end_time": resolved_end,
            "day_of_week": resolved_day,
        }
        response["is_recess"] = instance.period.period_type == Period.PeriodType.RECESS
        return response


class TeacherScheduleProjectionSerializer(serializers.ModelSerializer):
    class Meta:
        model = TeacherSchedule
        fields = [
            "id",
            "teacher",
            "class_schedule",
        ]

    def to_representation(self, instance):
        response = super().to_representation(instance)

        section_time_slot = instance.class_schedule.section_time_slot
        period_time = instance.class_schedule.period_time
        day_of_week = section_time_slot.day_of_week if section_time_slot else (period_time.day_of_week if period_time else None)
        start_time = section_time_slot.start_time if section_time_slot else (period_time.start_time if period_time else None)
        end_time = section_time_slot.end_time if section_time_slot else (period_time.end_time if period_time else None)

        response["teacher"] = {
            "id": instance.teacher.id,
            "id_number": instance.teacher.id_number,
            "full_name": instance.teacher.get_full_name(),
        }
        response["section"] = {
            "id": instance.class_schedule.section.id,
            "name": instance.class_schedule.section.name,
        }
        response["subject"] = (
            {
                "id": instance.class_schedule.subject.id,
                "name": instance.class_schedule.subject.subject.name,
            }
            if instance.class_schedule.subject
            else None
        )
        response["period"] = {
            "id": instance.class_schedule.period.id,
            "name": instance.class_schedule.period.name,
            "period_type": instance.class_schedule.period.period_type,
        }
        response["time_window"] = {
            "day_of_week": day_of_week,
            "start_time": start_time,
            "end_time": end_time,
        }
        return response


class GradeBookScheduleProjectionSerializer(serializers.ModelSerializer):
    class Meta:
        model = GradeBookScheduleProjection
        fields = [
            "id",
            "class_schedule",
            "gradebook",
            "section",
            "section_subject",
            "subject",
            "period",
            "day_of_week",
            "start_time",
            "end_time",
        ]

    def to_representation(self, instance):
        response = super().to_representation(instance)
        response["gradebook"] = {
            "id": instance.gradebook.id,
            "name": instance.gradebook.name,
            "academic_year": {
                "id": instance.gradebook.academic_year.id,
                "name": instance.gradebook.academic_year.name,
            },
        }
        response["section"] = {
            "id": instance.section.id,
            "name": instance.section.name,
        }
        response["subject"] = {
            "id": instance.subject.id,
            "name": instance.subject.name,
        }
        response["period"] = {
            "id": instance.period.id,
            "name": instance.period.name,
            "period_type": instance.period.period_type,
        }
        response["section_subject"] = {
            "id": instance.section_subject.id,
            "subject": {
                "id": instance.section_subject.subject.id,
                "name": instance.section_subject.subject.name,
            },
        }
        return response


class StudentScheduleProjectionSerializer(serializers.ModelSerializer):
    class Meta:
        model = StudentScheduleProjection
        fields = [
            "id",
            "class_schedule",
            "enrollment",
            "student",
            "section",
            "section_subject",
            "subject",
            "period",
            "day_of_week",
            "start_time",
            "end_time",
        ]

    def to_representation(self, instance):
        response = super().to_representation(instance)
        response["student"] = {
            "id": instance.student.id,
            "id_number": instance.student.id_number,
            "full_name": instance.student.get_full_name(),
        }
        response["enrollment"] = {
            "id": instance.enrollment.id,
            "status": instance.enrollment.status,
            "academic_year": {
                "id": instance.enrollment.academic_year.id,
                "name": instance.enrollment.academic_year.name,
            },
        }
        response["section"] = {
            "id": instance.section.id,
            "name": instance.section.name,
        }
        response["subject"] = {
            "id": instance.subject.id,
            "name": instance.subject.name,
        }
        response["period"] = {
            "id": instance.period.id,
            "name": instance.period.name,
            "period_type": instance.period.period_type,
        }
        response["section_subject"] = {
            "id": instance.section_subject.id,
            "subject": {
                "id": instance.section_subject.subject.id,
                "name": instance.section_subject.subject.name,
            },
        }
        return response
