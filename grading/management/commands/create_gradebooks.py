"""
Django management command to create gradebooks for existing sections and academic years.

This command will create gradebooks for each SectionSubject combination across all academic years,
ensuring that every subject taught in every section has a corresponding gradebook for each academic year.

Usage:
    python manage.py create_gradebooks
    python manage.py create_gradebooks --section-id SECTION_ID
    python manage.py create_gradebooks --academic-year-id ACADEMIC_YEAR_ID
    python manage.py create_gradebooks --school-id SCHOOL_ID
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from academics.models import AcademicYear, Section, SectionSubject
from grading.models import GradeBook
from users.models import CustomUser


class Command(BaseCommand):
    help = 'Create gradebooks for existing sections and academic years'

    def add_arguments(self, parser):
        parser.add_argument(
            '--section-id',
            type=str,
            help='Create gradebooks only for this specific section ID',
        )
        parser.add_argument(
            '--academic-year-id',
            type=str,
            help='Create gradebooks only for this specific academic year ID',
        )
        parser.add_argument(
            '--school-id',
            type=str,
            help='Create gradebooks only for sections in this specific school ID',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be created without actually creating',
        )
        parser.add_argument(
            '--calculation-method',
            type=str,
            choices=['average', 'weighted', 'cumulative'],
            default='average',
            help='Default calculation method for created gradebooks (default: average)',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        section_id = options.get('section_id')
        academic_year_id = options.get('academic_year_id')
        school_id = options.get('school_id')
        calculation_method = options['calculation_method']

        self.stdout.write(
            self.style.SUCCESS('Starting gradebook creation process...')
        )

        if dry_run:
            self.stdout.write(
                self.style.WARNING('DRY RUN MODE: No gradebooks will actually be created')
            )

        try:
            # Get a system user for created_by field (use first superuser or admin)
            system_user = CustomUser.objects.filter(is_superuser=True).first()
            if not system_user:
                system_user = CustomUser.objects.filter(is_staff=True).first()
            
            if not system_user:
                raise CommandError(
                    'No superuser or staff user found. Please create an admin user first.'
                )

            # Build querysets based on filters
            section_subjects = SectionSubject.objects.select_related(
                'section', 'subject', 'section__grade_level', 'section__grade_level__school'
            ).filter(active=True)

            academic_years = AcademicYear.objects.filter(active=True)

            # Apply filters
            if section_id:
                section_subjects = section_subjects.filter(section_id=section_id)
                
            if academic_year_id:
                academic_years = academic_years.filter(id=academic_year_id)
                

            # Get all combinations that need gradebooks
            combinations = []
            for section_subject in section_subjects:
                for academic_year in academic_years:
                    # In multi-tenant setup, all data is already scoped to current tenant
                    # No need to check school_id since foreign key was removed
                    combinations.append((section_subject, academic_year))

            if not combinations:
                self.stdout.write(
                    self.style.WARNING('No section-subject-academic year combinations found.')
                )
                return

            self.stdout.write(
                f'Found {len(combinations)} section-subject-academic year combinations to process.'
            )

            created_count = 0
            skipped_count = 0

            with transaction.atomic():
                for section_subject, academic_year in combinations:
                    # Generate gradebook name
                    gradebook_name = f"{section_subject.subject.name} - {section_subject.section.name} - {academic_year.name}"
                    
                    # Check if gradebook already exists
                    existing_gradebook = GradeBook.objects.filter(
                        section_subject=section_subject,
                        academic_year=academic_year
                    ).first()

                    if existing_gradebook:
                        skipped_count += 1
                        self.stdout.write(
                            self.style.WARNING(f'SKIPPED: {gradebook_name} (already exists)')
                        )
                        continue

                    if not dry_run:
                        # Create the gradebook
                        gradebook = GradeBook.objects.create(
                            section_subject=section_subject,
                            section=section_subject.section,  # Denormalized field
                            subject=section_subject.subject,  # Denormalized field
                            academic_year=academic_year,
                            name=gradebook_name,
                            calculation_method=calculation_method,
                            created_by=system_user,
                            updated_by=system_user,
                        )
                        created_count += 1
                        self.stdout.write(
                            self.style.SUCCESS(f'CREATED: {gradebook_name} (ID: {gradebook.id})')
                        )
                    else:
                        created_count += 1
                        self.stdout.write(
                            self.style.SUCCESS(f'WOULD CREATE: {gradebook_name}')
                        )

                if dry_run:
                    # Rollback the transaction in dry run mode
                    transaction.set_rollback(True)

            # Summary
            self.stdout.write('')
            self.stdout.write(self.style.SUCCESS('=== SUMMARY ==='))
            if dry_run:
                self.stdout.write(f'Would create: {created_count} gradebooks')
            else:
                self.stdout.write(f'Created: {created_count} gradebooks')
            self.stdout.write(f'Skipped (already exist): {skipped_count} gradebooks')
            self.stdout.write(f'Total processed: {created_count + skipped_count} combinations')

            if not dry_run and created_count > 0:
                self.stdout.write('')
                self.stdout.write(
                    self.style.SUCCESS(f'Successfully created {created_count} gradebooks!')
                )

        except Exception as e:
            raise CommandError(f'Error creating gradebooks: {str(e)}')