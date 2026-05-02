#!/usr/bin/env python
"""
Complete database reset script - DESTRUCTIVE!

This script:
1. Drops ALL database tables and schemas
2. Deletes all migration files
3. Creates fresh migrations
4. Runs shared schema migrations
5. Creates public tenant
6. Creates superadmin with full config
7. Runs tenant schema migrations

Usage:
    python reset_database.py                 # Interactive reset
    python reset_database.py --force         # Skip confirmation
    python reset_database.py --dry-run       # Show what would happen

⚠️  WARNING: This will DELETE ALL DATA from the database. Use only in development!
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
from django.contrib.auth import get_user_model
from common.status import Roles, UserAccountType
from django_tenants.utils import get_public_schema_name
from django.utils import timezone


def delete_all_schemas(dry_run=False):
    """Drop all tenant schemas (keep public)"""
    if dry_run:
        print("[DRY RUN] Would drop all tenant schemas\n")
        return
    
    print("Dropping all tenant schemas...")
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT schema_name FROM information_schema.schemata 
            WHERE schema_name NOT IN ('public', 'pg_catalog', 'information_schema', 'pg_toast')
            AND schema_name NOT LIKE 'pg_%'
            ORDER BY schema_name;
        """)
        schemas = [row[0] for row in cursor.fetchall()]
        
        if schemas:
            for schema in schemas:
                try:
                    cursor.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE;')
                    print(f"  ✓ Dropped schema: {schema}")
                except Exception as e:
                    print(f"  ✗ Error dropping schema {schema}: {e}")
        
        # Drop all tables in public schema
        cursor.execute("""
            SELECT tablename FROM pg_tables 
            WHERE schemaname = 'public'
            ORDER BY tablename;
        """)
        tables = [row[0] for row in cursor.fetchall()]
        
        if tables:
            for table in tables:
                try:
                    cursor.execute(f'DROP TABLE IF EXISTS "{table}" CASCADE;')
                    print(f"  ✓ Dropped table: {table}")
                except Exception as e:
                    print(f"  ✗ Error dropping table {table}: {e}")
        
        connection.commit()
    
    print("✓ Database cleared!\n")


def delete_migration_files(dry_run=False):
    """Delete all migration files except __init__.py"""
    if dry_run:
        print("[DRY RUN] Would delete all migration files\n")
        return
    
    print("Deleting migration files...")
    
    # Find all local apps with migrations
    local_apps = [
        'common', 'users', 'core', 'academics', 'students', 'staff',
        'grading', 'finance', 'accounting', 'hr', 'payroll',
        'settings', 'reports', 'defaults'
    ]
    
    total = 0
    for app_name in local_apps:
        try:
            app_module = __import__(app_name, fromlist=[''])
            app_path = Path(app_module.__file__).parent
            migrations_dir = app_path / 'migrations'
            
            if migrations_dir.exists():
                for file in migrations_dir.iterdir():
                    if file.is_file() and file.name != '__init__.py' and file.name.endswith('.py'):
                        file.unlink()
                        total += 1
                print(f"  ✓ {app_name}: cleaned")
        except (ImportError, AttributeError):
            continue
    
    print(f"✓ Deleted {total} migration file(s)\n")


def create_migrations(dry_run=False):
    """Create fresh migrations"""
    if dry_run:
        print("[DRY RUN] Would create new migrations\n")
        return
    
    print("Creating fresh migrations...")
    try:
        call_command('makemigrations', verbosity=0)
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
        call_command('migrate_schemas', '--shared', verbosity=0)
        print("✓ Shared schema migrated!\n")
    except Exception as e:
        print(f"✗ Error migrating shared schema: {e}\n")
        raise


def create_public_tenant(dry_run=False):
    """Create public tenant"""
    if dry_run:
        print("[DRY RUN] Would create public tenant\n")
        return
    
    print("Creating public tenant...")
    
    try:
        from core.models import Tenant
        from tenant_users.tenants.utils import create_public_tenant as create_public_tenant_func
        
        public_schema = get_public_schema_name()
        
        # Get configuration from environment or use defaults
        domain_url = os.environ.get('PUBLIC_TENANT_DOMAIN', 'public.localhost')
        owner_email = os.environ.get('PUBLIC_TENANT_OWNER_EMAIL', 'admin@ezyschool.app')
        owner_password = os.environ.get('PUBLIC_TENANT_OWNER_PASSWORD', 'Ezyschool.net')
        owner_id_number = os.environ.get('PUBLIC_TENANT_OWNER_ID_NUMBER', 'admin001')
        owner_username = os.environ.get('PUBLIC_TENANT_OWNER_USERNAME', 'admin')
        
        # Prepare owner data
        owner_extra = {
            "password": owner_password,
            "username": owner_username,
            "id_number": owner_id_number,
            "first_name": "System",
            "last_name": "Administrator",
            "account_type": UserAccountType.GLOBAL,
            "role": Roles.SUPERADMIN,
            "gender": "male",
            "is_default_password": False,
            "last_password_updated": timezone.now(),
        }
        
        try:
            public_tenant, domain, owner = create_public_tenant_func(
                domain_url=domain_url,
                owner_email=owner_email,
                is_superuser=True,
                is_staff=True,
                **owner_extra
            )
            print(f"  ✓ Public tenant created")
            print(f"    Domain: {domain_url}")
            print(f"    Owner: {owner_email}\n")
        except Exception as e:
            if "already exists" in str(e):
                print(f"  Public tenant already exists\n")
            else:
                raise
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
        call_command('migrate_schemas', verbosity=0)
        print("✓ Tenant schemas migrated!\n")
    except Exception as e:
        print(f"✗ Error migrating tenant schemas: {e}\n")
        raise


def ensure_superadmin_configured(dry_run=False):
    """Ensure superadmin has all required fields"""
    if dry_run:
        print("[DRY RUN] Would ensure superadmin is configured\n")
        return
    
    print("Ensuring superadmin is properly configured...")
    
    try:
        User = get_user_model()
        email = "admin@ezyschool.app"
        
        user = User.objects.get(email=email)
        
        # Force-set all required fields
        user.username = "admin"
        user.role = Roles.SUPERADMIN
        user.account_type = UserAccountType.GLOBAL
        user.first_name = "System"
        user.last_name = "Administrator"
        user.id_number = "admin001"
        user.is_active = True
        user.save()
        
        print(f"  ✓ Superadmin configured:")
        print(f"    Email: {user.email}")
        print(f"    Username: {user.username}")
        print(f"    Role: {user.role}\n")
    except User.DoesNotExist:
        print("  ⚠️  Superadmin not found - will be created by public tenant\n")
    except Exception as e:
        print(f"✗ Error configuring superadmin: {e}\n")
        raise


def collect_static(dry_run=False):
    """Collect static files"""
    if dry_run:
        print("[DRY RUN] Would collect static files\n")
        return
    
    print("Collecting static files...")
    try:
        call_command('collectstatic', '--noinput', '--clear', verbosity=0)
        print("✓ Static files collected!\n")
    except Exception as e:
        print(f"⚠️  Warning: {e}\n")


def main():
    parser = argparse.ArgumentParser(
        description='Complete database reset for development',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
⚠️  WARNING: This will DELETE ALL DATA from the database!

Examples:
  python reset_database.py              # Interactive reset
  python reset_database.py --force      # Skip confirmation
  python reset_database.py --dry-run    # Preview actions
        """
    )
    parser.add_argument('--force', action='store_true', help='Skip confirmation')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done')
    
    args = parser.parse_args()
    
    # Confirmation
    if not args.force and not args.dry_run:
        print("\n" + "="*70)
        print("⚠️  WARNING: This will DELETE ALL DATABASE DATA!")
        print("="*70)
        response = input("\nType 'reset' to confirm: ").strip().lower()
        if response != 'reset':
            print("Cancelled.\n")
            sys.exit(0)
    
    print("\n" + "="*70)
    print("DATABASE RESET PIPELINE")
    print("="*70 + "\n")
    
    try:
        delete_all_schemas(args.dry_run)
        delete_migration_files(args.dry_run)
        create_migrations(args.dry_run)
        migrate_shared_schema(args.dry_run)
        create_public_tenant(args.dry_run)
        migrate_tenant_schemas(args.dry_run)
        ensure_superadmin_configured(args.dry_run)
        collect_static(args.dry_run)
        
        print("="*70)
        if args.dry_run:
            print("DRY RUN COMPLETE - No changes made")
        else:
            print("✅ DATABASE RESET COMPLETE!")
            print("\nSuperadmin Credentials:")
            print("  Email:    admin@ezyschool.app")
            print("  Username: admin")
            print("  Password: Ezyschool.net")
        print("="*70)
        
    except Exception as e:
        print(f"\n✗ Reset failed: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
