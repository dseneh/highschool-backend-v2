"""
Management command to generate default assessments for gradebooks.

Usage:
    # Generate for all active academic years
    python manage.py generate_default_assessments
    
    # Generate for specific academic year
    python manage.py generate_default_assessments --year "2025-2026"
    
    # Generate for specific school
    python manage.py generate_default_assessments --school "school-id"
    
    # Dry run (preview only, don't create)
    python manage.py generate_default_assessments --dry-run
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from academics.models import AcademicYear
from grading.utils import (
    generate_default_assessments_for_academic_year,
    generate_default_assessments_for_gradebook
)
from grading.models import GradeBook


class Command(BaseCommand):
    help = 'Generate default assessments for gradebooks based on templates'

    def add_arguments(self, parser):
        parser.add_argument(
            '--year',
            type=str,
            help='Academic year name (e.g., "2025-2026")',
        )
        parser.add_argument(
            '--gradebook',
            type=str,
            help='Specific gradebook ID to generate for (ignores other filters)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Preview what would be created without actually creating',
        )
        parser.add_argument(
            '--active-only',
            action='store_true',
            default=True,
            help='Only process active academic years (default: True)',
        )

    @transaction.atomic
    def handle(self, *args, **options):
        dry_run = options['dry_run']
        year_name = options.get('year')
        gradebook_id = options.get('gradebook')
        active_only = options.get('active_only', True)

        # Specific gradebook mode
        if gradebook_id:
            return self._handle_single_gradebook(gradebook_id, dry_run)

        # Get academic years
        academic_years = AcademicYear.objects.all()
        
        if active_only:
            academic_years = academic_years.filter(active=True)
            
        if year_name:
            academic_years = academic_years.filter(name=year_name)
            if not academic_years.exists():
                raise CommandError(f'Academic year "{year_name}" not found')

        if not academic_years.exists():
            self.stdout.write(self.style.WARNING('No academic years found to process'))
            return

        # Process each academic year
        total_stats = {
            'gradebooks_processed': 0,
            'assessments_created': 0,
            'gradebooks_with_errors': []
        }

        for ay in academic_years:
            self.stdout.write(f'\nProcessing academic year: {ay.name}')
            
            if dry_run:
                self.stdout.write(self.style.WARNING('[DRY RUN MODE - No changes will be made]'))
                count = GradeBook.objects.filter(academic_year=ay, active=True).count()
                self.stdout.write(f'  Would process {count} gradebooks')
                continue

            stats = generate_default_assessments_for_academic_year(
                academic_year=ay
            )

            # Update totals
            total_stats['gradebooks_processed'] += stats['gradebooks_processed']
            total_stats['assessments_created'] += stats['assessments_created']
            total_stats['gradebooks_with_errors'].extend(stats['gradebooks_with_errors'])

            # Display stats for this academic year
            self.stdout.write(
                self.style.SUCCESS(
                    f"  ✓ Processed {stats['gradebooks_processed']} gradebooks, "
                    f"created {stats['assessments_created']} assessments"
                )
            )

            if stats['gradebooks_with_errors']:
                self.stdout.write(
                    self.style.ERROR(
                        f"  ✗ {len(stats['gradebooks_with_errors'])} gradebooks had errors"
                    )
                )
                for error in stats['gradebooks_with_errors']:
                    self.stdout.write(
                        self.style.ERROR(
                            f"    - {error['gradebook_name']}: {error['error']}"
                        )
                    )

        # Final summary
        self.stdout.write('\n' + '='*70)
        self.stdout.write(self.style.SUCCESS('SUMMARY:'))
        self.stdout.write(f"  Total gradebooks processed: {total_stats['gradebooks_processed']}")
        self.stdout.write(f"  Total assessments created: {total_stats['assessments_created']}")
        if total_stats['gradebooks_with_errors']:
            self.stdout.write(
                self.style.ERROR(
                    f"  Total gradebooks with errors: {len(total_stats['gradebooks_with_errors'])}"
                )
            )
        else:
            self.stdout.write(self.style.SUCCESS('  No errors!'))

    def _handle_single_gradebook(self, gradebook_id, dry_run):
        """Handle generation for a single gradebook."""
        try:
            gradebook = GradeBook.objects.select_related(
                'section', 'academic_year'
            ).get(id=gradebook_id)
        except GradeBook.DoesNotExist:
            raise CommandError(f'Gradebook with ID "{gradebook_id}" does not exist')

        self.stdout.write(f'Processing gradebook: {gradebook.name}')
        self.stdout.write(f'  Academic Year: {gradebook.academic_year.name}')

        if dry_run:
            from grading.utils import preview_default_assessments_for_gradebook
            
            self.stdout.write(self.style.WARNING('\n[DRY RUN MODE - Previewing only]'))
            preview = preview_default_assessments_for_gradebook(gradebook)
            
            self.stdout.write(f'\nWill create {len(preview["will_create"])} assessments:')
            for assessment in preview['will_create']:
                self.stdout.write(
                    f"  ✓ {assessment['name']} ({assessment['type']}) "
                    f"for {assessment['marking_period']}"
                )
            
            if preview['already_exists']:
                self.stdout.write(f'\n{len(preview["already_exists"])} assessments already exist:')
                for assessment in preview['already_exists']:
                    self.stdout.write(
                        f"  - {assessment['name']} ({assessment['type']}) "
                        f"for {assessment['marking_period']}"
                    )
            
            if preview['skipped_by_restrictions']:
                self.stdout.write(
                    self.style.WARNING(
                        f'\n{len(preview["skipped_by_restrictions"])} assessments '
                        'skipped due to restrictions:'
                    )
                )
                for assessment in preview['skipped_by_restrictions']:
                    self.stdout.write(
                        f"  ✗ {assessment['name']} ({assessment['type']}): "
                        f"{assessment['reason']}"
                    )
        else:
            created = generate_default_assessments_for_gradebook(gradebook)
            self.stdout.write(
                self.style.SUCCESS(f'\n✓ Created {len(created)} assessments')
            )
            for assessment in created:
                self.stdout.write(
                    f"  - {assessment.name} ({assessment.assessment_type.name}) "
                    f"for {assessment.marking_period.name}"
                )
