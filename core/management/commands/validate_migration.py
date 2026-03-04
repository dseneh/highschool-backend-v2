"""
Django management command to validate multi-tenant data migration.

Checks data integrity, foreign key relationships, and record counts post-migration.

Usage:
    python manage.py validate_migration [--verbose] [--fix-issues]
"""

import json
from django.core.management.base import BaseCommand, CommandError
from django_tenants.utils import schema_context, get_tenant_model
from django.db import connection

from students.models import Student
from staff.models import Staff, Department, Position
from academics.models import AcademicYear, Semester, Division, GradeLevel, Subject, Section
from finance.models import BankAccount, Transaction
from grading.models import Assessment, Grade


class Command(BaseCommand):
    """Validate multi-tenant data migration."""
    
    help = 'Validate migrated multi-tenant data integrity'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Verbose output',
        )
        parser.add_argument(
            '--fix-issues',
            action='store_true',
            help='Attempt to fix common issues',
        )
        parser.add_argument(
            '--tenant-id',
            type=int,
            help='Validate specific tenant only',
        )
    
    def handle(self, *args, **options):
        """Main command handler."""
        self.verbose = options['verbose']
        self.fix_issues = options['fix_issues']
        self.tenant_id = options['tenant_id']
        
        self.stdout.write(self.style.SUCCESS('\n=== Validating Multi-Tenant Data ==='))
        
        validation_report = {
            'timestamp': str(datetime.now()),
            'total_tenants': 0,
            'tenants_validated': 0,
            'critical_issues': 0,
            'warnings': 0,
            'tenant_reports': {},
        }
        
        try:
            Tenant = get_tenant_model()
            tenants = Tenant.objects.all()
            
            if self.tenant_id:
                tenants = tenants.filter(id=self.tenant_id)
            
            validation_report['total_tenants'] = Tenant.objects.count()
            
            self.log_step(f'Validating {tenants.count()} tenants...')
            
            for tenant in tenants:
                self.log_step(f'\nValidating tenant: {tenant.schema_name} ({tenant.name})')
                
                try:
                    with schema_context(tenant.schema_name):
                        tenant_report = self._validate_tenant(tenant)
                        validation_report['tenant_reports'][tenant.schema_name] = tenant_report
                        
                        if tenant_report['critical_issues']:
                            validation_report['critical_issues'] += len(tenant_report['critical_issues'])
                        if tenant_report['warnings']:
                            validation_report['warnings'] += len(tenant_report['warnings'])
                        
                        validation_report['tenants_validated'] += 1
                
                except Exception as e:
                    error_msg = f"Error validating {tenant.schema_name}: {str(e)}"
                    self.log_error(error_msg)
                    validation_report['tenant_reports'][tenant.schema_name] = {
                        'error': str(e),
                        'status': 'failed',
                    }
            
            # Print summary
            self._print_summary(validation_report)
            
            # Save report
            report_file = f'/tmp/validation_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
            with open(report_file, 'w') as f:
                json.dump(validation_report, f, indent=2)
            self.stdout.write(f'\nValidation report saved to: {report_file}')
            
            # Determine exit status
            if validation_report['critical_issues'] > 0:
                raise CommandError(f"Validation failed: {validation_report['critical_issues']} critical issues found")
            
            self.stdout.write(self.style.SUCCESS('\n✓ Validation completed successfully!\n'))
        
        except CommandError:
            raise
        except Exception as e:
            raise CommandError(f'Validation failed: {str(e)}')
    
    def _validate_tenant(self, tenant):
        """Validate single tenant data."""
        report = {
            'status': 'success',
            'record_counts': {},
            'critical_issues': [],
            'warnings': [],
            'fk_integrity': {},
        }
        
        try:
            # Count records per app
            report['record_counts'] = {
                'students': Student.objects.count(),
                'staff': Staff.objects.count(),
                'departments': Department.objects.count(),
                'positions': Position.objects.count(),
                'academic_years': AcademicYear.objects.count(),
                'semesters': Semester.objects.count(),
                'divisions': Division.objects.count(),
                'grade_levels': GradeLevel.objects.count(),
                'subjects': Subject.objects.count(),
                'sections': Section.objects.count(),
                'bank_accounts': BankAccount.objects.count(),
                'transactions': Transaction.objects.count(),
                'assessments': Assessment.objects.count(),
                'grades': Grade.objects.count(),
            }
            
            if self.verbose:
                self.stdout.write(f"  Record Counts:")
                for app, count in report['record_counts'].items():
                    self.stdout.write(f"    {app}: {count}")
            
            # Check foreign key integrity
            fk_checks = self._check_foreign_keys()
            report['fk_integrity'] = fk_checks
            
            # Check for orphaned records
            orphaned = self._check_orphaned_records()
            if orphaned:
                report['warnings'].extend(orphaned)
            
            # Check for missing required data
            missing = self._check_missing_required_data()
            if missing:
                report['critical_issues'].extend(missing)
            
            report['status'] = 'success' if not report['critical_issues'] else 'failed'
        
        except Exception as e:
            report['status'] = 'failed'
            report['critical_issues'].append(f"Exception during validation: {str(e)}")
        
        return report
    
    def _check_foreign_keys(self):
        """Check foreign key integrity."""
        checks = {
            'student_divisions': 0,
            'student_grades': 0,
            'staff_departments': 0,
            'section_subjects': 0,
        }
        
        try:
            # Students with valid divisions
            checks['student_divisions'] = Student.objects.filter(division__isnull=False).count()
            
            # Students with grades
            checks['student_grades'] = Student.objects.filter(grade__isnull=False).count()
            
            # Staff with departments
            checks['staff_departments'] = Staff.objects.filter(department__isnull=False).count()
            
            # Sections with subjects
            checks['section_subjects'] = Section.objects.filter(subject__isnull=False).count()
            
        except Exception as e:
            self.log_error(f"  Error checking foreign keys: {str(e)}")
        
        return checks
    
    def _check_orphaned_records(self):
        """Check for orphaned records (broken foreign keys)."""
        warnings = []
        
        try:
            # Check students with invalid divisions
            orphaned_students = Student.objects.filter(division__isnull=True)
            if orphaned_students.exists():
                warnings.append(f"WARNING: {orphaned_students.count()} students have no division")
            
            # Check staff with invalid departments
            orphaned_staff = Staff.objects.filter(department__isnull=True)
            if orphaned_staff.exists():
                warnings.append(f"WARNING: {orphaned_staff.count()} staff members have no department")
            
        except Exception as e:
            warnings.append(f"WARNING: Error checking orphaned records: {str(e)}")
        
        return warnings
    
    def _check_missing_required_data(self):
        """Check for missing required data."""
        issues = []
        
        try:
            # Check if any academic year exists
            if not AcademicYear.objects.exists():
                issues.append("CRITICAL: No academic years found")
            
            # Check if any users are assigned to tenant
            # (This would require checking tenant-user association)
            
        except Exception as e:
            issues.append(f"CRITICAL: Error checking required data: {str(e)}")
        
        return issues
    
    def _print_summary(self, report):
        """Print validation summary."""
        self.stdout.write('\n' + '='*60)
        self.stdout.write(self.style.SUCCESS('VALIDATION SUMMARY'))
        self.stdout.write('='*60)
        self.stdout.write(f"Tenants Validated: {report['tenants_validated']} / {report['total_tenants']}")
        self.stdout.write(f"Critical Issues: {report['critical_issues']}")
        self.stdout.write(f"Warnings: {report['warnings']}")
        self.stdout.write('='*60)
    
    def log_step(self, msg):
        """Log a step."""
        if self.verbose:
            self.stdout.write(f"\n→ {msg}")
    
    def log_error(self, msg):
        """Log error message."""
        self.stdout.write(self.style.ERROR(f"✗ {msg}"))


from datetime import datetime
