#!/usr/bin/env python
"""
Database setup script for development environment.

This script performs a complete database reset and setup:
1. Drops all database tables and schemas
2. Deletes all migration files
3. Creates fresh migrations
4. Runs shared schema migrations (migrate_schemas --shared)
5. Creates public tenant with admin user
6. Runs tenant schema migrations (migrate_schemas)
7. Creates a test superuser for development

Usage:
    python setup.py                    # Full setup with defaults
    python setup.py --skip-migrations  # Skip migration deletion/creation
    python setup.py --dry-run          # Show what would be done
    python setup.py --help             # Show help

Environment Variables:
    PUBLIC_TENANT_DOMAIN         Domain URL for public tenant (default: public.localhost)
    PUBLIC_TENANT_OWNER_EMAIL    Owner email for public tenant (default: admin@example.com)
    PUBLIC_TENANT_OWNER_PASSWORD Owner password for public tenant (default: admin123)
    PUBLIC_TENANT_OWNER_ID_NUMBER Owner id_number for public tenant (default: admin01)
    PUBLIC_TENANT_OWNER_USERNAME Owner username for public tenant (default: admin)
    TEST_USER_EMAIL              Test user email (default: testadmin@test.com)
    TEST_USER_PASSWORD           Test user password (default: testpass123)

WARNING: This will DELETE ALL DATA from the database. Use only in development!
"""

import os
import sys
import argparse
from pathlib import Path

# Add the project directory to Python path
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

# Set Django settings
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'api.settings')

import django
django.setup()

from django.conf import settings
from django.db import connection
from django.core.management import call_command


def find_all_apps():
    """Find all local apps with migrations directories"""
    apps = []
    for app in settings.INSTALLED_APPS:
        # Skip third-party apps
        if app.startswith('django.') or app.startswith('rest_framework') or \
           app.startswith('corsheaders') or app.startswith('drf_yasg') or \
           app.startswith('storages') or app.startswith('django_tenants') or \
           app.startswith('tenant_users'):
            continue
        
        try:
            app_module = __import__(app, fromlist=[''])
            app_path = Path(app_module.__file__).parent
            migrations_dir = app_path / 'migrations'
            
            if migrations_dir.exists():
                apps.append((app, migrations_dir))
        except (ImportError, AttributeError):
            continue
    
    return apps


def delete_migration_files(migrations_dir, dry_run=False):
    """Delete all migration files except __init__.py"""
    deleted = []
    
    for file in migrations_dir.iterdir():
        if file.is_file() and file.name != '__init__.py' and file.name.endswith('.py'):
            if not dry_run:
                file.unlink()
            deleted.append(file.name)
    
    return deleted


def drop_database(dry_run=False):
    """Drop all tables and schemas from the database"""
    if dry_run:
        print("[DRY RUN] Would drop all tables and schemas from the database")
        return
    
    print("Dropping all database tables and schemas...")
    
    with connection.cursor() as cursor:
        # Drop all tenant schemas (except public)
        cursor.execute("""
            SELECT schema_name 
            FROM information_schema.schemata 
            WHERE schema_name NOT IN ('public', 'pg_catalog', 'information_schema', 'pg_toast')
            AND schema_name NOT LIKE 'pg_%'
            ORDER BY schema_name;
        """)
        schemas = [row[0] for row in cursor.fetchall()]
        
        if schemas:
            print(f"  Found {len(schemas)} tenant schema(s) to drop")
            for schema in schemas:
                try:
                    cursor.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE;')
                    print(f"  ✓ Dropped schema: {schema}")
                except Exception as e:
                    print(f"  ✗ Error dropping schema {schema}: {e}")
        
        # Get all table names in public schema
        cursor.execute("""
            SELECT tablename 
            FROM pg_tables 
            WHERE schemaname = 'public'
            ORDER BY tablename;
        """)
        tables = [row[0] for row in cursor.fetchall()]
        
        if tables:
            print(f"  Found {len(tables)} table(s) in public schema to drop")
            for table in tables:
                try:
                    cursor.execute(f'DROP TABLE IF EXISTS "{table}" CASCADE;')
                    print(f"  ✓ Dropped table: {table}")
                except Exception as e:
                    print(f"  ✗ Error dropping table {table}: {e}")
        
        connection.commit()
        print("✓ Database cleared!\n")


def delete_migrations(dry_run=False):
    """Delete all migration files"""
    apps = find_all_apps()
    
    if not apps:
        print("No apps with migrations found.\n")
        return
    
    print(f"Deleting migration files from {len(apps)} app(s)...")
    total_deleted = 0
    
    for app_name, migrations_dir in apps:
        deleted = delete_migration_files(migrations_dir, dry_run=dry_run)
        if deleted:
            total_deleted += len(deleted)
            if dry_run:
                print(f"  [WOULD DELETE] {app_name}: {len(deleted)} file(s)")
            else:
                print(f"  ✓ {app_name}: {len(deleted)} file(s) deleted")
    
    if dry_run:
        print(f"[DRY RUN] Would delete {total_deleted} migration file(s)\n")
    else:
        print(f"✓ Deleted {total_deleted} migration file(s)\n")


def create_migrations(dry_run=False):
    """Create fresh migrations"""
    if dry_run:
        print("[DRY RUN] Would create new migrations\n")
        return
    
    print("Creating fresh migrations...")
    try:
        call_command('makemigrations', verbosity=1)
        print("✓ Migrations created!\n")
    except Exception as e:
        print(f"✗ Error creating migrations: {e}\n")
        raise


def migrate_shared_schema(dry_run=False):
    """Run shared schema migrations"""
    if dry_run:
        print("[DRY RUN] Would run shared schema migrations\n")
        return
    
    print("Running shared schema migrations...")
    try:
        call_command('migrate_schemas', '--shared', verbosity=1)
        print("✓ Shared schema migrated!\n")
    except Exception as e:
        print(f"✗ Error migrating shared schema: {e}\n")
        raise


def create_public_tenant(dry_run=False):
    """Create public tenant with admin user"""
    if dry_run:
        print("[DRY RUN] Would create public tenant\n")
        return
    
    print("Creating public tenant...")
    
    try:
        from core.models import Tenant
        from django_tenants.utils import get_public_schema_name
        from tenant_users.tenants.utils import create_public_tenant
        from tenant_users.tenants.models import ExistsError
        from common.status import UserAccountType, Roles
        from django.utils import timezone
        
        public_schema = get_public_schema_name()
        
        if Tenant.objects.filter(schema_name=public_schema).exists():
            print("  Public tenant already exists\n")
            return
        
        # Get configuration from environment or use defaults
        domain_url = os.environ.get('PUBLIC_TENANT_DOMAIN', 'public.localhost')
        owner_email = os.environ.get('PUBLIC_TENANT_OWNER_EMAIL', 'admin@example.com')
        owner_password = os.environ.get('PUBLIC_TENANT_OWNER_PASSWORD', 'admin123')
        owner_id_number = os.environ.get('PUBLIC_TENANT_OWNER_ID_NUMBER', 'admin01')
        owner_username = os.environ.get('PUBLIC_TENANT_OWNER_USERNAME', 'admin')
        owner_first_name = os.environ.get('PUBLIC_TENANT_OWNER_FIRST_NAME', 'Super')
        owner_last_name = os.environ.get('PUBLIC_TENANT_OWNER_LAST_NAME', 'Admin')
        
        # Prepare owner data
        from users.models import User
        user_fields = {f.name for f in User._meta.get_fields() if hasattr(f, 'name')}
        
        owner_extra = {"password": owner_password}
        
        if 'username' in user_fields:
            owner_extra["username"] = owner_username
        if 'id_number' in user_fields:
            owner_extra["id_number"] = owner_id_number
        if 'first_name' in user_fields:
            owner_extra["first_name"] = owner_first_name
        if 'last_name' in user_fields:
            owner_extra["last_name"] = owner_last_name
        if 'account_type' in user_fields:
            owner_extra["account_type"] = UserAccountType.GLOBAL
        if 'role' in user_fields:
            owner_extra["role"] = Roles.SUPERADMIN
        if 'gender' in user_fields:
            owner_extra["gender"] = "male"
        if 'is_default_password' in user_fields:
            owner_extra["is_default_password"] = False
        if 'last_password_updated' in user_fields:
            owner_extra["last_password_updated"] = timezone.now()
        
        try:
            public_tenant, domain, owner = create_public_tenant(
                domain_url=domain_url,
                owner_email=owner_email,
                is_superuser=True,
                is_staff=True,
                **owner_extra
            )
            print(f"  ✓ Public tenant created")
            print(f"    Domain: {domain_url}")
            print(f"    Owner: {owner_email} (username: {owner_username})")
            print(f"    Password: {owner_password}\n")
        except ExistsError:
            print("  Public tenant already exists\n")
    except Exception as e:
        print(f"✗ Error creating public tenant: {e}\n")
        raise


def migrate_tenant_schemas(dry_run=False):
    """Run tenant schema migrations"""
    if dry_run:
        print("[DRY RUN] Would run tenant schema migrations\n")
        return
    
    print("Running tenant schema migrations...")
    try:
        call_command('migrate_schemas', verbosity=1)
        print("✓ Tenant schemas migrated!\n")
    except Exception as e:
        print(f"✗ Error migrating tenant schemas: {e}\n")
        raise


def create_test_user(dry_run=False):
    """Create a test superuser for development"""
    if dry_run:
        print("[DRY RUN] Would create test superuser\n")
        return
    
    print("Creating test superuser...")
    
    try:
        from django.contrib.auth import get_user_model
        from common.status import UserAccountType, Roles
        import random
        
        User = get_user_model()
        
        email = os.environ.get('TEST_USER_EMAIL', 'testadmin@test.com')
        password = os.environ.get('TEST_USER_PASSWORD', 'testpass123')
        
        if User.objects.filter(email=email).exists():
            print(f"  Test user {email} already exists\n")
            return
        
        id_number = f"{random.randint(100000, 999999)}"
        
        user = User.objects.create_superuser(
            email=email,
            username=email,
            password=password,
            first_name="Test",
            last_name="Admin",
            id_number=id_number,
            account_type=UserAccountType.GLOBAL,
            role=Roles.SUPERADMIN
        )
        
        print(f"  ✓ Test superuser created")
        print(f"    Email: {email}")
        print(f"    Password: {password}\n")
    except Exception as e:
        print(f"✗ Error creating test user: {e}\n")
        raise


def main():
    parser = argparse.ArgumentParser(
        description='Complete database setup for development',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
This script performs a complete database reset and setup.
Use only in development environments!

Examples:
  python setup.py                    # Full setup
  python setup.py --skip-migrations  # Keep existing migrations
  python setup.py --dry-run          # Preview actions
        """
    )
    parser.add_argument(
        '--skip-migrations',
        action='store_true',
        help='Skip deletion and creation of migration files'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be done without making changes'
    )
    
    args = parser.parse_args()
    
    # Safety confirmation
    if not args.dry_run:
        print("\n" + "="*60)
        print("⚠️  DATABASE SETUP - DESTRUCTIVE OPERATION")
        print("="*60)
        print("\nThis will:")
        print("  1. DROP all database tables and schemas")
        print("  2. DELETE all migration files")
        print("  3. CREATE fresh migrations")
        print("  4. MIGRATE shared and tenant schemas")
        print("  5. CREATE public tenant and test user")
        print("\n⚠️  ALL EXISTING DATA WILL BE LOST!")
        print("\nUse only in development environments!\n")
        
        response = input("Type 'RESET DATABASE' to confirm: ")
        if response != 'RESET DATABASE':
            print("\nCancelled. No changes made.")
            sys.exit(0)
        print()
    
    print("="*60)
    print("STARTING DATABASE SETUP")
    print("="*60 + "\n")
    
    try:
        # Step 1: Drop database
        drop_database(dry_run=args.dry_run)
        
        # Step 2-4: Handle migrations
        if not args.skip_migrations:
            delete_migrations(dry_run=args.dry_run)
            create_migrations(dry_run=args.dry_run)
        else:
            print("Skipping migration deletion/creation\n")
        
        # Step 5: Migrate shared schema
        migrate_shared_schema(dry_run=args.dry_run)
        
        # Step 6: Create public tenant
        create_public_tenant(dry_run=args.dry_run)
        
        # Step 7: Migrate tenant schemas
        migrate_tenant_schemas(dry_run=args.dry_run)
        
        # Step 8: Create test user
        create_test_user(dry_run=args.dry_run)
        
        if args.dry_run:
            print("="*60)
            print("DRY RUN COMPLETE - No changes made")
            print("="*60)
        else:
            print("="*60)
            print("✓ DATABASE SETUP COMPLETE!")
            print("="*60)
            print("\nYou can now:")
            print("  - Start the server: python manage.py runserver")
            print("  - Access admin at: http://localhost:8000/admin/")
            print("  - Create test data: python manage.py seed_grading_data")
        print()
        
    except Exception as e:
        print("\n" + "="*60)
        print("✗ SETUP FAILED")
        print("="*60)
        print(f"\nError: {e}\n")
        sys.exit(1)


if __name__ == '__main__':
    main()
