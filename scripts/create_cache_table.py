#!/usr/bin/env python
"""
Create cache table for Django database cache backend.
This script can be run manually if the cache table is missing.
"""

import os

import django

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "api.settings")
django.setup()

from django.conf import settings
from django.core.cache import caches
from django.core.management import execute_from_command_line


def create_cache_table():
    """Create the cache table for database cache backend."""
    print("🗃️  Creating cache table...")

    try:
        # Check if we're using database cache
        cache_config = settings.CACHES.get("default", {})
        backend = cache_config.get("BACKEND", "")

        if "db.DatabaseCache" in backend:
            table_name = cache_config.get("LOCATION", "cache_table")
            print(f"📋 Using database cache with table: {table_name}")

            # Create the cache table
            execute_from_command_line(["manage.py", "createcachetable"])
            print("✅ Cache table created successfully!")

        else:
            print(f"ℹ️  Using {backend} - no database cache table needed")

    except Exception as e:
        print(f"❌ Error creating cache table: {e}")
        return False

    return True


if __name__ == "__main__":
    create_cache_table()
