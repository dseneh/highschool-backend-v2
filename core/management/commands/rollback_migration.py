"""
Django management command to rollback a data migration.

This command safely rolls back the data migration by:
1. Deleting all created tenant schemas
2. Resetting the public schema to pre-migration state
3. Removing tenant records from Tenant and Domain models

CAUTION: This will DELETE all data in tenant schemas!

Usage:
    python manage.py rollback_migration [--force] [--verbose]
"""

from datetime import datetime
from django.core.management.base import BaseCommand
from django_tenants.utils import get_tenant_model
from django.db import connection

from core.models import Domain


class Command(BaseCommand):
    """Rollback data migration from backend-v2."""
    
    help = 'Rollback data migration - DELETE all tenant schemas'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force rollback without confirmation',
        )
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Verbose output',
        )
        parser.add_argument(
            '--keep-public',
            action='store_true',
            help='Keep public schema (only delete tenant schemas)',
        )
    
    def handle(self, *args, **options):
        """Main command handler."""
        self.verbose = options['verbose']
        self.force = options['force']
        self.keep_public = options['keep_public']
        
        self.stdout.write(self.style.ERROR('=== Data Migration Rollback ==='))
        self.stdout.write(f'Timestamp: {datetime.now().isoformat()}')
        self.stdout.write(self.style.WARNING('CAUTION: This will DELETE all data in tenant schemas!'))
        
        # Confirm rollback
        if not self.force:
            response = input('\nType "ROLLBACK" to confirm: ')
            if response != 'ROLLBACK':
                self.stdout.write(self.style.SUCCESS('Rollback cancelled.'))
                return
        
        try:
            self.log_step('Starting rollback...')
            
            Tenant = get_tenant_model()
            tenants = list(Tenant.objects.all())
            
            if not tenants:
                self.stdout.write(self.style.WARNING('No tenants found to rollback.'))
                return
            
            self.log_step(f'Found {len(tenants)} tenants to delete')
            
            # Step 1: Delete tenant schemas
            self.log_step('Deleting tenant schemas...')
            deleted_count = 0
            for tenant in tenants:
                try:
                    self._delete_tenant_schema(tenant)
                    self.log_success(f"  ✓ Deleted schema: {tenant.schema_name}")
                    deleted_count += 1
                except Exception as e:
                    self.log_warning(f"  ✗ Failed to delete {tenant.schema_name}: {str(e)}")
            
            # Step 2: Delete Domain records
            self.log_step('Deleting domain records...')
            domains_deleted = Domain.objects.filter(
                tenant__in=tenants
            ).delete()[0]
            self.log_success(f"  ✓ Deleted {domains_deleted} domain records")
            
            # Step 3: Delete Tenant records
            self.log_step('Deleting tenant records...')
            tenants_deleted = Tenant.objects.filter(
                id__in=[t.id for t in tenants]
            ).delete()[0]
            self.log_success(f"  ✓ Deleted {tenants_deleted} tenant records")
            
            # Step 4: Optional - Reset public schema
            if not self.keep_public:
                self.log_step('Resetting public schema...')
                self._reset_public_schema()
                self.log_success('  ✓ Public schema reset')
            
            # Print summary
            self._print_summary(deleted_count)
            
            self.stdout.write(self.style.ERROR('\n⚠ Rollback completed!'))
            self.stdout.write(self.style.WARNING('All migrated data has been deleted.'))
            self.stdout.write('To restore, use a database backup from before migration.')
            
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'\n✗ Rollback failed: {str(e)}'))
            raise
    
    def _delete_tenant_schema(self, tenant):
        """Delete the schema for a tenant."""
        with connection.cursor() as cursor:
            # Drop the tenant schema
            cursor.execute(f"DROP SCHEMA IF EXISTS {tenant.schema_name} CASCADE")
            
            if self.verbose:
                self.stdout.write(f"      Schema deleted: {tenant.schema_name}")
    
    def _reset_public_schema(self):
        """Reset the public schema to clean state."""
        with connection.cursor() as cursor:
            # Delete all Tenant records (already done above, but ensure clean state)
            cursor.execute("""
                DELETE FROM tenants_tenant
                WHERE schema_name NOT IN ('public')
            """)
            
            # Delete all Domain records (already done above)
            cursor.execute("""
                DELETE FROM tenants_domain
                WHERE tenant_id IS NOT NULL
            """)
            
            if self.verbose:
                self.stdout.write("      Public schema cleaned")
    
    def _print_summary(self, deleted_count):
        """Print rollback summary."""
        self.stdout.write('\n' + '='*60)
        self.stdout.write(self.style.ERROR('ROLLBACK SUMMARY'))
        self.stdout.write('='*60)
        self.stdout.write(f"Schemas Deleted: {deleted_count}")
        self.stdout.write(f"Timestamp: {datetime.now().isoformat()}")
        self.stdout.write('='*60)
    
    def log_step(self, msg):
        """Log a step."""
        if self.verbose:
            self.stdout.write(f"\n→ {msg}")
        else:
            self.stdout.write(msg)
    
    def log_success(self, msg):
        """Log success message."""
        self.stdout.write(self.style.SUCCESS(msg))
    
    def log_warning(self, msg):
        """Log warning message."""
        self.stdout.write(self.style.WARNING(msg))
