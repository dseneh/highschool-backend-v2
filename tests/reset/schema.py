from django.core.management import call_command


def recreate_schema():
    call_command("makemigrations")
    call_command("migrate")
    print("Recreated the database schema...")
