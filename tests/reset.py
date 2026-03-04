import os

import django

# Initialize Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "api.settings")
django.setup()

from reset.cleanup import run_cleanup
from reset.data import run_data_creation
from reset.schema import recreate_schema

if __name__ == "__main__":
    print("Resetting the database...")
    print("---------------------------------")
    run_cleanup()
    recreate_schema()
    run_data_creation()
    print("---------------------------------")
    print("Database reset complete.")
