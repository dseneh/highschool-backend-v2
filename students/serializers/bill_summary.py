from rest_framework import serializers

from students.models import Student


class BillSummaryGradeLevelSerializer(serializers.Serializer):
    """Serializer for grade level bill summary grouped by enrolled_as"""
    
    # Grade level fields
    section__grade_level__id = serializers.CharField()  # Changed to CharField for UUID support
    section__grade_level__name = serializers.CharField()
    section__grade_level__level = serializers.IntegerField()
    
    # Enrollment type
    enrolled_as = serializers.CharField()
    
    # Summary fields
    student_count = serializers.IntegerField()
    total_bills = serializers.DecimalField(max_digits=15, decimal_places=2, allow_null=True)
    total_concessions = serializers.DecimalField(max_digits=15, decimal_places=2, allow_null=True, required=False)
    total_paid = serializers.DecimalField(max_digits=15, decimal_places=2, allow_null=True)
    avg_bill_per_student = serializers.DecimalField(max_digits=10, decimal_places=2, allow_null=True)
    
    # Computed fields
    balance = serializers.SerializerMethodField()
    percent_paid = serializers.SerializerMethodField()
    # enrolled_as_display = serializers.SerializerMethodField()
    
    def get_balance(self, obj):
        """Calculate balance (total_bills - total_paid)"""
        total_bills = float(obj.get('total_bills') or 0)
        total_paid = float(obj.get('total_paid') or 0)
        return round(total_bills - total_paid, 2)
    
    def get_percent_paid(self, obj):
        """Calculate percentage of bills that have been paid"""
        total_bills = float(obj.get('total_bills') or 0)
        total_paid = float(obj.get('total_paid') or 0)
        
        if total_bills == 0:
            return 0.0
        
        percent = (total_paid / total_bills) * 100
        return round(percent, 2)
    
    # def get_enrolled_as_display(self, obj):
    #     """Get display name for enrolled_as"""
    #     enrolled_as = obj.get('enrolled_as', '').lower()
    #     display_map = {
    #         'new': 'New',
    #         'transferred': 'Transferred',
    #         'returning': 'Returning'
    #     }
    #     return display_map.get(enrolled_as, enrolled_as.capitalize())
    
    def to_representation(self, instance):
        """Transform the data to a more readable format"""
        data = super().to_representation(instance)
        
        # Restructure the data
        return {
            'grade_level': {
                'id': data['section__grade_level__id'],
                'name': data['section__grade_level__name'],
                'level': data['section__grade_level__level']
            },
            'enrolled_as': data['enrolled_as'],
            'student_count': data['student_count'],
            'total_bills': float(data['total_bills'] or 0),
            'total_concessions': float(data.get('total_concessions') or 0),
            'total_paid': float(data['total_paid'] or 0),
            'balance': data['balance'],
            'percent_paid': data['percent_paid'],
            'avg_bill_per_student': float(data['avg_bill_per_student'] or 0)
        }


class BillSummarySectionSerializer(serializers.Serializer):
    """Serializer for section bill summary grouped by enrolled_as"""
    
    # Section fields
    section__id = serializers.CharField()  # Changed to CharField for UUID support
    section__name = serializers.CharField()
    
    # Enrollment type
    enrolled_as = serializers.CharField()
    
    # Summary fields
    student_count = serializers.IntegerField()
    total_bills = serializers.DecimalField(max_digits=15, decimal_places=2, allow_null=True)
    total_concessions = serializers.DecimalField(max_digits=15, decimal_places=2, allow_null=True, required=False)
    total_paid = serializers.DecimalField(max_digits=15, decimal_places=2, allow_null=True)
    avg_bill_per_student = serializers.DecimalField(max_digits=10, decimal_places=2, allow_null=True)
    
    # Computed fields
    balance = serializers.SerializerMethodField()
    percent_paid = serializers.SerializerMethodField()
    # enrolled_as_display = serializers.SerializerMethodField()
    
    def get_balance(self, obj):
        """Calculate balance (total_bills - total_paid)"""
        total_bills = float(obj.get('total_bills') or 0)
        total_paid = float(obj.get('total_paid') or 0)
        return round(total_bills - total_paid, 2)
    
    def get_percent_paid(self, obj):
        """Calculate percentage of bills that have been paid"""
        total_bills = float(obj.get('total_bills') or 0)
        total_paid = float(obj.get('total_paid') or 0)
        
        if total_bills == 0:
            return 0.0
        
        percent = (total_paid / total_bills) * 100
        return round(percent, 2)
    
    def get_enrolled_as_display(self, obj):
        """Get display name for enrolled_as"""
        enrolled_as = obj.get('enrolled_as', '').lower()
        display_map = {
            'new': 'New',
            'transferred': 'Transferred',
            'returning': 'Returning'
        }
        return display_map.get(enrolled_as, enrolled_as.capitalize())
    
    def to_representation(self, instance):
        """Transform the data to a more readable format"""
        data = super().to_representation(instance)
        
        # Restructure the data
        return {
            'section': {
                'id': data['section__id'],
                'name': data['section__name']
            },
            'enrolled_as': data['enrolled_as'],
            # 'enrolled_as_display': data['enrolled_as_display'],
            'student_count': data['student_count'],
            'total_bills': float(data['total_bills'] or 0),
            'total_concessions': float(data.get('total_concessions') or 0),
            'total_paid': float(data['total_paid'] or 0),
            'balance': data['balance'],
            'percent_paid': data['percent_paid'],
            'avg_bill_per_student': float(data['avg_bill_per_student'] or 0)
        }

class BillSummaryStudentSerializer(serializers.ModelSerializer):
    """Serializer for student bill summary"""
    
    total_bills = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)
    total_concessions = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True, required=False)
    total_paid = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)
    balance = serializers.SerializerMethodField()
    percent_paid = serializers.SerializerMethodField()
    enrollment_info = serializers.SerializerMethodField()
    full_name = serializers.SerializerMethodField()
    detailed_billing = serializers.SerializerMethodField()
    # enrolled_as_display = serializers.SerializerMethodField()
    
    class Meta:
        model = Student
        fields = [
            'id',
            'id_number',
            'first_name',
            'last_name',
            'full_name',
            'enrollment_info',
            # 'enrolled_as',
            'total_bills',
            'total_concessions',
            'total_paid',
            'balance',
            'percent_paid',
            'detailed_billing'
        ]
    
    def get_balance(self, obj):
        """Calculate balance (total_bills - total_paid)"""
        total_bills = float(obj.total_bills or 0)
        total_paid = float(obj.total_paid or 0)
        return round(total_bills - total_paid, 2)
    
    def get_percent_paid(self, obj):
        """Calculate percentage of bills that have been paid"""
        total_bills = float(obj.total_bills or 0)
        total_paid = float(obj.total_paid or 0)
        
        if total_bills == 0:
            return 0.0
        
        percent = (total_paid / total_bills) * 100
        return round(percent, 2)
    
    def get_full_name(self, obj):
        """Get full name of student"""
        return obj.get_full_name()
    
    def to_representation(self, instance):
        """Transform the data to ensure amounts are floats"""
        data = super().to_representation(instance)
        
        # Convert decimal amounts to float
        if data.get('total_bills') is not None:
            data['total_bills'] = float(data['total_bills'])
        else:
            data['total_bills'] = 0.0

        if data.get('total_concessions') is not None:
            data['total_concessions'] = float(data['total_concessions'])
        else:
            data['total_concessions'] = 0.0
            
        if data.get('total_paid') is not None:
            data['total_paid'] = float(data['total_paid'])
        else:
            data['total_paid'] = 0.0
            
        return data
    
    def get_enrolled_as_display(self, obj):
        """Get enrolled_as display for current enrollment"""
        context = self.context
        academic_year = context.get('academic_year')
        section = context.get('section')
        
        if academic_year and section:
            enrollment = obj.enrollments.filter(
                academic_year=academic_year,
                section=section
            ).first()
            
            if enrollment:
                enrolled_as = enrollment.enrolled_as.lower()
                display_map = {
                    'new': 'New',
                    'transferred': 'Transferred',
                    'returning': 'Returning'
                }
                return display_map.get(enrolled_as, enrolled_as.capitalize())
        
        return None
    
    def get_enrollment_info(self, obj):
        """Get enrollment information for the current academic year and section"""
        context = self.context
        academic_year = context.get('academic_year')
        section = context.get('section')
        
        if academic_year and section:
            enrollment = obj.enrollments.filter(
                academic_year=academic_year,
                section=section
            ).first()
            
            if enrollment:
                return {
                    'id': enrollment.id,
                    'status': enrollment.status,
                    'date_enrolled': enrollment.date_enrolled,
                    'enrolled_as': enrollment.enrolled_as,
                    # 'enrolled_as_display': self.get_enrolled_as_display(obj)
                }
        
        return None
    
    def get_detailed_billing(self, obj):
        """Get detailed billing breakdown"""
        context = self.context
        academic_year = context.get('academic_year')
        
        if not academic_year:
            return {}
        
        enrollment = obj.enrollments.filter(academic_year=academic_year).first()
        if not enrollment:
            return {}
        
        # Get bill breakdown by type
        bills = enrollment.student_bills.all()
        
        # Categorize bills
        tuition_bills = bills.filter(type__in=['tuition', 'Tuition Fee', 'Tuition'])
        fee_bills = bills.filter(type__in=['fee', 'other', 'general', 'General'])
        
        tuition_total = sum(bill.amount for bill in tuition_bills)
        fees_total = sum(bill.amount for bill in fee_bills)
        
        # Get payment breakdown by status
        transactions = obj.transactions.filter(
            academic_year=academic_year,
            type__type='income'
        )
        
        approved_payments = sum(
            t.amount for t in transactions if t.status == 'approved'
        )
        pending_payments = sum(
            t.amount for t in transactions if t.status == 'pending'
        )
        
        return {
            'tuition_fees': float(tuition_total),
            'other_fees': float(fees_total),
            'total_concessions': float(getattr(obj, 'total_concessions', 0) or 0),
            'approved_payments': float(approved_payments),
            'pending_payments': float(pending_payments),
            'projected_balance': float(
                tuition_total
                + fees_total
                - (getattr(obj, 'total_concessions', 0) or 0)
                - approved_payments
                - pending_payments
            )
        }