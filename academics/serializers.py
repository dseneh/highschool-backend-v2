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
        ]

    def to_representation(self, instance):
        response = super().to_representation(instance)
        return response


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


class SectionScheduleSerializer(serializers.ModelSerializer):
    class Meta:
        model = SectionSchedule
        fields = [
            "id",
            "section",
            "period_time",
            "period",
            "subject",
        ]

    def to_representation(self, instance):
        response = super().to_representation(instance)
        response["section"] = {
            "id": instance.section.id,
            "name": instance.section.name,
        }
        response["subject"] = {
            "id": instance.subject.id,
            "name": instance.subject.subject.name,
        }
        response["period"] = {
            "id": instance.period.id,
            "name": instance.period.name,
        }
        response["period_time"] = {
            "id": instance.period_time.id,
            "start_time": instance.period_time.start_time,
            "end_time": instance.period_time.end_time,
            "day_of_week": instance.period_time.day_of_week,
        }
        return response
